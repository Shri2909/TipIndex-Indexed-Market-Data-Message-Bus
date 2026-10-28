#include "scan_oracle.hpp"
#include "tiplog/engine/engine.hpp"

#include <algorithm>
#include <array>
#include <gtest/gtest.h>
#include <limits>
#include <optional>

namespace tiplog {
namespace {
EngineConfig config(std::size_t capacity = 256, std::uint32_t blocks = 32,
                    std::uint32_t entries = 2) {
  EngineConfig c;
  c.ring_bytes = capacity;
  c.max_record_bytes = capacity / 2;
  c.index.blocks = blocks;
  c.index.entries_per_block = entries;
  c.index.sweep_evictions = 3;
  return c;
}
SubscriptionSpec exact(std::string path) {
  return {{{Term::Exact, std::move(path)}}};
}
SubscriptionSpec subtree(std::string path) {
  return {{{Term::Subtree, std::move(path)}}};
}
std::vector<std::byte> bytes(std::size_t size, unsigned char value = 7) {
  return std::vector<std::byte>(size, static_cast<std::byte>(value));
}
struct Membership {
  EngineStats stats;
  ring::RingStats ring_stats;
  std::vector<std::byte> storage;
  std::vector<index::Posting> entries;
  std::vector<index::BlockMeta> metadata;
  index::Gauges gauges;
};
Membership snapshot(const Engine &e) {
  const auto storage = e.ring().storage_bytes();
  return {e.stats(), e.ring().stats(), {storage.begin(), storage.end()},
          e.index()->entries(), e.index()->metadata(), e.index()->stats().gauges};
}
void unchanged(const Engine &e, const Membership &s) {
  const auto now = snapshot(e);
  EXPECT_EQ(now.stats.head_pos, s.stats.head_pos);
  EXPECT_EQ(now.stats.tail_pos, s.stats.tail_pos);
  EXPECT_EQ(now.stats.head_seq, s.stats.head_seq);
  EXPECT_EQ(now.stats.tail_seq, s.stats.tail_seq);
  EXPECT_EQ(now.ring_stats, s.ring_stats);
  EXPECT_EQ(now.storage, s.storage);
  EXPECT_EQ(now.entries, s.entries);
  EXPECT_EQ(now.metadata, s.metadata);
  EXPECT_EQ(now.gauges, s.gauges);
  e.check_invariants();
}
TEST(EngineIndex, V18RecycledBlockCannotServeUnreadCursor) {
  for (const std::uint32_t block_entries : {1U, 2U}) {
    Engine e(config(128, 1, block_entries));
    const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
    const auto sub = e.compile(subtree("itch/A"));
    for (std::uint32_t i = 0; i < block_entries; ++i)
      e.publish(a, bytes(16));
    auto replay = e.open_replay(sub, Seq{0}, ReplayMode::Indexed);
    const auto generation = e.index()->metadata()[0].gen;
    e.publish(b, bytes(16));
    ASSERT_GT(e.index()->metadata()[0].gen, generation);
    const auto before = replay.checkpoint();
    std::vector<Delivered> out;
    EXPECT_EQ(replay.next_batch(0, out), Status::More);
    EXPECT_EQ(replay.checkpoint(), before);
    EXPECT_EQ(replay.next_batch(1, out), Status::Error);
    EXPECT_TRUE(out.empty());
    EXPECT_EQ(replay.error(),
              (ReplayError{ReplayError::FellBehind, 0, 0,
                           static_cast<Seq>(block_entries + 1)}));
    e.check_invariants();
  }
}
TEST(EngineIndex, V18ConsumedRecycledBlockReseeksStillRetainedCheckpoint) {
  // B=1: seq1's block is freed by capacity eviction, but the unread seq2
  // checkpoint remains retained. A stale consumed block must not be advanced.
  Engine e(config(64, 8, 1));
  const auto a = e.intern("itch/A/add");
  const auto sub = e.compile(subtree("itch/A"));
  e.publish(a, bytes(16));
  e.publish(a, bytes(16));
  auto replay = e.open_replay(sub, Seq{0}, ReplayMode::Indexed);
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  ASSERT_EQ(out[0].seq, 1U);
  e.publish(a, bytes(16));
  ASSERT_EQ(e.stats().tail_pos, 32U);
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  ASSERT_EQ(out.size(), 1U);
  EXPECT_EQ(out[0].seq, 2U);
  EXPECT_EQ(replay.next_batch(1, out), Status::Done);
  e.check_invariants();
}
TEST(EngineIndex, V19PressureMatchesIndependentHandScheduleIncludingPad) {
  Engine e(config(64, 1, 1));
  const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
  constexpr std::array<std::size_t, 5> lengths{10, 4, 8, 0, 8};
  constexpr std::array<LogPos, 5> starts{0, 32, 64, 88, 104};
  constexpr std::array<LogPos, 5> heads{32, 56, 88, 104, 128};
  constexpr std::array<LogPos, 5> tails{0, 32, 56, 88, 104};
  constexpr std::array<std::uint64_t, 5> lost_bytes{0, 32, 56, 88, 104};
  for (std::size_t i = 0; i < lengths.size(); ++i) {
    EXPECT_EQ(e.publish(i % 2 ? b : a, bytes(lengths[i])), i + 1);
    EXPECT_EQ(e.stats().head_pos, heads[i]);
    EXPECT_EQ(e.stats().tail_pos, tails[i]);
    EXPECT_EQ(e.stats().tail_seq, i + 1);
    EXPECT_EQ(e.ring().stats().pressure_data_evicted, i);
    EXPECT_EQ(e.ring().stats().pressure_bytes_evicted, lost_bytes[i]);
    EXPECT_EQ(e.ring().stats().data_evicted, i);
    ASSERT_EQ(e.index()->entries().size(), 1U);
    EXPECT_EQ(e.index()->entries()[0].pos, starts[i]);
    EXPECT_EQ(e.index()->metadata()[0].gen, i);
    const auto gauges = e.index()->stats().gauges;
    EXPECT_EQ(gauges.live_entries, 1U);
    EXPECT_EQ(gauges.allocated_blocks, 1U);
    EXPECT_EQ(gauges.open_slack + gauges.sealed_partial_slack +
                  gauges.free_block_slots + gauges.expired_allocated_entries,
              0U);
    EXPECT_EQ(e.index()->stats().counters.allocations, i + 1);
    EXPECT_EQ(e.index()->stats().counters.frees, i);
    EXPECT_EQ(e.index()->stats().allocated_high_water, 1U);
    e.check_invariants();
  }
}
TEST(EngineIndex, V19RejectBeforeHypotheticalCapacityOrPressureEviction) {
  auto c = config(64, 1, 2);
  c.pool_policy = PoolPolicy::RejectPublish;
  Engine e(c);
  const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
  e.publish(a, bytes(16));
  e.publish(a, bytes(16));
  ASSERT_EQ(e.stats().head_pos, 64U);
  const auto before = snapshot(e);
  // Ordinary capacity eviction would remove seq1 while leaving seq2 in the
  // sole full index block. Reject must preserve both, not partially evict.
  EXPECT_THROW(e.publish(b, bytes(0)), PoolExhausted);
  unchanged(e, before);
  auto replay = e.open_replay(e.compile(subtree("itch/A")), Seq{0},
                              ReplayMode::Indexed);
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(10, out), Status::Done);
  ASSERT_EQ(out.size(), 2U);
  EXPECT_EQ(out[0].seq, 1U);
  EXPECT_EQ(out[1].seq, 2U);
}
TEST(EngineIndex, V19GenerationExhaustionRejectsBeforeEviction) {
  auto c = config(64, 1, 1);
  c.index.generation_limit = 1;
  Engine e(c);
  const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
  e.publish(a, bytes(16));
  e.publish(b, bytes(16));
  ASSERT_EQ(e.index()->metadata()[0].gen, 1U);
  const auto before = snapshot(e);
  EXPECT_THROW(e.publish(a, bytes(16)), index::RepresentationLimit);
  unchanged(e, before);
}
TEST(EngineIndex, V19OversizeAndRepresentationalLimitsPreserveIndexToo) {
  auto c = config(64, 8, 2);
  c.position_limit = 128;
  c.sequence_limit = 4;
  Engine e(c);
  const auto a = e.intern("itch/A/add");
  e.publish(a, bytes(16));
  auto before = snapshot(e);
  EXPECT_THROW(e.publish(a, bytes(17)), std::length_error);
  EXPECT_THROW(e.publish(0, bytes(0)), std::out_of_range);
  unchanged(e, before);
  e.publish(a, bytes(16));
  e.publish(a, bytes(16));
  before = snapshot(e);
  EXPECT_THROW(e.publish(a, bytes(16)), std::overflow_error);
  unchanged(e, before);
}
TEST(EngineIndex, V19SizingBoundGenericAndEnforcedItchMinimum) {
  for (const std::uint32_t minimum : {16U, 32U})
    for (const std::uint32_t entries : {1U, 2U, 4U, 16U}) {
      auto c = config(256, 1, entries);
      c.minimum_record_bytes = minimum;
      // Registered partitions include the unused single-segment ancestor.
      constexpr std::uint64_t partition_bound = 6;
      c.index.blocks = index::Index::sizing_blocks(
          c.ring_bytes, minimum, entries, partition_bound);
      Engine e(c);
      std::array<TopicId, 5> ids{};
      for (std::size_t i = 0; i < ids.size(); ++i)
        ids[i] = e.intern("itch/S" + std::to_string(i) + "/add");
      ASSERT_LE(e.registry().partition_count(), partition_bound);
      for (std::size_t i = 0; i < 400; ++i) {
        e.publish(ids[(i / 7) % ids.size()], bytes(minimum - 16));
        e.check_invariants();
      }
      EXPECT_EQ(e.ring().stats().pressure_data_evicted, 0U);
      if (minimum == 32) {
        const auto before = snapshot(e);
        EXPECT_THROW(e.publish(ids[0], bytes(0)), std::length_error);
        unchanged(e, before);
      }
    }
}
TEST(EngineIndex, V20IndexedEmptyAndFutureFollowCommonProgress) {
  Engine e(config());
  const auto a = e.intern("itch/A/add");
  e.publish(a, bytes(8));
  auto missing = e.open_replay(e.compile(exact("itch/missing/add")), Seq{0},
                               ReplayMode::Indexed);
  EXPECT_EQ(missing.status(), Status::More);
  const auto before = missing.checkpoint();
  std::vector<Delivered> out;
  EXPECT_EQ(missing.next_batch(0, out), Status::More);
  EXPECT_EQ(missing.checkpoint(), before);
  EXPECT_EQ(missing.next_batch(1, out), Status::Done);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(missing.checkpoint(), (ResumeCheckpoint{1, 24}));
  auto future = e.open_replay(e.compile(exact("itch/A/add")), UINT64_MAX,
                              ReplayMode::Indexed);
  EXPECT_EQ(future.status(), Status::Done);
  EXPECT_FALSE(future.checkpoint());
}
TEST(EngineIndex, V20EmptyIndexedCursorStillChecksConservativeExpiry) {
  Engine e(config(64, 1, 1));
  const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
  e.publish(a, bytes(16));
  auto missing = e.open_replay(e.compile(exact("itch/B/add")), Seq{0},
                               ReplayMode::Indexed);
  EXPECT_EQ(missing.status(), Status::More);
  e.publish(b, bytes(16));
  std::vector<Delivered> out;
  EXPECT_EQ(missing.next_batch(1, out), Status::Error);
  EXPECT_EQ(missing.error(), (ReplayError{ReplayError::FellBehind, 0, 0, 2}));
}
TEST(EngineIndex, V20ExactFinalBudgetCompletesBeforeExpiredCursorAccess) {
  Engine e(config(64, 1, 1));
  const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
  e.publish(a, bytes(16));
  auto replay = e.open_replay(e.compile(exact("itch/A/add")), Seq{0},
                              ReplayMode::Indexed);
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 32}));
  for (unsigned i = 0; i < 4; ++i)
    e.publish(b, bytes(16));
  EXPECT_EQ(replay.next_batch(0, out), Status::More);
  EXPECT_EQ(replay.next_batch(1, out), Status::Done);
  EXPECT_FALSE(replay.error());
}
TEST(EngineIndex, V20FullBudgetDoesNotLookPastFilteredGap) {
  Engine e(config(1024, 64, 2));
  const auto a = e.intern("itch/A/add"), b = e.intern("itch/A/cancel");
  e.publish(a, bytes(0));
  for (unsigned i = 0; i < 20; ++i)
    e.publish(b, bytes(0));
  auto replay = e.open_replay(e.compile(exact("itch/A/add")), Seq{0},
                              ReplayMode::Indexed);
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 16}));
  EXPECT_EQ(replay.next_batch(1, out), Status::Done);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{21, 336}));
}
TEST(EngineIndex, V20DynamicFilterGrowthDoesNotLeaveDanglingPointers) {
  Engine e(config(4096, 64, 4));
  const auto sub = e.compile(subtree("itch/A/add"));
  const auto a = e.intern("itch/A/add/a");
  e.publish(a, bytes(8));
  e.publish(a, bytes(8));
  auto replay = e.open_replay(sub, Seq{0}, ReplayMode::Indexed);
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  for (unsigned i = 0; i < 80; ++i) {
    const auto t = e.intern("itch/Z" + std::to_string(i) + "/add");
    const auto later = e.intern("itch/A/add/later" + std::to_string(i));
    static_cast<void>(t);
    static_cast<void>(later);
  }
  e.publish(e.intern("itch/A/add/new"), bytes(8));
  EXPECT_EQ(replay.next_batch(10, out), Status::Done);
  ASSERT_EQ(out.size(), 1U);
  EXPECT_EQ(out[0].seq, 2U); // captured upper excludes new seq3
  auto chained = e.open_replay(sub, *replay.checkpoint(), ReplayMode::Indexed);
  EXPECT_EQ(chained.next_batch(10, out), Status::Done);
  ASSERT_EQ(out.size(), 1U);
  EXPECT_EQ(out[0].seq, 3U);
}
TEST(EngineIndex, V20WideFallsBackAndMultiplePartitionsMerge) {
  Engine e(config());
  const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
  e.publish(a, bytes(0));
  e.publish(b, bytes(0));
  auto wide = e.open_replay(e.compile(subtree("itch")), Seq{0},
                            ReplayMode::Indexed);
  EXPECT_EQ(wide.effective_mode(), ReplayMode::Scan);
  auto merged = e.open_replay(
      e.compile({{{Term::Exact, "itch/A/add"}, {Term::Exact, "itch/B/add"}}}),
      Seq{0}, ReplayMode::Indexed);
  std::vector<Delivered> out;
  EXPECT_EQ(merged.next_batch(8, out), Status::Done);
  ASSERT_EQ(out.size(), 2U);
  EXPECT_EQ(out[0].seq, 1U);
  EXPECT_EQ(out[1].seq, 2U);
}
TEST(EngineIndex, V20DisabledIndexPreservesScanAndRejectsIndexed) {
  auto c = config();
  c.index_enabled = false;
  Engine e(c);
  EXPECT_EQ(e.index(), nullptr);
  const auto a = e.intern("itch/A/add");
  e.publish(a, bytes(8));
  auto scan = e.open_replay(e.compile(exact("itch/A/add")), Seq{0});
  std::vector<Delivered> out;
  EXPECT_EQ(scan.next_batch(3, out), Status::Done);
  EXPECT_THROW(static_cast<void>(e.open_replay(e.compile(exact("itch/A/add")),
      Seq{0}, ReplayMode::Indexed)), std::invalid_argument);
  e.check_invariants();
}
TEST(EngineIndex, V20RetainedPadCheckpointRemainsConservative) {
  Engine e(config(64, 8, 2));
  const auto a = e.intern("itch/A/add");
  e.publish(a, bytes(10));
  e.publish(a, bytes(4));
  e.publish(a, bytes(8));
  e.publish(a, bytes(0));
  ASSERT_EQ(e.stats().tail_pos, 56U);
  auto replay = e.open_replay(e.compile(exact("itch/A/add")),
                              ResumeCheckpoint{2, 56}, ReplayMode::Indexed);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{2, 56}));
  e.publish(a, bytes(8));
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::Error);
  EXPECT_EQ(replay.error(), (ReplayError{ReplayError::FellBehind, 2, 2, 3}));
}
TEST(EngineIndex, V19AliasedInputCopiesBeforeEvictionAndIndexMutation) {
  Engine e(config(64, 8, 1));
  const auto a = e.intern("itch/A/add");
  e.publish(a, bytes(16, 23));
  const auto copied = e.ring().at(0).payload;
  e.publish(a, bytes(16, 31));
  e.publish(a, copied);
  const auto item = e.ring().at(64);
  EXPECT_EQ(item.seq, 3U);
  EXPECT_TRUE(std::ranges::all_of(item.payload, [](std::byte b) {
    return b == std::byte{23};
  }));
  e.check_invariants();
}
TEST(EngineIndex, V19MinimumConfigurationValidatedBeforeUse) {
  auto c = config();
  c.minimum_record_bytes = 24;
  EXPECT_THROW(Engine invalid(c), std::invalid_argument);
  c.minimum_record_bytes = 32;
  c.max_record_bytes = 16;
  EXPECT_THROW(Engine invalid(c), std::invalid_argument);
}
TEST(EngineIndex, AutoUsesRecentSparsePostingInPartiallyOverlappingBlock) {
  auto c = config(131072, 32, 1024);
  Engine engine(c);
  const auto a = engine.intern("r/A/e"), b = engine.intern("r/B/e");
  const auto sub = engine.compile(exact("r/A/e"));
  for (int i = 0; i < 1023; ++i) engine.publish(a, {});
  for (int i = 0; i < 4000; ++i) engine.publish(b, {});
  engine.publish(a, {});
  auto automatic = engine.open_replay(sub, 1023, ReplayMode::Auto);
  auto indexed = engine.open_replay(sub, 1023, ReplayMode::Indexed);
  auto scan = engine.open_replay(sub, 1023, ReplayMode::Scan);
  ASSERT_EQ(automatic.effective_mode(), ReplayMode::Indexed);
  std::vector<Delivered> actual, indexed_out, scanned;
  EXPECT_EQ(automatic.next_batch(2, actual), Status::Done);
  EXPECT_EQ(indexed.next_batch(2, indexed_out), Status::Done);
  EXPECT_EQ(scan.next_batch(2, scanned), Status::Done);
  ASSERT_EQ(actual.size(), 1U);
  ASSERT_EQ(indexed_out.size(), 1U);
  ASSERT_EQ(scanned.size(), 1U);
  EXPECT_EQ(actual[0].seq, 5024U);
  EXPECT_EQ(actual[0].seq, indexed_out[0].seq);
  EXPECT_EQ(actual[0].seq, scanned[0].seq);
  EXPECT_EQ(automatic.checkpoint(), scan.checkpoint());
  EXPECT_EQ(automatic.work().records_fetched, 1U);
  EXPECT_EQ(scan.work().records_fetched, 4001U);
  engine.check_invariants();
}
} // namespace
} // namespace tiplog
