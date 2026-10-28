#include "scan_oracle.hpp"
#include "tiplog/engine/engine.hpp"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <gtest/gtest.h>
#include <limits>
#include <memory>
#include <new>
#include <optional>
#include <random>
#include <string_view>
#include <utility>

// Isolated to this executable. Preparation uses allocations of other sizes in
// the single-partition fixture below, so this fails the first output append,
// after its rejecting prefix has actually been traversed.
namespace {
thread_local bool fail_output_append = false;
thread_local std::size_t failed_allocation_size = sizeof(tiplog::Delivered);
}
[[gnu::noinline]] void *operator new(std::size_t bytes) {
  if (fail_output_append && bytes == failed_allocation_size) {
    fail_output_append = false;
    throw std::bad_alloc();
  }
  if (auto *memory = std::malloc(bytes == 0 ? 1 : bytes))
    return memory;
  throw std::bad_alloc();
}
// std::stable_sort (including GoogleTest's own ordering) may obtain temporary
// storage through nothrow new and release it through ordinary delete. Keep both
// scalar allocation forms in this executable's malloc/free family so ASAN can
// retain its normal allocation/deallocation mismatch checks.
[[gnu::noinline]] void *operator new(std::size_t bytes,
                                   const std::nothrow_t &) noexcept {
  try {
    return ::operator new(bytes);
  } catch (...) {
    return nullptr;
  }
}
// Keep replacement allocation/deallocation boundaries visible to the compiler;
// inlining free into STL callers otherwise triggers mismatched-new-delete
// diagnostics even though this executable pairs its malloc/free replacements.
[[gnu::noinline]] void operator delete(void *memory) noexcept {
  std::free(memory);
}
[[gnu::noinline]] void operator delete(void *memory, std::size_t) noexcept {
  std::free(memory);
}
[[gnu::noinline]] void operator delete(void *memory,
                                     const std::nothrow_t &) noexcept {
  ::operator delete(memory);
}

namespace tiplog {
namespace {
struct Choice {
  ReplayMode mode;
  MergeKernel kernel;
};
constexpr std::array<Choice, 12> choices{{
    {ReplayMode::Scan, MergeKernel::StdPQ},
    {ReplayMode::Scan, MergeKernel::BinHeap},
    {ReplayMode::Scan, MergeKernel::Quad},
    {ReplayMode::Scan, MergeKernel::Loser},
    {ReplayMode::Indexed, MergeKernel::StdPQ},
    {ReplayMode::Indexed, MergeKernel::BinHeap},
    {ReplayMode::Indexed, MergeKernel::Quad},
    {ReplayMode::Indexed, MergeKernel::Loser},
    {ReplayMode::Auto, MergeKernel::StdPQ},
    {ReplayMode::Auto, MergeKernel::BinHeap},
    {ReplayMode::Auto, MergeKernel::Quad},
    {ReplayMode::Auto, MergeKernel::Loser}}};

EngineConfig config(std::size_t capacity = 8192,
                    std::uint32_t block_entries = 8) {
  EngineConfig result;
  result.ring_bytes = capacity;
  result.max_record_bytes = capacity / 2;
  result.index.blocks = static_cast<std::uint32_t>(capacity / 16 + 128);
  result.index.entries_per_block = block_entries;
  result.index.sweep_evictions = 3;
  result.auto_max_partitions = 65535;
  result.auto_max_index_fraction = 1;
  return result;
}
SubscriptionSpec exact(std::string path = "itch/A/add") {
  return {{{Term::Exact, std::move(path)}}};
}
std::vector<std::byte> payload(std::size_t size = 0, unsigned seed = 0) {
  std::vector<std::byte> result(size);
  for (std::size_t i = 0; i < size; ++i)
    result[i] = static_cast<std::byte>((seed * 29 + i * 17) & 255U);
  return result;
}
void accounting(const PollResult &result, ReplayMode mode,
                std::size_t outputs) {
  EXPECT_EQ(result.work_delta.delivered, outputs);
  EXPECT_EQ(result.inspections_used,
            mode == ReplayMode::Indexed
                ? result.work_delta.entries_visited
                : result.work_delta.records_fetched +
                      result.work_delta.pads_inspected);
  if (mode == ReplayMode::Indexed) {
    EXPECT_EQ(result.work_delta.records_fetched,
              result.work_delta.entries_visited);
    EXPECT_EQ(result.work_delta.pads_inspected, 0U);
  }
}
void no_work(const PollResult &result, Status cached_status) {
  EXPECT_EQ(result.status, cached_status);
  EXPECT_EQ(result.stop, PollStop::NoWork);
  EXPECT_EQ(result.inspections_used, 0U);
  EXPECT_EQ(result.work_delta, ReplayWork{});
}
std::string partition(std::string_view path) {
  const auto first = path.find('/');
  const auto second = first == std::string_view::npos
                          ? first
                          : path.find('/', first + 1);
  return std::string(path.substr(0, second));
}

TEST(PollBudget, V03ZeroCapsPreserveReplayAndTailWithoutFreshCapture) {
  for (const auto choice : choices) {
    Engine engine(config());
    const auto topic = engine.intern("itch/A/add");
    const auto sub = engine.compile(exact());
    engine.publish(topic, payload());
    auto replay = engine.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    auto tail = engine.open_tail(sub, Seq{1}, choice.mode, choice.kernel);
    const auto replay_checkpoint = replay.checkpoint();
    const auto tail_checkpoint = tail.checkpoint();
    engine.publish(topic, payload());
    std::vector<Delivered> out{{999, 999, 0, {}}};
    for (const auto limits : {PollLimits{0, std::nullopt}, PollLimits{0, 2},
                              PollLimits{8, 0}}) {
      no_work(replay.next_batch(limits, out), Status::More);
      EXPECT_TRUE(out.empty());
      EXPECT_EQ(replay.checkpoint(), replay_checkpoint);
      EXPECT_EQ(replay.upper_seq(), 1U);
      no_work(tail.poll(limits, out), Status::Done);
      EXPECT_TRUE(out.empty());
      EXPECT_EQ(tail.checkpoint(), tail_checkpoint);
      EXPECT_EQ(tail.upper_seq(), 1U);
    }
    const auto result = tail.poll(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::CaughtUp);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
  }
}

TEST(PollBudget, V03EmptyFutureFinishedAndMaximumCaps) {
  for (const auto choice : choices) {
    Engine engine(config());
    const auto topic = engine.intern("itch/A/add");
    const auto sub = engine.compile(exact());
    auto empty = engine.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> out;
    auto result = empty.next_batch(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::SnapshotDone);
    EXPECT_EQ(result.inspections_used, 0U);
    engine.publish(topic, payload(3, 42));
    auto future = engine.open_replay(sub, UINT64_MAX, choice.mode, choice.kernel);
    result = future.next_batch(PollLimits{8, UINT64_MAX}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::SnapshotDone);
    EXPECT_EQ(result.inspections_used, 0U);
    EXPECT_FALSE(future.checkpoint());
    auto replay = engine.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    result = replay.next_batch(PollLimits{SIZE_MAX, UINT64_MAX}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::SnapshotDone);
    EXPECT_EQ(result.inspections_used, 1U);
    accounting(result, replay.effective_mode(), out.size());
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 1U);
    result = replay.next_batch(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::SnapshotDone);
    EXPECT_EQ(result.inspections_used, 0U);
    EXPECT_TRUE(out.empty());
  }
}

TEST(PollBudget, V03OutputLimitWinsExactTieAndCompletionNeedsNoInspection) {
  for (const auto choice : choices) {
    Engine engine(config(64));
    const auto topic = engine.intern("itch/A/add");
    engine.publish(topic, payload(16));
    auto replay = engine.open_replay(engine.compile(exact()), Seq{0},
                                     choice.mode, choice.kernel);
    std::vector<Delivered> out;
    auto result = replay.next_batch(PollLimits{1, 1}, out);
    EXPECT_EQ(result.status, Status::More);
    EXPECT_EQ(result.stop, PollStop::OutputLimit);
    EXPECT_EQ(result.inspections_used, 1U);
    EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 32}));
    ASSERT_EQ(out.size(), 1U);
    // The consumed final item may expire: completion is known from its logical
    // boundary, and must be recognized before dereferencing recycled storage.
    for (unsigned i = 0; i < 8; ++i)
      engine.publish(topic, payload(16));
    result = replay.next_batch(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::SnapshotDone);
    EXPECT_EQ(result.inspections_used, 0U);
    EXPECT_FALSE(replay.error());
    EXPECT_TRUE(out.empty());
  }
}

