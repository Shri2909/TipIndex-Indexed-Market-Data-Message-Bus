// Audit: pool-pressure (ForceEvict / RejectPublish) property and differential
// tests. The production suite checks pressure with one fixed five-publish
// fixture (tests/fuzz/pressure_fixture.hpp) and keeps every randomized
// differential campaign pressure-free. This file drives randomized schedules
// with undersized pools against an independent model of:
//   * ring placement, PAD and capacity-only retention (re-derived here),
//   * the documented ForceEvict rule (ARCHITECTURE 5.5: advance the tail until
//     one block frees, choosing the block whose freeing needs least eviction),
//   * the common replay checkpoint/expiry contract (ARCHITECTURE 3.6),
// and compares every replay mode and merge kernel against that model.
#include "scan_oracle.hpp"
#include "tiplog/engine/engine.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <map>
#include <optional>
#include <random>
#include <string>
#include <vector>

namespace tiplog {
namespace {

struct Item {
  LogPos pos{};
  std::uint64_t size{};
  std::optional<Seq> seq;
};
struct Record {
  std::string path;
  std::vector<std::byte> payload;
  LogPos pos{};
  std::uint64_t size{};
};

// Independent restatement of ring placement and retention; it reads no
// production state except where a test explicitly compares against it.
class Model {
 public:
  explicit Model(std::uint64_t capacity) : capacity_(capacity) {}
  struct Placement {
    LogPos pad_pos{}, data_pos{}, end_pos{};
    std::uint64_t pad{}, need{};
  };
  Placement place(std::size_t payload) const {
    const std::uint64_t need = ((16 + payload + 7) / 8) * 8;
    const std::uint64_t room = capacity_ - head_ % capacity_;
    const std::uint64_t pad = room < need ? room : 0;
    return {head_, head_ + pad, head_ + pad + need, pad, need};
  }
  // Capacity-only tail after a placement ending at end_pos.
  LogPos capacity_tail(LogPos end_pos) const {
    const LogPos floor = end_pos > capacity_ ? end_pos - capacity_ : 0;
    for (std::size_t i = first_; i < items_.size(); ++i)
      if (items_[i].pos >= floor) return items_[i].pos;
    return head_;
  }
  std::uint64_t data_between(LogPos from, LogPos to) const {
    std::uint64_t count = 0;
    for (std::size_t i = first_; i < items_.size(); ++i)
      if (items_[i].seq && items_[i].pos >= from && items_[i].pos < to) ++count;
    return count;
  }
  std::uint64_t record_size_at(LogPos pos) const {
    for (std::size_t i = first_; i < items_.size(); ++i)
      if (items_[i].pos == pos) return items_[i].size;
    ADD_FAILURE() << "no retained item at " << pos;
    return 0;
  }
  bool is_boundary(LogPos pos) const {
    if (pos == head_) return true;
    for (std::size_t i = first_; i < items_.size(); ++i)
      if (items_[i].pos == pos) return true;
    return false;
  }
  Seq commit(const Placement& p, LogPos new_tail, std::string path,
             std::vector<std::byte> payload) {
    if (p.pad) items_.push_back({p.pad_pos, p.pad, std::nullopt});
    items_.push_back({p.data_pos, p.need, next_seq_});
    records_.push_back({std::move(path), std::move(payload), p.data_pos, p.need});
    head_ = p.end_pos;
    while (first_ < items_.size() && items_[first_].pos < new_tail) ++first_;
    return next_seq_++;
  }
  LogPos head_pos() const { return head_; }
  LogPos tail_pos() const { return first_ < items_.size() ? items_[first_].pos : head_; }
  Seq head_seq() const { return next_seq_; }
  Seq tail_seq() const {
    for (std::size_t i = first_; i < items_.size(); ++i)
      if (items_[i].seq) return *items_[i].seq;
    return next_seq_;
  }
  const Record& record(Seq seq) const { return records_.at(seq - 1); }

