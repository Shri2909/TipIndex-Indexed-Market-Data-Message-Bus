#include "tiplog/engine/engine.hpp"

#include <cassert>
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>
#include <variant>

namespace tiplog {
namespace {
void validate_mode(ReplayMode mode, MergeKernel kernel) {
  if (mode != ReplayMode::Scan && mode != ReplayMode::Indexed &&
      mode != ReplayMode::Auto)
    throw std::invalid_argument("invalid replay mode");
  switch (kernel) {
  case MergeKernel::StdPQ:
  case MergeKernel::BinHeap:
  case MergeKernel::Quad:
  case MergeKernel::Loser:
    break;
  default:
    throw std::invalid_argument("invalid merge kernel");
  }
}
} // namespace
Engine::Engine(const EngineConfig &config)
    : config_(config), registry_(config.registry_limits),
      ring_(ring::RingConfig{config.ring_bytes, config.max_record_bytes,
                             config.ckpt_log2, config.position_limit,
                             config.sequence_limit}) {
  if (config.minimum_record_bytes != 16 && config.minimum_record_bytes != 32)
    throw std::invalid_argument("minimum DATA record must be 16 or 32 bytes");
  if (config.minimum_record_bytes > config.max_record_bytes)
    throw std::invalid_argument("minimum DATA record exceeds configured maximum");
  if (config.pool_policy != PoolPolicy::ForceEvict &&
      config.pool_policy != PoolPolicy::RejectPublish)
    throw std::invalid_argument("invalid index pool policy");
  if (config.auto_max_partitions > merge::max_cursors ||
      !std::isfinite(config.auto_max_index_fraction) ||
      config.auto_max_index_fraction < 0 ||
      config.auto_max_index_fraction > 1)
    throw std::invalid_argument("invalid uncalibrated Auto policy thresholds");
  if (config.index_enabled)
    index_ = std::make_unique<index::Index>(config.index);
}

Engine::~Engine() {
  assert(lifetime_->active_replays == 0 &&
         "Replay must be closed before Engine destruction");
  lifetime_->alive = false;
}

Seq Engine::publish(TopicId topic, std::span<const std::byte> payload) {
  // Registry validation precedes ring eviction or any visible state mutation.
  const auto partition = registry_.get(topic).partition;
  auto layout = ring_.dry_run(payload.size());
  if (layout.record_bytes < config_.minimum_record_bytes)
    throw std::length_error("record below configured minimum DATA size");
  if (!index_) {
    auto plan = ring_.plan_append(payload);
    const auto published = ring_.commit(std::move(plan), topic);
    retained_data_count_ = retained_data_count_ - layout.data_evicted + 1;
    return published.seq;
  }
  // Preparation may reserve unused control capacity, but cannot evict, free,
  // append an entry or advance sequence. Every rejecting operation precedes
  // both nonallocating commits. Index reclamation reads metadata only.
  auto prepared = index_->prepare_append(
      partition, layout.data_pos, layout.tail_pos,
      registry_.partition_count(), layout.data_evicted);
  LogPos minimum_tail = 0;
  if (const auto *pressure = std::get_if<index::NeedTailThrough>(&prepared)) {
    if (config_.pool_policy == PoolPolicy::RejectPublish)
      throw PoolExhausted();
    const auto victim = ring_.at(pressure->last_pos);
    if (victim.pad)
      throw std::logic_error("index pressure victim must reference DATA");
    minimum_tail = victim.pos + victim.size;
    layout = ring_.dry_run(payload.size(), minimum_tail);
    prepared = index_->prepare_append(
        partition, layout.data_pos, layout.tail_pos,
        registry_.partition_count(), layout.data_evicted);
    if (std::holds_alternative<index::NeedTailThrough>(prepared))
      throw std::logic_error("pressure preparation did not free one block");
  }
  auto plan = ring_.plan_append(payload, minimum_tail);
  const auto retained = retained_data_count_ - layout.data_evicted + 1;
  const auto published = ring_.commit(std::move(plan), topic);
  index_->commit(std::move(std::get<index::PreparedAppend>(prepared)), retained);
  retained_data_count_ = retained;
  return published.seq;
}
Replay Engine::open_replay(const subs::CompiledSubscription &sub, Seq after,
                           ReplayMode mode, MergeKernel kernel) {
  validate_mode(mode, kernel);
  return Replay(*this, sub, after, std::nullopt, mode, kernel);
}
Replay Engine::open_replay(const subs::CompiledSubscription &sub,
                           ResumeCheckpoint checkpoint, ReplayMode mode,
                           MergeKernel kernel) {
  validate_mode(mode, kernel);
  return Replay(*this, sub, checkpoint.after_seq, checkpoint, mode, kernel);
}
Tail Engine::open_tail(const subs::CompiledSubscription &sub, Seq after,
                       ReplayMode mode, MergeKernel kernel) {
  if (after > ring_.head_seq() - 1)
    throw InvalidRange();
  validate_mode(mode, kernel);
  return Tail(*this, sub, after, mode, kernel);
}
EngineStats Engine::stats() const noexcept {
  return {ring_.head_pos(), ring_.tail_pos(), ring_.head_seq(),
          ring_.tail_seq()};
}
void Engine::check_invariants() const {
  ring_.check_invariants();
  std::vector<std::pair<LogPos, PartitionId>> retained;
  for (auto pos = ring_.tail_pos(); pos < ring_.head_pos();) {
    const auto item = ring_.at(pos);
    if (!item.pad) {
      const auto &topic = registry_.get(item.topic);
      retained.emplace_back(pos, topic.partition);
    }
    pos += item.size;
  }
  if (retained.size() != retained_data_count_)
    throw std::logic_error("engine retained DATA count mismatch");
  if (index_) {
    index_->check_invariants(ring_.tail_pos());
    // This scan starts from the retained log rather than the index's gauge or
    // chain traversal; sorting decoded postings proves exact one-to-one cover.
    std::vector<std::pair<LogPos, PartitionId>> postings;
    for (const auto &entry : index_->entries())
      if (entry.pos >= ring_.tail_pos())
        postings.emplace_back(entry.pos, entry.partition);
    std::sort(postings.begin(), postings.end());
    if (postings != retained)
      throw std::logic_error("retained ring DATA/index postings mismatch");
  }
}

Replay::Replay(Engine &engine, const subs::CompiledSubscription &sub, Seq after,
               std::optional<ResumeCheckpoint> supplied, ReplayMode mode,
               MergeKernel kernel)
    : engine_(&engine), lifetime_(engine.lifetime_), sub_(sub),
      requested_after_(after), last_delivered_(after),
      upper_seq_(engine.ring_.head_seq() - 1),
      upper_pos_(engine.ring_.head_pos()), mode_(mode), kernel_(kernel) {
  if (!sub.belongs_to(engine.registry_))
    throw std::invalid_argument(
        "subscription belongs to another or expired registry");
  if (mode_ != ReplayMode::Scan) {
    if (!engine.index_ && mode_ == ReplayMode::Indexed)
      throw std::invalid_argument("Indexed replay requires enabled index");
    if (!engine.index_ || sub.wide()) {
      mode_ = ReplayMode::Scan;
    } else {
      const auto filters = sub.filters();
      if (mode_ == ReplayMode::Auto &&
          (filters.size() > engine.config_.auto_max_partitions ||
           filters.size() > merge::max_cursors)) {
        mode_ = ReplayMode::Scan;
      } else {
        if (filters.size() > merge::max_cursors)
          throw index::RepresentationLimit("too many packed indexed cursors");
        partitions_.reserve(filters.size());
        for (const auto &filter : filters)
          partitions_.push_back(filter.partition);
        mode_ = ReplayMode::Indexed;
      }
    }
  }
  // Empty/future ranges are recognized before +1 to avoid overflow.
  if (after >= upper_seq_) {
    status_ = Status::Done;
    if (after == upper_seq_)
      checkpoint_ = ResumeCheckpoint{upper_seq_, upper_pos_};
    ++engine.lifetime_->active_replays;
    return;
  }
  if (after + 1 < engine.ring_.tail_seq()) {
    status_ = Status::Error;
    error_ = ReplayError{ReplayError::HistoryExpired, after, after,
                         engine.ring_.tail_seq()};
    ++engine.lifetime_->active_replays;
    return;
  }
  const auto canonical = engine.ring_.seek_after(after);
  const auto seek_work = engine.ring_.last_seek_metrics();
  work_.seek_data_examined += seek_work.data_examined;
  work_.seek_pads_examined += seek_work.pads_examined;
  checkpoint_ = ResumeCheckpoint{after, canonical};
  if (supplied) {
    // A completed snapshot may end before a subsequently inserted PAD. Only
    // accept the canonical next DATA, or the proven end of the preceding DATA;
    // arbitrary aligned offsets are never interpreted as ring headers.
    const auto candidate = supplied->next_pos;
    // A tail PAD remains a proven boundary even after the preceding DATA was
    // evicted. Keep that conservative progress point when its next DATA agrees.
    if (candidate < canonical && candidate == engine.ring_.tail_pos() &&
        after + 1 == engine.ring_.tail_seq()) {
      const auto tail = engine.ring_.at(candidate);
      if (tail.pad && candidate + tail.size == canonical)
        checkpoint_->next_pos = candidate;
    }
    if (candidate != canonical && after >= engine.ring_.tail_seq() &&
        after != 0) {
      const auto previous = engine.ring_.at(engine.ring_.seek_after(after - 1));
      if (previous.seq == after && candidate == previous.pos + previous.size &&
          candidate >= engine.ring_.tail_pos() && candidate < canonical) {
        checkpoint_->next_pos = candidate;
      }
    }
  }
  if (mode == ReplayMode::Auto && mode_ == ReplayMode::Indexed) {
    std::uint64_t estimate = 0;
    for (const auto partition : partitions_)
      estimate += engine.index_->estimate_count(
          partition, checkpoint_->next_pos, upper_pos_);
    const auto range_records = upper_seq_ - after;
    if (static_cast<long double>(estimate) >
        static_cast<long double>(range_records) *
            engine.config_.auto_max_index_fraction) {
      mode_ = ReplayMode::Scan;
      partitions_.clear();
    }
  }
  ++engine.lifetime_->active_replays;
}

void Replay::release() noexcept {
  if (const auto anchor = lifetime_.lock()) {
    assert(anchor->active_replays != 0);
    --anchor->active_replays;
  }
  lifetime_.reset();
  engine_ = nullptr;
}
Replay::~Replay() { release(); }
Replay::Replay(Replay &&other) noexcept
    : engine_(std::exchange(other.engine_, nullptr)),
      lifetime_(std::move(other.lifetime_)), sub_(std::move(other.sub_)),
      requested_after_(other.requested_after_),
      last_delivered_(other.last_delivered_), upper_seq_(other.upper_seq_),
      upper_pos_(other.upper_pos_), status_(other.status_),
      error_(other.error_), checkpoint_(other.checkpoint_), mode_(other.mode_),
      kernel_(other.kernel_), partitions_(std::move(other.partitions_)),
      work_(other.work_) {}
Replay &Replay::operator=(Replay &&other) noexcept {
  if (this == &other)
    return *this;
  release();
  engine_ = std::exchange(other.engine_, nullptr);
  lifetime_ = std::move(other.lifetime_);
  sub_ = std::move(other.sub_);
  requested_after_ = other.requested_after_;
  last_delivered_ = other.last_delivered_;
  upper_seq_ = other.upper_seq_;
  upper_pos_ = other.upper_pos_;
  status_ = other.status_;
  error_ = other.error_;
  checkpoint_ = other.checkpoint_;
  mode_ = other.mode_;
  kernel_ = other.kernel_;
  partitions_ = std::move(other.partitions_);
  work_ = other.work_;
  return *this;
}

Status Replay::next_batch(std::size_t max, std::vector<Delivered> &out) {
  out.clear();
  return next_batch_into(max, out);
}
Status Replay::next_batch_into(std::size_t max, std::vector<Delivered> &out) {
  const auto initial_output = out.size();
  const auto anchor = lifetime_.lock();
  if (!anchor || !anchor->alive)
    throw std::logic_error("Replay outlived its Engine");
  if (max == 0 || status_ != Status::More)
    return status_;
  auto &ring = engine_->ring_;
  if (checkpoint_->next_pos == upper_pos_) {
    status_ = Status::Done;
    checkpoint_ = ResumeCheckpoint{upper_seq_, upper_pos_};
    return status_;
  }
  if (checkpoint_->next_pos < ring.tail_pos()) {
    status_ = Status::Error;
    error_ = ReplayError{ReplayError::FellBehind, requested_after_,
                         last_delivered_, ring.tail_seq()};
    return status_;
  }
  if (mode_ == ReplayMode::Indexed) {
    // Re-seek at each batch boundary. The consumed previous record's block may
    // have been recycled while the conservative unread checkpoint remains
    // retained. No cached metadata is touched before the common checks above.
    // Within a batch there is no engine mutation; cursor generation is checked
    // by index advance. Filters are reacquired because intern() may grow them.
    std::vector<index::Cursor> cursors;
    std::vector<merge::Key> heads;
    std::vector<const subs::PartitionFilter *> filters;
    cursors.reserve(partitions_.size());
    heads.reserve(partitions_.size());
    filters.reserve(partitions_.size());
    const auto count = static_cast<std::uint32_t>(partitions_.size());
    for (std::uint32_t i = 0; i < count; ++i) {
      auto cursor = engine_->index_->seek(partitions_[i], checkpoint_->next_pos);
      ++work_.index_seeks;
      heads.push_back(cursor.valid() && cursor.pos < upper_pos_
                          ? merge::pack(cursor.pos, i, count)
                          : merge::sentinel);
      cursors.push_back(cursor);
      filters.push_back(sub_.partition_filter(partitions_[i]));
    }
    auto kernel = merge::make_kernel(kernel_, heads);
    const auto full = std::visit([&](auto &queue) {
      while (!queue.empty()) {
        const auto key = queue.top();
        const auto pos = merge::position(key);
        const auto id = merge::cursor_id(key);
        if (pos < ring.tail_pos())
          throw std::logic_error("retained unread checkpoint has expired cursor");
        const auto item = ring.at(pos);
        ++work_.entries_visited;
        ++work_.records_fetched;
        work_.bytes_inspected += item.size;
        if (item.pad)
          throw std::logic_error("index cursor references PAD");
        const auto &topic = engine_->registry_.get(item.topic);
        const auto *filter = filters[id];
        if (filter != nullptr && filter->matches(topic.local_id)) {
          out.push_back({item.seq, item.pos, item.topic, item.payload});
          ++work_.delivered;
          checkpoint_ = ResumeCheckpoint{item.seq, item.pos + item.size};
          last_delivered_ = item.seq;
          if (out.size() - initial_output == max)
            return true;
        }
        auto &cursor = cursors[id];
        engine_->index_->advance(cursor, ring.tail_pos());
        queue.replace_top(cursor.valid() && cursor.pos < upper_pos_
                              ? merge::pack(cursor.pos, id, count)
                              : merge::sentinel);
      }
      return false;
    }, kernel);
    if (full)
      return Status::More;
    checkpoint_ = ResumeCheckpoint{upper_seq_, upper_pos_};
    status_ = Status::Done;
    return status_;
  }
  while (checkpoint_->next_pos < upper_pos_) {
    const auto item = ring.at(checkpoint_->next_pos);
    work_.bytes_inspected += item.size;
    if (item.pad)
      ++work_.pads_inspected;
    else
      ++work_.records_fetched;
    if (!item.pad && sub_.matches(item.topic)) {
      // Preserve the unread record if output allocation throws.
      out.push_back({item.seq, item.pos, item.topic, item.payload});
      ++work_.delivered;
      checkpoint_ = ResumeCheckpoint{item.seq, item.pos + item.size};
      last_delivered_ = item.seq;
      if (out.size() - initial_output == max)
        return Status::More;
    } else {
      checkpoint_->next_pos += item.size;
      if (!item.pad)
        checkpoint_->after_seq = item.seq;
    }
  }
  checkpoint_ = ResumeCheckpoint{upper_seq_, upper_pos_};
  status_ = Status::Done;
  return status_;
}

Tail::Tail(Engine &engine, const subs::CompiledSubscription &sub, Seq after,
           ReplayMode mode, MergeKernel kernel)
    : engine_(&engine), lifetime_(engine.lifetime_), sub_(sub), mode_(mode),
      kernel_(kernel), requested_after_(after), last_delivered_(after),
      replay_(engine.open_replay(sub, after, mode, kernel)),
      status_(replay_.status()), error_(replay_.error()),
      checkpoint_(replay_.checkpoint()) {}

Status Tail::poll(std::size_t max, std::vector<Delivered> &out) {
  out.clear();
  const auto anchor = lifetime_.lock();
  if (!anchor || !anchor->alive)
    throw std::logic_error("Tail outlived its Engine");
  if (max == 0 || status_ == Status::Error)
    return status_;
  for (;;) {
    if (replay_.status() == Status::Done) {
      // Sequence-floor validation on the new snapshot is authoritative. An old
      // completed PAD boundary can expire while every new DATA remains valid.
      if (checkpoint_->after_seq == engine_->ring_.head_seq() - 1) {
        status_ = Status::Done;
        return status_;
      }
      replay_ = engine_->open_replay(sub_, *checkpoint_, mode_, kernel_);
      if (replay_.status() == Status::Error) {
        const auto error = *replay_.error();
        error_ = ReplayError{ReplayError::FellBehind, requested_after_,
                             last_delivered_, error.oldest_retained};
        status_ = Status::Error;
        return status_;
      }
    }
    const auto before = out.size();
    status_ = replay_.next_batch_into(max - out.size(), out);
    if (out.size() != before)
      last_delivered_ = out.back().seq;
    if (replay_.checkpoint())
      checkpoint_ = replay_.checkpoint();
    if (status_ == Status::Error) {
      const auto error = *replay_.error();
      error_ = ReplayError{ReplayError::FellBehind, requested_after_,
                           last_delivered_, error.oldest_retained};
      return status_;
    }
    if (status_ == Status::More)
      return status_;
    // At most one fresh head range follows the old captured range: no engine
    // mutation interleaves, so the next loop observes its completed head.
  }
}
} // namespace tiplog