TEST(PollBudget, V01V02RejectingCandidatesHaveExactIndependentProgress) {
  constexpr Seq count = 50000;
  constexpr std::uint64_t budget = 127;
  for (const auto mode : {ReplayMode::Scan, ReplayMode::Indexed}) {
    Engine engine(config(1U << 20, 256));
    const auto rejected = engine.intern("itch/A/cancel");
    const auto sub = engine.compile(exact());
    for (Seq seq = 1; seq <= count; ++seq)
      engine.publish(rejected, payload());
    auto replay = engine.open_replay(sub, Seq{0}, mode);
    ASSERT_EQ(replay.effective_mode(), mode);
    ASSERT_EQ(engine.stats().tail_pos, 0U);
    std::vector<Delivered> out;
    std::uint64_t calls = 0;
    Seq processed = 0;
    while (processed < count) {
      const auto expected = std::min<std::uint64_t>(budget, count - processed);
      const auto result = replay.next_batch(PollLimits{1, budget}, out);
      processed += expected;
      ++calls;
      ASSERT_TRUE(out.empty());
      // These independently known record boundaries catch a lying meter or
      // repeatedly restarted rejected-prefix traversal.
      ASSERT_EQ(replay.checkpoint(),
                (ResumeCheckpoint{processed, processed * 16}));
      ASSERT_EQ(result.inspections_used, expected);
      accounting(result, mode, out.size());
      ASSERT_EQ(result.status,
                processed == count ? Status::Done : Status::More);
      ASSERT_EQ(result.stop, processed == count ? PollStop::SnapshotDone
                                               : PollStop::InspectionLimit);
    }
    EXPECT_EQ(calls, (count + budget - 1) / budget);
    EXPECT_EQ(replay.work().records_fetched, count);
    EXPECT_EQ(replay.work().bytes_inspected, count * 16);
  }
}

TEST(PollBudget, V02BudgetOneReachesMatchAtEndWithoutSkippingOrRepeating) {
  for (const auto choice : choices) {
    Engine engine(config());
    const auto a = engine.intern("itch/A/add");
    const auto b = engine.intern("itch/A/cancel");
    for (unsigned i = 0; i < 99; ++i)
      engine.publish(b, payload());
    engine.publish(a, payload(5, 71));
    auto replay = engine.open_replay(engine.compile(exact()), Seq{0},
                                     choice.mode, choice.kernel);
    std::vector<Delivered> out;
    for (Seq seq = 1; seq <= 100; ++seq) {
      const auto result = replay.next_batch(PollLimits{8, 1}, out);
      EXPECT_EQ(result.inspections_used, 1U);
      EXPECT_EQ(replay.checkpoint()->after_seq, seq);
      EXPECT_EQ(replay.checkpoint()->next_pos, seq < 100 ? seq * 16 : 1608);
      accounting(result, replay.effective_mode(), out.size());
      if (seq < 100) {
        EXPECT_EQ(result.stop, PollStop::InspectionLimit);
        EXPECT_EQ(result.status, Status::More);
        ASSERT_TRUE(out.empty());
      } else {
        EXPECT_EQ(result.stop, PollStop::SnapshotDone);
        EXPECT_EQ(result.status, Status::Done);
        ASSERT_EQ(out.size(), 1U);
        EXPECT_EQ(out[0].seq, 100U);
        EXPECT_TRUE(std::ranges::equal(out[0].payload, payload(5, 71)));
      }
    }
  }
}