 private:
  std::uint64_t capacity_;
  std::vector<Item> items_;
  std::vector<Record> records_;
  std::size_t first_{};
  LogPos head_{};
  Seq next_seq_{1};
};

// Expected outcome of the documented checkpoint/expiry contract for one replay.
class ModelReplay {
 public:
  ModelReplay(const Model& model, const SubscriptionSpec& sub, Seq after)
      : model_(&model), sub_(sub), after_(after), last_(after),
        upper_seq_(model.head_seq() - 1), upper_pos_(model.head_pos()) {
    if (after >= upper_seq_) {
      status_ = Status::Done;
      if (after == upper_seq_) checkpoint_ = ResumeCheckpoint{upper_seq_, upper_pos_};
      return;
    }
    if (after + 1 < model.tail_seq()) {
      status_ = Status::Error;
      error_ = ReplayError{ReplayError::HistoryExpired, after, after, model.tail_seq()};
      return;
    }
    next_ = after + 1;
    checkpoint_ = ResumeCheckpoint{after, model.record(next_).pos};
  }
  Status next_batch(std::size_t max, std::vector<Seq>& out) {
    out.clear();
    if (max == 0 || status_ != Status::More) return status_;
    if (checkpoint_->next_pos == upper_pos_) {
      status_ = Status::Done;
      checkpoint_ = ResumeCheckpoint{upper_seq_, upper_pos_};
      return status_;
    }
    if (checkpoint_->next_pos < model_->tail_pos()) {
      status_ = Status::Error;
      error_ = ReplayError{ReplayError::FellBehind, after_, last_, model_->tail_seq()};
      return status_;
    }
    for (; next_ <= upper_seq_; ++next_) {
      const auto& r = model_->record(next_);
      if (!ref::ScanOracle::matches(sub_, r.path)) continue;
      out.push_back(next_);
      last_ = next_;
      checkpoint_ = ResumeCheckpoint{next_, r.pos + r.size};
      if (out.size() == max) {
        ++next_;
        return Status::More;
      }
    }
    status_ = Status::Done;
    checkpoint_ = ResumeCheckpoint{upper_seq_, upper_pos_};
    return status_;
  }
  Status status() const { return status_; }
  std::optional<ReplayError> error() const { return error_; }
  std::optional<ResumeCheckpoint> checkpoint() const { return checkpoint_; }