TEST(PollBudget, V01ScanPadConsumesOneUnitWithoutInventingSequenceProgress) {
  Engine engine(config(64));
  const auto topic = engine.intern("itch/A/add");
  const auto sub = engine.compile(exact());
  engine.publish(topic, payload(10)); // [0, 32)
  engine.publish(topic, payload(4));  // [32, 56)
  auto old = engine.open_replay(sub, Seq{1});
  std::vector<Delivered> out;
  ASSERT_EQ(old.next_batch(1, out), Status::More);
  ASSERT_EQ(old.checkpoint(), (ResumeCheckpoint{2, 56}));
  engine.publish(topic, payload(8)); // PAD [56, 64), DATA [64, 88)
  auto replay = engine.open_replay(sub, *old.checkpoint());
  auto result = replay.next_batch(PollLimits{8, 1}, out);
  EXPECT_EQ(result.status, Status::More);
  EXPECT_EQ(result.stop, PollStop::InspectionLimit);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(result.inspections_used, 1U);
  EXPECT_EQ(result.work_delta.pads_inspected, 1U);
  EXPECT_EQ(result.work_delta.records_fetched, 0U);
  EXPECT_EQ(result.work_delta.bytes_inspected, 8U);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{2, 64}));
  result = replay.next_batch(PollLimits{8, 1}, out);
  EXPECT_EQ(result.status, Status::Done);
  EXPECT_EQ(result.stop, PollStop::SnapshotDone);
  EXPECT_EQ(result.inspections_used, 1U);
  ASSERT_EQ(out.size(), 1U);
  EXPECT_EQ(out[0].seq, 3U);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{3, 88}));
}

TEST(PollBudget, V04TailSharesInspectionAndOutputBudgetsAcrossRanges) {
  for (const auto choice : choices) {
    Engine engine(config());
    const auto a = engine.intern("itch/A/add");
    const auto b = engine.intern("itch/A/cancel");
    const auto sub = engine.compile(exact());
    engine.publish(b, payload());
    engine.publish(a, payload());
    auto tail = engine.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    auto output_limited_tail =
        engine.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    engine.publish(b, payload());
    engine.publish(a, payload());
    std::vector<Delivered> out;
    auto result = tail.poll(PollLimits{8, 3}, out);
    EXPECT_EQ(result.status, Status::More);
    EXPECT_EQ(result.stop, PollStop::InspectionLimit);
    EXPECT_EQ(result.inspections_used, 3U);
    EXPECT_EQ(result.work_delta.records_fetched, 3U);
    EXPECT_EQ(result.work_delta.bytes_inspected, 48U);
    // New captured-range construction seeks DATA 1, 2, 3 independently of
    // candidate accounting. Old + new Indexed preparation each seek one list.
    EXPECT_EQ(result.work_delta.seek_data_examined, 3U);
    EXPECT_EQ(result.work_delta.seek_pads_examined, 0U);
    EXPECT_EQ(result.work_delta.index_seeks,
              tail.effective_mode() == ReplayMode::Indexed ? 2U : 0U);
    accounting(result, tail.effective_mode(), out.size());
    EXPECT_EQ(tail.checkpoint(), (ResumeCheckpoint{3, 48}));
    EXPECT_EQ(tail.upper_seq(), 4U);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
    result = tail.poll(PollLimits{1, 1}, out);
    EXPECT_EQ(result.status, Status::More);
    EXPECT_EQ(result.stop, PollStop::OutputLimit);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 4U);
    result = tail.poll(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::CaughtUp);
    EXPECT_EQ(result.inspections_used, 0U);
    result = output_limited_tail.poll(PollLimits{2, 4}, out);
    EXPECT_EQ(result.status, Status::More);
    EXPECT_EQ(result.stop, PollStop::OutputLimit);
    EXPECT_EQ(result.inspections_used, 4U);
    EXPECT_EQ(result.work_delta.seek_data_examined, 3U);
    ASSERT_EQ(out.size(), 2U);
    EXPECT_EQ(out[0].seq, 2U);
    EXPECT_EQ(out[1].seq, 4U);
    EXPECT_EQ(output_limited_tail.checkpoint(), (ResumeCheckpoint{4, 64}));
  }
}

TEST(PollBudget, V04TailExactOldCompletionDefersFreshOpeningWhenExhausted) {
  for (const auto choice : choices) {
    Engine engine(config());
    const auto b = engine.intern("itch/A/cancel");
    const auto a = engine.intern("itch/A/add");
    const auto sub = engine.compile(exact());
    engine.publish(b, payload());
    auto tail = engine.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    engine.publish(a, payload());
    std::vector<Delivered> out;
    auto result = tail.poll(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::More);
    EXPECT_EQ(result.stop, PollStop::InspectionLimit);
    EXPECT_EQ(result.inspections_used, 1U);
    EXPECT_TRUE(out.empty());
    EXPECT_EQ(result.work_delta.seek_data_examined, 0U);
    EXPECT_EQ(tail.upper_seq(), 1U);
    EXPECT_EQ(tail.checkpoint(), (ResumeCheckpoint{1, 16}));
    result = tail.poll(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::CaughtUp);
    EXPECT_EQ(result.inspections_used, 1U);
    EXPECT_EQ(result.work_delta.seek_data_examined, 2U);
    EXPECT_EQ(tail.upper_seq(), 2U);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
  }
}

TEST(PollBudget, V04TailExactFinalRejectionReportsCaughtUpAndCanObserveLaterData) {
  for (const auto choice : choices) {
    Engine engine(config());
    const auto b = engine.intern("itch/A/cancel");
    const auto sub = engine.compile(exact());
    engine.publish(b, payload());
    auto tail = engine.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> out;
    auto result = tail.poll(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::CaughtUp);
    EXPECT_EQ(result.inspections_used, 1U);
    EXPECT_TRUE(out.empty());
    for (unsigned repeat = 0; repeat < 3; ++repeat) {
      result = tail.poll(PollLimits{8, 1}, out);
      EXPECT_EQ(result.stop, PollStop::CaughtUp);
      EXPECT_EQ(result.status, Status::Done);
      EXPECT_EQ(result.work_delta, ReplayWork{});
    }
    engine.publish(engine.intern("itch/A/add"), payload());
    result = tail.poll(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::CaughtUp);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
  }
}