 private:
  const Model* model_;
  SubscriptionSpec sub_;
  Seq after_{}, last_{}, upper_seq_{};
  LogPos upper_pos_{};
  Seq next_{};
  Status status_{Status::More};
  std::optional<ReplayError> error_;
  std::optional<ResumeCheckpoint> checkpoint_;
};

struct Prediction {
  bool pressure{};
  LogPos tail{};
};

// Independent prediction of whether this publication needs the pool-pressure
// policy and, for ForceEvict, where the tail must end. Block membership and
// last positions are read from metadata; sealing is re-derived from the
// documented rule (full or not the partition's newest block).
Prediction predict(const Engine& engine, const Model& model, PartitionId partition,
                   const Model::Placement& placement) {
  const auto& meta = engine.index()->metadata();
  const auto entries = engine.index()->config().entries_per_block;
  const LogPos t0 = model.capacity_tail(placement.end_pos);
  std::optional<std::size_t> newest;
  std::uint64_t free_blocks = 0;
  bool freeable = false;
  LogPos minimum_last = std::numeric_limits<LogPos>::max();
  for (std::size_t b = 0; b < meta.size(); ++b) {
    if (meta[b].partition == index::none) {
      ++free_blocks;
      continue;
    }
    minimum_last = std::min(minimum_last, meta[b].last_pos);
    if (meta[b].last_pos < t0) freeable = true;
    if (meta[b].partition == partition &&
        (!newest || meta[b].base_pos > meta[*newest].base_pos))
      newest = b;
  }
  const bool needs_block = !newest || meta[*newest].last_pos < t0 ||
                           meta[*newest].count == entries;
  Prediction result;
  result.tail = t0;
  if (needs_block && free_blocks == 0 && !freeable) {
    result.pressure = true;
    const auto victim_end = minimum_last + model.record_size_at(minimum_last);
    result.tail = std::max(t0, victim_end);
  }
  return result;
}

struct Spec {
  SubscriptionSpec sub;
};

void run_schedule(std::uint64_t seed, PoolPolicy policy, std::uint64_t operations,
                  std::uint64_t* pressure_events, std::uint64_t* replay_checks) {
  std::mt19937_64 random(seed);
  const std::size_t capacity = std::size_t{256} << (random() % 5);  // 256..4096
  EngineConfig config;
  config.ring_bytes = capacity;
  config.max_record_bytes = std::min<std::size_t>(capacity / 2, 256);
  config.ckpt_log2 = static_cast<std::uint32_t>(random() % 4);
  config.index.blocks = static_cast<std::uint32_t>(1 + random() % 6);
  config.index.entries_per_block = 1U << (random() % 4);
  const std::array<std::uint64_t, 3> sweeps{0, 1, 7};
  config.index.sweep_evictions = sweeps[random() % sweeps.size()];
  config.pool_policy = policy;
  Engine engine(config);
  Model model(capacity);
  const std::vector<std::string> paths{"p/A/x", "p/A/y", "p/B/x", "p/C",
                                       "q/D/x/z", "r", "p/A/y/deep"};
  const std::vector<SubscriptionSpec> specs{
      {{{Term::Subtree, "p/A"}}},
      {{{Term::Exact, "p/A/x"}}},
      {{{Term::Subtree, "p"}}},
      {{{Term::Subtree, "p/A"}, {Term::Exact, "p/B/x"}, {Term::Exact, "q/D/x/z"}}},
      {{{Term::Exact, "r"}}},
      {{{Term::Subtree, "q/D/x"}}},
      {{{Term::Exact, "missing/x/y"}}},
      {{{Term::Exact, "p/C"}, {Term::Exact, "r"}}}};
  std::vector<subs::CompiledSubscription> compiled;
  for (const auto& spec : specs) compiled.push_back(engine.compile(spec));
  std::vector<TopicId> topics;
  for (const auto& path : paths) topics.push_back(engine.intern(path));

  struct Open {
    Replay actual;
    ModelReplay expected;
  };
  std::vector<std::optional<Open>> open(6);
  std::vector<Delivered> got;
  std::vector<Seq> want;
  const std::array<ReplayMode, 3> modes{ReplayMode::Scan, ReplayMode::Indexed, ReplayMode::Auto};
  const std::array<MergeKernel, 4> kernels{MergeKernel::StdPQ, MergeKernel::BinHeap,
                                           MergeKernel::Quad, MergeKernel::Loser};

  for (std::uint64_t op = 0; op < operations; ++op) {
    SCOPED_TRACE("seed=" + std::to_string(seed) + " op=" + std::to_string(op));
    const auto action = random() % 100;
    if (action < 55) {
      const auto which = random() % paths.size();
      std::vector<std::byte> payload(random() % (config.max_record_bytes - 16 + 1));
      for (auto& b : payload) b = static_cast<std::byte>(random());
      const auto placement = model.place(payload.size());
      const auto partition = engine.registry().get(topics[which]).partition;
      const auto prediction = predict(engine, model, partition, placement);
      const auto before = engine.stats();
      const auto ring_before = engine.ring().stats();
      if (prediction.pressure && policy == PoolPolicy::RejectPublish) {
        EXPECT_THROW((void)engine.publish(topics[which], payload), PoolExhausted);
        const auto after = engine.stats();
        ASSERT_EQ(after.head_pos, before.head_pos);
        ASSERT_EQ(after.tail_pos, before.tail_pos);
        ASSERT_EQ(after.head_seq, before.head_seq);
        ASSERT_EQ(after.tail_seq, before.tail_seq);
        ASSERT_EQ(engine.ring().stats(), ring_before);
        ++*pressure_events;
      } else {
        const auto seq = engine.publish(topics[which], payload);
        const auto expected_seq =
            model.commit(placement, prediction.tail, paths[which], payload);
        ASSERT_EQ(seq, expected_seq);
        const auto ring_after = engine.ring().stats();
        ASSERT_EQ(engine.stats().tail_pos, model.tail_pos())
            << "pressure=" << prediction.pressure;
        ASSERT_EQ(engine.stats().tail_seq, model.tail_seq());
        ASSERT_EQ(engine.stats().head_pos, model.head_pos());
        const auto capacity_tail = before.tail_pos;  // only used for messages
        (void)capacity_tail;
        if (prediction.pressure) {
          ++*pressure_events;
          EXPECT_GT(ring_after.pressure_bytes_evicted, ring_before.pressure_bytes_evicted);
        } else {
          EXPECT_EQ(ring_after.pressure_data_evicted, ring_before.pressure_data_evicted);
          EXPECT_EQ(ring_after.pressure_bytes_evicted, ring_before.pressure_bytes_evicted);
        }
        const auto item = engine.ring().at(placement.data_pos);
        ASSERT_FALSE(item.pad);
        ASSERT_EQ(item.seq, seq);
        ASSERT_TRUE(std::ranges::equal(item.payload, payload));
      }
    } else if (action < 70) {
      const auto slot = random() % open.size();
      const auto spec = random() % specs.size();
      const auto upper = engine.stats().head_seq - 1;
      Seq after = 0;
      switch (random() % 4) {
        case 0: after = engine.stats().tail_seq - 1; break;
        case 1: after = upper; break;
        case 2: after = upper == 0 ? 0 : random() % (upper + 1); break;
        default: after = engine.stats().tail_seq > 1 ? engine.stats().tail_seq - 2 : 0;
      }
      const auto mode = modes[random() % modes.size()];
      const auto kernel = kernels[random() % kernels.size()];
      open[slot].emplace(Open{engine.open_replay(compiled[spec], after, mode, kernel),
                              ModelReplay(model, specs[spec], after)});
      ASSERT_EQ(open[slot]->actual.status(), open[slot]->expected.status());
      ASSERT_EQ(open[slot]->actual.error(), open[slot]->expected.error());
      ASSERT_EQ(open[slot]->actual.checkpoint(), open[slot]->expected.checkpoint());
    } else if (action < 97) {
      auto& pair = open[random() % open.size()];
      if (!pair) continue;
      const auto budget = static_cast<std::size_t>(random() % 6);
      const auto actual_status = pair->actual.next_batch(budget, got);
      const auto expected_status = pair->expected.next_batch(budget, want);
      ASSERT_EQ(actual_status, expected_status);
      ASSERT_EQ(got.size(), want.size());
      for (std::size_t i = 0; i < got.size(); ++i) {
        ASSERT_EQ(got[i].seq, want[i]);
        const auto& r = model.record(want[i]);
        ASSERT_EQ(got[i].pos, r.pos);
        ASSERT_EQ(engine.registry().get(got[i].topic).path, r.path);
        ASSERT_TRUE(std::ranges::equal(got[i].payload, r.payload));
      }
      ASSERT_EQ(pair->actual.error(), pair->expected.error());
      ASSERT_EQ(pair->actual.checkpoint(), pair->expected.checkpoint());
      ++*replay_checks;
    } else {
      open[random() % open.size()].reset();
    }
    ASSERT_NO_THROW(engine.check_invariants());
  }
}

TEST(AuditPressure, ForceEvictMatchesIndependentPressureModel) {
  std::uint64_t pressure = 0, checks = 0;
  for (std::uint64_t seed = 1; seed <= 400; ++seed) {
    run_schedule(seed, PoolPolicy::ForceEvict, 2000, &pressure, &checks);
    if (HasFatalFailure()) return;
  }
  RecordProperty("pressure_events", std::to_string(pressure));
  RecordProperty("replay_batches_checked", std::to_string(checks));
  std::cout << "[audit] ForceEvict pressure events=" << pressure
            << " replay batches checked=" << checks << "\n";
  EXPECT_GT(pressure, 1000U) << "schedule must actually exercise pressure";
}

TEST(AuditPressure, RejectPublishRejectsExactlyWhenPressureIsRequired) {
  std::uint64_t pressure = 0, checks = 0;
  for (std::uint64_t seed = 1001; seed <= 1400; ++seed) {
    run_schedule(seed, PoolPolicy::RejectPublish, 2000, &pressure, &checks);
    if (HasFatalFailure()) return;
  }
  std::cout << "[audit] RejectPublish rejections=" << pressure
            << " replay batches checked=" << checks << "\n";
  EXPECT_GT(pressure, 1000U);
}

}  // namespace
}  // namespace tiplog