TEST(PollBudget, V05IndependentCandidateTraceAndPayloadOracleAllModesAndKernels) {
  const std::array<SubscriptionSpec, 5> specs{{
      exact(),
      {{{Term::Subtree, "itch/A/add"}, {Term::Exact, "itch/A/add"},
        {Term::Subtree, "itch/B"}, {Term::Exact, "itch/C/cancel"}}},
      {{{Term::Subtree, "itch"}}},
      exact("itch/unpublished/add"),
      {{{Term::Exact, "itch/A/add"}, {Term::Exact, "itch/B/add"},
        {Term::Exact, "itch/C/add"}, {Term::Exact, "itch/D/add"}}}}};
  for (const auto choice : choices) {
    for (std::size_t spec_index = 0; spec_index < specs.size(); ++spec_index) {
      SCOPED_TRACE(::testing::Message()
                   << static_cast<unsigned>(choice.mode) << ':'
                   << static_cast<unsigned>(choice.kernel) << ':' << spec_index);
      Engine engine(config(1U << 16));
      ref::ScanOracle oracle({1U << 16, 1U << 15});
      const auto &subscription = specs[spec_index];
      const auto sub = engine.compile(subscription);
      constexpr std::array<std::string_view, 7> names{
          "itch/A/add", "itch/A/add/anon", "itch/A/cancel", "itch/B/add",
          "itch/B/delete", "itch/C/cancel", "itch/D/other"};
      for (unsigned i = 0; i < 301; ++i) {
        const auto name = names[(i * 17 + i / 9) % names.size()];
        const auto data = payload(i % 37, i);
        EXPECT_EQ(engine.publish(engine.intern(name), data),
                  oracle.publish(name, data));
      }
      auto replay = engine.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
      std::vector<const ref::OracleRecord *> candidates;
      std::vector<std::string> selected;
      for (const auto &term : subscription.terms)
        selected.push_back(partition(term.path));
      for (const auto &record : oracle.full_records()) {
        if (replay.effective_mode() == ReplayMode::Scan ||
            std::ranges::find(selected, partition(record.path)) != selected.end())
          candidates.push_back(&record);
      }
      std::mt19937 random(0xF01U + static_cast<unsigned>(spec_index));
      std::size_t next = 0;
      std::vector<Seq> delivered;
      std::vector<Delivered> out;
      for (unsigned call = 0; call < 2000 && replay.status() == Status::More;
           ++call) {
        const std::size_t max_outputs = 1 + random() % 8;
        const std::uint64_t cap = 1 + random() % 19;
        std::vector<const ref::OracleRecord *> expected;
        std::uint64_t used = 0;
        while (next < candidates.size() && used < cap &&
               expected.size() < max_outputs) {
          const auto *record = candidates[next++];
          ++used;
          if (ref::ScanOracle::matches(subscription, record->path))
            expected.push_back(record);
        }
        const auto result = replay.next_batch(PollLimits{max_outputs, cap}, out);
        ASSERT_EQ(result.inspections_used, used);
        ASSERT_LE(result.inspections_used, cap);
        ASSERT_EQ(out.size(), expected.size());
        accounting(result, replay.effective_mode(), out.size());
        const auto expected_stop = expected.size() == max_outputs
                                       ? PollStop::OutputLimit
                                   : next == candidates.size()
                                       ? PollStop::SnapshotDone
                                       : PollStop::InspectionLimit;
        ASSERT_EQ(result.stop, expected_stop);
        ASSERT_EQ(result.status, expected_stop == PollStop::SnapshotDone
                                     ? Status::Done : Status::More);
        for (std::size_t i = 0; i < out.size(); ++i) {
          EXPECT_EQ(out[i].seq, expected[i]->seq);
          EXPECT_EQ(out[i].pos, expected[i]->pos);
          EXPECT_EQ(engine.registry().get(out[i].topic).path, expected[i]->path);
          EXPECT_TRUE(std::ranges::equal(out[i].payload, expected[i]->payload));
          delivered.push_back(out[i].seq);
        }
        if (result.status == Status::Done) {
          EXPECT_EQ(replay.checkpoint(),
                    (ResumeCheckpoint{301, oracle.head_pos()}));
        } else if (next != 0) {
          const auto &last = *candidates[next - 1];
          EXPECT_EQ(replay.checkpoint(),
                    (ResumeCheckpoint{last.seq, last.pos + last.size}));
        }
      }
      ASSERT_EQ(replay.status(), Status::Done);
      auto reference = oracle.open_replay(subscription, 0);
      std::vector<ref::OracleRecord> expected_all;
      ASSERT_EQ(reference.next_batch(SIZE_MAX, expected_all), Status::Done);
      ASSERT_EQ(delivered.size(), expected_all.size());
      for (std::size_t i = 0; i < delivered.size(); ++i)
        EXPECT_EQ(delivered[i], expected_all[i].seq);
      EXPECT_EQ(replay.checkpoint(), reference.checkpoint());
    }
  }
}

TEST(PollBudget, V06RejectingProgressDoesNotFalsifyLastDeliveredOnExpiry) {
  for (const auto choice : choices) {
    Engine engine(config(128));
    const auto a = engine.intern("itch/A/add");
    const auto b = engine.intern("itch/A/cancel");
    engine.publish(a, payload());
    engine.publish(b, payload());
    engine.publish(b, payload());
    engine.publish(a, payload());
    auto replay = engine.open_replay(engine.compile(exact()), Seq{0},
                                     choice.mode, choice.kernel);
    std::vector<Delivered> out;
    ASSERT_EQ(replay.next_batch(PollLimits{1, 1}, out).stop,
              PollStop::OutputLimit);
    ASSERT_EQ(out[0].seq, 1U);
    ASSERT_EQ(replay.next_batch(PollLimits{8, 2}, out).stop,
              PollStop::InspectionLimit);
    EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{3, 48}));
    for (unsigned i = 0; i < 16; ++i)
      engine.publish(b, payload());
    const auto checkpoint = replay.checkpoint();
    no_work(replay.next_batch(PollLimits{8, 0}, out), Status::More);
    EXPECT_EQ(replay.checkpoint(), checkpoint);
    const auto result = replay.next_batch(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Error);
    EXPECT_EQ(result.stop, PollStop::Error);
    EXPECT_EQ(result.inspections_used, 0U);
    EXPECT_TRUE(out.empty());
    EXPECT_EQ(replay.error(), (ReplayError{ReplayError::FellBehind, 0, 1,
                                          engine.stats().tail_seq}));
    const auto error = replay.error();
    no_work(replay.next_batch(PollLimits{0, 1}, out), Status::Error);
    EXPECT_EQ(replay.error(), error);
    EXPECT_EQ(replay.next_batch(PollLimits{8, 1}, out).stop, PollStop::Error);
  }
}

TEST(PollBudget, V06ConsumedRecycledBlockCanReseekAndUnreadRecycledBlockExpires) {
  for (const auto kernel : {MergeKernel::StdPQ, MergeKernel::BinHeap,
                            MergeKernel::Quad, MergeKernel::Loser}) {
    Engine engine(config(64, 1));
    const auto a = engine.intern("itch/A/add");
    const auto sub = engine.compile(exact());
    engine.publish(a, payload(16));
    engine.publish(a, payload(16));
    auto consumed = engine.open_replay(sub, Seq{0}, ReplayMode::Indexed, kernel);
    auto unread = engine.open_replay(sub, Seq{0}, ReplayMode::Indexed, kernel);
    std::vector<Delivered> out;
    ASSERT_EQ(consumed.next_batch(PollLimits{8, 1}, out).stop,
              PollStop::InspectionLimit);
    ASSERT_EQ(out.size(), 1U);
    engine.publish(a, payload(16));
    ASSERT_EQ(engine.stats().tail_pos, 32U);
    auto result = consumed.next_batch(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::SnapshotDone);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
    result = unread.next_batch(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Error);
    EXPECT_EQ(result.stop, PollStop::Error);
    EXPECT_EQ(result.inspections_used, 0U);
    EXPECT_TRUE(out.empty());
    engine.check_invariants();
  }
}

TEST(PollBudget, V06RegistryGrowthAndMovesKeepLogicalProgress) {
  for (const auto choice : choices) {
    Engine engine(config());
    const auto sub = engine.compile({{{Term::Subtree, "itch/A/add"}}});
    const auto a = engine.intern("itch/A/add/old");
    engine.publish(a, payload(5, 1));
    engine.publish(a, payload(7, 2));
    auto original = engine.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> out;
    ASSERT_EQ(original.next_batch(PollLimits{8, 1}, out).status, Status::More);
    for (unsigned i = 0; i < 200; ++i)
      static_cast<void>(engine.intern("itch/A/add/new" + std::to_string(i)));
    auto moved = std::move(original);
    EXPECT_THROW(original.next_batch(PollLimits{0, 0}, out), std::logic_error);
    EXPECT_THROW(original.next_batch(PollLimits{0, std::nullopt}, out),
                 std::logic_error);
    auto assigned = engine.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    assigned = std::move(moved);
    EXPECT_THROW(moved.next_batch(PollLimits{8, 0}, out), std::logic_error);
    const auto result = assigned.next_batch(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Done);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
    EXPECT_TRUE(std::ranges::equal(out[0].payload, payload(7, 2)));
    auto tail = engine.open_tail(sub, Seq{2}, choice.mode, choice.kernel);
    auto moved_tail = std::move(tail);
    EXPECT_THROW(tail.poll(PollLimits{0, 0}, out), std::logic_error);
    engine.publish(a, payload(9, 3));
    EXPECT_EQ(moved_tail.poll(PollLimits{8, 1}, out).stop, PollStop::CaughtUp);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 3U);
  }
}

TEST(PollBudget, V06OutlivedZeroWorkReaderStillChecksLifetime) {
#ifndef NDEBUG
  EXPECT_DEATH(
      {
        auto engine = std::make_unique<Engine>(config());
        auto reader = engine->open_replay(engine->compile(exact()), Seq{0});
        engine.reset();
      },
      "Replay must be closed");
#else
  std::optional<Replay> replay;
  std::optional<Tail> tail;
  {
    auto engine = std::make_unique<Engine>(config());
    const auto sub = engine->compile(exact());
    replay.emplace(engine->open_replay(sub, Seq{0}));
    tail.emplace(engine->open_tail(sub, Seq{0}));
  }
  std::vector<Delivered> out;
  EXPECT_THROW(replay->next_batch(PollLimits{0, 0}, out), std::logic_error);
  EXPECT_THROW(tail->poll(PollLimits{0, 0}, out), std::logic_error);
#endif
}

TEST(PollBudget, V07FailedAppendPreservesUnreadMatchAndLegacyCheckpoint) {
  for (const auto mode : {ReplayMode::Scan, ReplayMode::Indexed}) {
    for (const unsigned form : {0U, 1U, 2U}) {
      SCOPED_TRACE(::testing::Message() << static_cast<unsigned>(mode) << ':' << form);
      Engine engine(config());
      const auto a = engine.intern("itch/A/add");
      const auto b = engine.intern("itch/A/cancel");
      engine.publish(b, payload());
      engine.publish(b, payload());
      engine.publish(a, payload(3, 51));
      auto replay = engine.open_replay(engine.compile(exact()), Seq{0}, mode);
      std::vector<Delivered> out;
      fail_output_append = true;
      try {
        if (form == 0)
          static_cast<void>(replay.next_batch(8, out));
        else
          static_cast<void>(replay.next_batch(
              PollLimits{8, form == 1 ? std::nullopt
                                      : std::optional<std::uint64_t>{3}}, out));
        fail_output_append = false;
        FAIL() << "output allocation failure was not reached";
      } catch (const std::bad_alloc &) {
        EXPECT_FALSE(fail_output_append);
      }
      fail_output_append = false;
      EXPECT_TRUE(out.empty());
      EXPECT_EQ(replay.status(), Status::More);
      // Scan already committed its rejecting prefix. Indexed preserves the
      // historical checkpoint for legacy/nullopt, but finite progress commits.
      const Seq expected_after = mode == ReplayMode::Scan || form == 2 ? 2 : 0;
      EXPECT_EQ(replay.checkpoint(),
                (ResumeCheckpoint{expected_after, expected_after * 16}));
      const auto result = replay.next_batch(PollLimits{8, 3}, out);
      EXPECT_EQ(result.status, Status::Done);
      EXPECT_EQ(result.stop, PollStop::SnapshotDone);
      ASSERT_EQ(out.size(), 1U);
      EXPECT_EQ(out[0].seq, 3U);
      EXPECT_TRUE(std::ranges::equal(out[0].payload, payload(3, 51)));
      EXPECT_EQ(replay.next_batch(PollLimits{8, 1}, out).status, Status::Done);
      EXPECT_TRUE(out.empty());
    }
  }
}

TEST(PollBudget, V08NulloptMatchesLegacyAtEveryVisibleBoundary) {
  for (const auto choice : choices) {
    Engine engine(config());
    const auto a = engine.intern("itch/A/add");
    const auto b = engine.intern("itch/A/cancel");
    const auto sub = engine.compile(exact());
    for (unsigned i = 0; i < 47; ++i)
      engine.publish(i % 5 == 0 ? a : b, payload(i % 17, i));
    auto legacy = engine.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    auto unlimited = engine.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> first, second;
    for (unsigned call = 0; call < 30; ++call) {
      const std::size_t output_cap = call % 4;
      const auto expected = legacy.next_batch(output_cap, first);
      const auto result = unlimited.next_batch(PollLimits{output_cap, std::nullopt}, second);
      EXPECT_EQ(result.status, expected);
      EXPECT_EQ(legacy.status(), unlimited.status());
      EXPECT_EQ(legacy.checkpoint(), unlimited.checkpoint());
      EXPECT_EQ(legacy.error(), unlimited.error());
      EXPECT_EQ(legacy.work(), unlimited.work());
      ASSERT_EQ(first.size(), second.size());
      for (std::size_t i = 0; i < first.size(); ++i) {
        EXPECT_EQ(first[i].seq, second[i].seq);
        EXPECT_EQ(first[i].pos, second[i].pos);
        EXPECT_EQ(first[i].topic, second[i].topic);
        EXPECT_TRUE(std::ranges::equal(first[i].payload, second[i].payload));
      }
    }
  }
}

TEST(PollBudget, V05ContinuingSnapshotAndReopeningCheckpointHaveDifferentUpperBounds) {
  for (const auto choice : choices) {
    Engine engine(config());
    const auto a = engine.intern("itch/A/add");
    const auto b = engine.intern("itch/A/cancel");
    const auto sub = engine.compile(exact());
    engine.publish(b, payload());
    engine.publish(a, payload());
    auto original = engine.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> out;
    ASSERT_EQ(original.next_batch(PollLimits{8, 1}, out).stop,
              PollStop::InspectionLimit);
    const auto checkpoint = *original.checkpoint();
    engine.publish(a, payload());
    auto reopened = engine.open_replay(sub, checkpoint, choice.mode, choice.kernel);
    EXPECT_EQ(original.upper_seq(), 2U);
    EXPECT_EQ(reopened.upper_seq(), 3U);
    EXPECT_EQ(original.next_batch(PollLimits{8, 8}, out).status, Status::Done);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
    EXPECT_EQ(reopened.next_batch(PollLimits{8, 8}, out).status, Status::Done);
    ASSERT_EQ(out.size(), 2U);
    EXPECT_EQ(out[0].seq, 2U);
    EXPECT_EQ(out[1].seq, 3U);
  }
}

TEST(PollBudget, V04TailRejectingProgressKeepsGlobalErrorPrefixAndLatchedErrors) {
  for (const auto choice : choices) {
    Engine engine(config(128));
    const auto a = engine.intern("itch/A/add");
    const auto b = engine.intern("itch/A/cancel");
    const auto sub = engine.compile(exact());
    engine.publish(a, payload());
    engine.publish(b, payload());
    engine.publish(b, payload());
    engine.publish(a, payload());
    auto tail = engine.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> out;
    ASSERT_EQ(tail.poll(PollLimits{1, 1}, out).stop, PollStop::OutputLimit);
    ASSERT_EQ(out[0].seq, 1U);
    ASSERT_EQ(tail.poll(PollLimits{8, 2}, out).stop, PollStop::InspectionLimit);
    ASSERT_EQ(tail.checkpoint(), (ResumeCheckpoint{3, 48}));
    for (unsigned i = 0; i < 16; ++i)
      engine.publish(b, payload());
    no_work(tail.poll(PollLimits{8, 0}, out), Status::More);
    const auto result = tail.poll(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Error);
    EXPECT_EQ(result.stop, PollStop::Error);
    EXPECT_EQ(result.inspections_used, 0U);
    EXPECT_EQ(tail.error(), (ReplayError{ReplayError::FellBehind, 0, 1,
                                        engine.stats().tail_seq}));
    const auto error = tail.error();
    no_work(tail.poll(PollLimits{0, 0}, out), Status::Error);
    engine.publish(a, payload());
    EXPECT_EQ(tail.poll(PollLimits{8, 1}, out).stop, PollStop::Error);
    EXPECT_EQ(tail.error(), error);
    EXPECT_TRUE(out.empty());
  }
}

TEST(PollBudget, V06PoolPressureExpiresUnreadRangeBeforeRecycledMetadataAccess) {
  auto c = config(128, 1);
  c.index.blocks = 1;
  for (const auto kernel : {MergeKernel::StdPQ, MergeKernel::BinHeap,
                            MergeKernel::Quad, MergeKernel::Loser}) {
    Engine engine(c);
    const auto a = engine.intern("itch/A/add");
    const auto b = engine.intern("itch/B/add");
    const auto sub = engine.compile(exact());
    engine.publish(a, payload());
    auto unread = engine.open_replay(sub, Seq{0}, ReplayMode::Indexed, kernel);
    auto completed = engine.open_replay(sub, Seq{0}, ReplayMode::Indexed, kernel);
    std::vector<Delivered> out;
    ASSERT_EQ(completed.next_batch(PollLimits{8, 1}, out).status, Status::Done);
    const auto generation = engine.index()->metadata()[0].gen;
    engine.publish(b, payload());
    ASSERT_EQ(engine.stats().tail_pos, 16U);
    ASSERT_GT(engine.index()->metadata()[0].gen, generation);
    ASSERT_GT(engine.ring().stats().pressure_data_evicted, 0U);
    EXPECT_EQ(unread.next_batch(PollLimits{8, 1}, out).stop, PollStop::Error);
    EXPECT_EQ(unread.error(), (ReplayError{ReplayError::FellBehind, 0, 0, 2}));
    const auto result = completed.next_batch(PollLimits{8, 1}, out);
    EXPECT_EQ(result.status, Status::Done);
    EXPECT_EQ(result.stop, PollStop::SnapshotDone);
    EXPECT_EQ(result.work_delta, ReplayWork{});
    EXPECT_FALSE(completed.error());
  }
}

TEST(PollBudget, V07FailedSecondAppendKeepsDeliveredPrefixAndUnreadMatch) {
  for (const auto choice : choices) {
    for (const bool finite : {false, true}) {
      Engine engine(config());
      const auto a = engine.intern("itch/A/add");
      const auto b = engine.intern("itch/A/cancel");
      engine.publish(a, payload(1, 1));
      engine.publish(b, payload(2, 2));
      engine.publish(a, payload(3, 3));
      auto replay = engine.open_replay(engine.compile(exact()), Seq{0},
                                       choice.mode, choice.kernel);
      std::vector<Delivered> out;
      out.reserve(1);
      failed_allocation_size = 2 * sizeof(Delivered);
      fail_output_append = true;
      try {
        static_cast<void>(replay.next_batch(
            PollLimits{8, finite ? std::optional<std::uint64_t>{3}
                                  : std::nullopt}, out));
        fail_output_append = false;
        failed_allocation_size = sizeof(Delivered);
        FAIL() << "second output allocation failure was not reached";
      } catch (const std::bad_alloc &) {
        EXPECT_FALSE(fail_output_append);
      }
      fail_output_append = false;
      failed_allocation_size = sizeof(Delivered);
      ASSERT_EQ(out.size(), 1U);
      EXPECT_EQ(out[0].seq, 1U);
      EXPECT_EQ(replay.work().records_fetched, 3U);
      EXPECT_EQ(replay.work().delivered, 1U);
      const Seq expected_after =
          finite || replay.effective_mode() == ReplayMode::Scan ? 2 : 1;
      EXPECT_EQ(replay.checkpoint(),
                (ResumeCheckpoint{expected_after, expected_after * 24}));
      const auto result = replay.next_batch(PollLimits{8, 3}, out);
      EXPECT_EQ(result.status, Status::Done);
      ASSERT_EQ(out.size(), 1U);
      EXPECT_EQ(out[0].seq, 3U);
      EXPECT_TRUE(std::ranges::equal(out[0].payload, payload(3, 3)));
      EXPECT_EQ(replay.work().delivered, 2U);
    }
  }
}

TEST(PollBudget, V08UnlimitedTailMatchesLegacyAcrossCaptureAndOutputBoundaries) {
  for (const auto choice : choices) {
    Engine engine(config());
    const auto a = engine.intern("itch/A/add");
    const auto b = engine.intern("itch/A/cancel");
    const auto sub = engine.compile(exact());
    auto legacy = engine.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    auto unlimited = engine.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> first, second;
    for (unsigned call = 0; call < 40; ++call) {
      engine.publish(call % 3 == 0 ? a : b, payload(call % 9, call));
      const std::size_t max_outputs = call % 3;
      const auto expected = legacy.poll(max_outputs, first);
      const auto result = unlimited.poll(PollLimits{max_outputs, std::nullopt}, second);
      EXPECT_EQ(result.status, expected);
      EXPECT_EQ(legacy.status(), unlimited.status());
      EXPECT_EQ(legacy.checkpoint(), unlimited.checkpoint());
      EXPECT_EQ(legacy.upper_seq(), unlimited.upper_seq());
      EXPECT_EQ(legacy.upper_pos(), unlimited.upper_pos());
      EXPECT_EQ(legacy.error(), unlimited.error());
      EXPECT_EQ(result.work_delta.delivered, second.size());
      ASSERT_EQ(first.size(), second.size());
      for (std::size_t i = 0; i < first.size(); ++i) {
        EXPECT_EQ(first[i].seq, second[i].seq);
        EXPECT_EQ(first[i].pos, second[i].pos);
        EXPECT_TRUE(std::ranges::equal(first[i].payload, second[i].payload));
      }
    }
  }
}

TEST(PollBudget, V05AutoFallbackUsesScanAccountingAndWideTailCapturesNewPartitions) {
  auto c = config();
  c.auto_max_partitions = 1;
  Engine engine(c);
  const auto sub = engine.compile({{{Term::Exact, "itch/A/add"},
                                    {Term::Exact, "itch/B/add"}}});
  engine.publish(engine.intern("itch/C/add"), payload());
  engine.publish(engine.intern("itch/A/add"), payload());
  auto replay = engine.open_replay(sub, Seq{0}, ReplayMode::Auto);
  ASSERT_EQ(replay.effective_mode(), ReplayMode::Scan);
  std::vector<Delivered> out;
  auto result = replay.next_batch(PollLimits{8, 1}, out);
  EXPECT_EQ(result.stop, PollStop::InspectionLimit);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 16}));
  accounting(result, ReplayMode::Scan, 0);
  const auto wide = engine.compile({{{Term::Subtree, "itch"}}});
  auto tail = engine.open_tail(wide, Seq{2}, ReplayMode::Auto);
  engine.publish(engine.intern("itch/new_partition/add"), payload(7, 99));
  result = tail.poll(PollLimits{8, 1}, out);
  EXPECT_EQ(tail.effective_mode(), ReplayMode::Scan);
  EXPECT_EQ(result.status, Status::Done);
  EXPECT_EQ(result.stop, PollStop::CaughtUp);
  ASSERT_EQ(out.size(), 1U);
  EXPECT_EQ(out[0].seq, 3U);
  EXPECT_TRUE(std::ranges::equal(out[0].payload, payload(7, 99)));
  accounting(result, ReplayMode::Scan, out.size());
}

TEST(PollBudget, V07TailPartialAppendKeepsLegacyCacheAndRetriesUnreadMatch) {
  for (const auto choice : choices) {
    for (const unsigned form : {0U, 1U, 2U}) {
      SCOPED_TRACE(::testing::Message()
                   << static_cast<unsigned>(choice.mode) << ':'
                   << static_cast<unsigned>(choice.kernel) << ':' << form);
      Engine engine(config());
      const auto a = engine.intern("itch/A/add");
      const auto b = engine.intern("itch/A/cancel");
      engine.publish(a, payload(1, 1));
      engine.publish(b, payload(2, 2));
      engine.publish(a, payload(3, 3));
      auto tail = engine.open_tail(engine.compile(exact()), Seq{0},
                                   choice.mode, choice.kernel);
      const auto before = tail.checkpoint();
      std::vector<Delivered> out;
      out.reserve(1);
      failed_allocation_size = 2 * sizeof(Delivered);
      fail_output_append = true;
      try {
        if (form == 0)
          static_cast<void>(tail.poll(8, out));
        else
          static_cast<void>(tail.poll(
              PollLimits{8, form == 1 ? std::nullopt
                                      : std::optional<std::uint64_t>{3}}, out));
        fail_output_append = false;
        failed_allocation_size = sizeof(Delivered);
        FAIL() << "second output allocation failure was not reached";
      } catch (const std::bad_alloc &) {
        EXPECT_FALSE(fail_output_append);
      }
      fail_output_append = false;
      failed_allocation_size = sizeof(Delivered);
      ASSERT_EQ(out.size(), 1U);
      EXPECT_EQ(out[0].seq, 1U);
      EXPECT_TRUE(std::ranges::equal(out[0].payload, payload(1, 1)));
      // Tail inherits the pre-existing cache behavior on exceptions: the
      // public cache describes its last completed poll, while internal Replay
      // retains its successfully processed prefix. No PollResult was returned.
      EXPECT_EQ(tail.status(), Status::More);
      EXPECT_EQ(tail.checkpoint(), before);
      EXPECT_FALSE(tail.error());
      no_work(tail.poll(PollLimits{8, 0}, out), Status::More);
      EXPECT_EQ(tail.checkpoint(), before);
      EXPECT_TRUE(out.empty());
      // Retry returns only the previously unread matching record. Legacy and
      // nullopt Indexed retry the intervening rejection; finite calls committed
      // it. This checks actual fetches as well as final ordered output.
      const auto result = tail.poll(PollLimits{8, 3}, out);
      EXPECT_EQ(result.status, Status::Done);
      EXPECT_EQ(result.stop, PollStop::CaughtUp);
      const std::uint64_t expected_fetches =
          form != 2 && tail.effective_mode() == ReplayMode::Indexed ? 2 : 1;
      EXPECT_EQ(result.inspections_used, expected_fetches);
      EXPECT_EQ(result.work_delta.records_fetched, expected_fetches);
      EXPECT_EQ(tail.checkpoint(), (ResumeCheckpoint{3, 72}));
      ASSERT_EQ(out.size(), 1U);
      EXPECT_EQ(out[0].seq, 3U);
      EXPECT_TRUE(std::ranges::equal(out[0].payload, payload(3, 3)));
      engine.publish(a, payload(4, 4));
      EXPECT_EQ(tail.poll(PollLimits{8, 1}, out).stop, PollStop::CaughtUp);
      ASSERT_EQ(out.size(), 1U);
      EXPECT_EQ(out[0].seq, 4U);
    }
  }
}

TEST(PollBudget, TailExpiryAfterFailedAppendReportsActuallyDeliveredPrefix) {
  for (const auto choice : choices) {
    for (const unsigned form : {0U, 1U, 2U}) {
      for (const bool partial : {false, true}) {
        SCOPED_TRACE(::testing::Message()
                     << static_cast<unsigned>(choice.mode) << ':'
                     << static_cast<unsigned>(choice.kernel) << ':' << form
                     << ':' << partial);
        Engine engine(config(128));
        const auto a = engine.intern("itch/A/add");
        engine.publish(a, payload());
        engine.publish(a, payload());
        auto tail = engine.open_tail(engine.compile(exact()), Seq{0},
                                     choice.mode, choice.kernel);
        const auto original_checkpoint = tail.checkpoint();
        std::vector<Delivered> out;
        if (partial)
          out.reserve(1);
        failed_allocation_size = (partial ? 2 : 1) * sizeof(Delivered);
        fail_output_append = true;
        try {
          if (form == 0)
            static_cast<void>(tail.poll(8, out));
          else
            static_cast<void>(tail.poll(
                PollLimits{8, form == 1 ? std::nullopt
                                        : std::optional<std::uint64_t>{8}}, out));
          fail_output_append = false;
          failed_allocation_size = sizeof(Delivered);
          FAIL() << "output allocation failure was not reached";
        } catch (const std::bad_alloc &) {
          EXPECT_FALSE(fail_output_append);
        }
        fail_output_append = false;
        failed_allocation_size = sizeof(Delivered);
        ASSERT_EQ(out.size(), partial ? 1U : 0U);
        const Seq actual_last_delivered = partial ? out.back().seq : 0;
        EXPECT_EQ(actual_last_delivered, partial ? 1U : 0U);
        // Preserve the public exception cache while accounting internally for
        // every output already handed to the caller in the throwing poll.
        EXPECT_EQ(tail.checkpoint(), original_checkpoint);
        EXPECT_EQ(tail.status(), Status::More);
        EXPECT_FALSE(tail.error());
        for (unsigned i = 0; i < 16; ++i)
          engine.publish(a, payload());
        no_work(tail.poll(PollLimits{8, 0}, out), Status::More);
        EXPECT_EQ(tail.checkpoint(), original_checkpoint);
        const auto result = tail.poll(PollLimits{8, 8}, out);
        EXPECT_EQ(result.status, Status::Error);
        EXPECT_EQ(result.stop, PollStop::Error);
        EXPECT_EQ(result.inspections_used, 0U);
        EXPECT_EQ(result.work_delta, ReplayWork{});
        EXPECT_TRUE(out.empty());
        const auto expected_error = ReplayError{
            ReplayError::FellBehind, 0, actual_last_delivered,
            engine.stats().tail_seq};
        EXPECT_EQ(tail.error(), expected_error);
        no_work(tail.poll(PollLimits{0, 0}, out), Status::Error);
        EXPECT_EQ(tail.poll(8, out), Status::Error);
        EXPECT_EQ(tail.error(), expected_error);
      }
    }
  }
}
} // namespace
} // namespace tiplog
