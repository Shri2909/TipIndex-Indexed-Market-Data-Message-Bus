#include "tiplog/index/index.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <limits>
#include <map>
#include <random>
#include <utility>
#include <vector>

namespace {
using namespace tiplog;
using index::Config;
using index::Index;

void append(Index &pool, PartitionId partition, LogPos pos, LogPos tail,
            std::uint64_t live, std::size_t partitions = 4,
            std::uint64_t evictions = 0) {
  auto preparation =
      pool.prepare_append(partition, pos, tail, partitions, evictions);
  ASSERT_TRUE(std::holds_alternative<index::PreparedAppend>(preparation));
  pool.commit(std::move(std::get<index::PreparedAppend>(preparation)), live);
  EXPECT_NO_THROW(pool.check_invariants(tail));
  EXPECT_EQ(pool.stats().gauges, pool.recount(tail).gauges);
  EXPECT_EQ(pool.stats().memory, pool.recount(tail).memory);
}
std::vector<LogPos> positions(const Index &pool, PartitionId partition,
                              LogPos lower) {
  std::vector<LogPos> out;
  auto cursor = pool.seek(partition, lower);
  while (cursor.valid()) {
    out.push_back(cursor.pos);
    pool.advance(cursor, pool.stats().tail_pos);
  }
  return out;
}
std::vector<std::pair<PartitionId, LogPos>> retained(const Index &pool,
                                                     LogPos tail) {
  std::vector<std::pair<PartitionId, LogPos>> out;
  for (const auto &posting : pool.retained_entries(tail))
    out.emplace_back(posting.partition, posting.pos);
  std::sort(out.begin(), out.end());
  return out;
}

TEST(IndexConfig, V15V37ValidatesPowerOfTwoLimitsAndSizingArithmetic) {
  EXPECT_THROW(Index((Config{0, 1})), std::invalid_argument);
  EXPECT_THROW(Index((Config{1, 0})), std::invalid_argument);
  EXPECT_THROW(Index((Config{1, 3})), std::invalid_argument);
  EXPECT_THROW(Index((Config{1, 1, 0, 0})), std::invalid_argument);
  EXPECT_THROW(Index((Config{1, 1, 0, 33})), std::invalid_argument);
  EXPECT_NO_THROW(Index((Config{1, 1, 0, 32, 0})));
  EXPECT_EQ(sizeof(index::BlockMeta), 32);
  EXPECT_EQ(Index::sizing_blocks(1024, 16, 4, 7), 31);
  EXPECT_EQ(Index::sizing_blocks(1024, 32, 4, 7), 23);
  EXPECT_EQ(Index::sizing_blocks(1040, 16, 4, 0), 18);
  EXPECT_THROW((void)Index::sizing_blocks(1024, 24, 4, 7),
               std::invalid_argument);
  EXPECT_THROW((void)Index::sizing_blocks(1024, 16, 3, 7),
               std::invalid_argument);
  EXPECT_THROW((void)Index::sizing_blocks(LogPos{1} << 35U, 16, 4, 7),
               std::invalid_argument);
  EXPECT_THROW((void)Index::sizing_blocks(1024, 16, 4, index::none),
               index::RepresentationLimit);
  EXPECT_THROW(Index((Config{index::none, std::uint32_t{1} << 31U})),
               std::length_error);
}

TEST(IndexPool, V15InitialFreeListAndExactReservedMemory) {
  Index pool({5, 4});
  pool.check_invariants(0);
  const auto stats = pool.stats();
  EXPECT_EQ(stats.gauges.free_blocks, 5);
  EXPECT_EQ(stats.gauges.free_block_slots, 20);
  EXPECT_EQ(stats.gauges.allocated_entries, 0);
  EXPECT_EQ(stats.memory.metadata_reserved_bytes, 5 * 32);
  EXPECT_EQ(stats.memory.entries_reserved_bytes, 20 * 4);
  EXPECT_EQ(stats.memory.sealed_flags_reserved_bytes, 5);
  EXPECT_GE(stats.memory.heap_reserved_bytes, 5 * 16);
  EXPECT_EQ(stats.memory.heap_used_bytes, 0);
  EXPECT_FALSE(stats.memory.allocator_overhead_measured);
  EXPECT_EQ(stats.memory, pool.recount(0).memory);
}

TEST(IndexPool, V15B1RepeatedFreeReuseHasExactlyOneGenerationIncrement) {
  Index pool({1, 1, 0});
  std::uint64_t independently_observed_high_water = 0;
  for (std::uint32_t i = 0; i < 1000; ++i) {
    const auto pos = static_cast<LogPos>(i) * 16;
    append(pool, i % 3, pos, pos, 1);
    const auto stats = pool.stats();
    independently_observed_high_water = std::max(
        independently_observed_high_water, stats.gauges.allocated_blocks);
    EXPECT_EQ(pool.metadata()[0].gen, i);
    EXPECT_EQ(pool.metadata()[0].partition, i % 3);
    EXPECT_EQ(stats.counters.allocations, i + 1);
    EXPECT_EQ(stats.counters.frees, i);
    EXPECT_EQ(stats.allocated_high_water, independently_observed_high_water);
    EXPECT_EQ(stats.gauges.live_entries, 1);
    EXPECT_EQ(stats.gauges.expired_allocated_entries, 0);
    EXPECT_EQ(stats.gauges.open_slack + stats.gauges.sealed_partial_slack, 0);
  }
}

TEST(IndexPool, V15NearGenerationLimitRejectsBeforeMembershipChanges) {
  Index pool({1, 1, 0, 32, 1});
  append(pool, 0, 0, 0, 1);
  append(pool, 1, 16, 16, 1);
  ASSERT_EQ(pool.metadata()[0].gen, 1);
  const auto before = pool.entries();
  const auto metadata = pool.metadata();
  const auto gauges = pool.stats().gauges;
  const auto allocations = pool.stats().counters.allocations;
  EXPECT_THROW((void)pool.prepare_append(0, 32, 32, 4),
               index::RepresentationLimit);
  EXPECT_EQ(pool.entries(), before);
  EXPECT_EQ(pool.metadata(), metadata);
  EXPECT_EQ(pool.stats().gauges, gauges);
  EXPECT_EQ(pool.stats().tail_pos, 16);
  EXPECT_EQ(pool.stats().counters.allocations, allocations);
  pool.check_invariants(16);
}

TEST(IndexPool, V15GenerationZeroLimitAllowsInitialAllocationButNoFree) {
  Index pool({2, 2, 0, 32, 0});
  append(pool, 0, 0, 0, 1);
  const auto metadata = pool.metadata();
  EXPECT_THROW((void)pool.prepare_append(0, 16, 16, 4),
               index::RepresentationLimit);
  EXPECT_EQ(pool.metadata(), metadata);
  pool.check_invariants(0);
}

TEST(IndexPreparation, V19AbandonedPreparationDoesNotPublishOrReclaim) {
  Index pool({3, 2, 0});
  append(pool, 0, 0, 0, 1);
  append(pool, 0, 16, 0, 2);
  const auto metadata = pool.metadata();
  const auto entries = pool.entries();
  const auto gauges = pool.stats().gauges;
  {
    auto plan = pool.prepare_append(1, 64, 64, 20, 2);
    ASSERT_TRUE(std::holds_alternative<index::PreparedAppend>(plan));
  }
  EXPECT_EQ(pool.metadata(), metadata);
  EXPECT_EQ(pool.entries(), entries);
  EXPECT_EQ(pool.stats().gauges, gauges);
  EXPECT_EQ(pool.stats().tail_pos, 0);
  EXPECT_EQ(pool.stats().counters.frees, 0);
  EXPECT_EQ(pool.stats().memory, pool.recount(0).memory);
}

TEST(IndexPreparation, V19PressureCandidateDoesNotMutatePoolMembership) {
  Index pool({2, 2, 0});
  append(pool, 0, 0, 0, 1);
  append(pool, 1, 16, 0, 2);
  const auto before = pool.stats();
  const auto metadata = pool.metadata();
  const auto entries = pool.entries();
  const auto plan = pool.prepare_append(2, 32, 0, 4);
  ASSERT_TRUE(std::holds_alternative<index::NeedTailThrough>(plan));
  EXPECT_EQ(std::get<index::NeedTailThrough>(plan).last_pos, 0);
  EXPECT_EQ(pool.metadata(), metadata);
  EXPECT_EQ(pool.entries(), entries);
  EXPECT_EQ(pool.stats(), before);
  // The exact oldest open block is now reclaimable; the unrelated live block
  // remains, and pressure sweeps are counted only after a successful commit.
  append(pool, 2, 32, 16, 2, 4, 1);
  EXPECT_EQ(pool.stats().counters.sweeps, 1);
  EXPECT_EQ(pool.stats().counters.swept_partitions, 4);
  EXPECT_EQ(retained(pool, 16),
            (std::vector<std::pair<PartitionId, LogPos>>{{1, 16}, {2, 32}}));
}

TEST(IndexExpiry, V17TailEqualityRemainsRetainedAndStrictGreaterReclaims) {
  Index pool({3, 1, 0});
  append(pool, 0, 0, 0, 1);
  append(pool, 1, 16, 0, 2);
  EXPECT_EQ(pool.stats().counters.frees, 0);
  append(pool, 2, 32, 16, 2, 4, 1);
  EXPECT_EQ(pool.stats().counters.frees, 1);
  EXPECT_EQ(positions(pool, 1, 16), (std::vector<LogPos>{16}));
  EXPECT_EQ(pool.stats().gauges.live_entries, 2);
  EXPECT_EQ(pool.stats().gauges.sealed_blocks, 2);
}

TEST(IndexExpiry, V17ColdExpiredOpenIsSoleThenPeriodicSweepReclaimsIt) {
  Index pool({6, 4, 2});
  append(pool, 0, 0, 0, 1);
  append(pool, 1, 16, 0, 2);
  append(pool, 1, 32, 16, 2, 4, 1);
  EXPECT_EQ(pool.stats().gauges.expired_allocated_entries, 1);
  EXPECT_EQ(pool.stats().counters.sweeps, 0);
  append(pool, 1, 48, 32, 2, 4, 1);
  EXPECT_EQ(pool.stats().counters.sweeps, 1);
  EXPECT_EQ(pool.stats().counters.frees, 1);
  EXPECT_EQ(pool.stats().gauges.expired_allocated_entries, 1);
  EXPECT_EQ(pool.stats().gauges.allocated_blocks, 1);
  EXPECT_TRUE(positions(pool, 0, 32).empty());
}

TEST(IndexExpiry, V17ExpiredTargetOpenIsReplacedAndBaseRecomputed) {
  Index pool({2, 4, 0, 2});
  append(pool, 0, 0, 0, 1);
  append(pool, 0, 128, 128, 1, 4, 1);
  const auto cursor = pool.seek(0, 128);
  ASSERT_TRUE(cursor.valid());
  EXPECT_EQ(pool.metadata()[cursor.block].base_pos, 128);
  EXPECT_EQ(pool.metadata()[cursor.block].count, 1);
  EXPECT_EQ(pool.metadata()[cursor.block].gen, 1);
  EXPECT_EQ(pool.stats().counters.seals, 0);
  EXPECT_EQ(pool.stats().counters.frees, 1);
}

TEST(IndexExpiry, V37LatePartialSealExpiresBeforeEarlierNewerFullSeal) {
  Index pool({8, 4, 0, 4}); // delta span=128 bytes, intentionally reduced.
  append(pool, 0, 0, 0, 1);
  append(pool, 0, 64, 0, 2); // A open last64, count2.
  for (const auto pos : {80U, 96U, 112U, 128U})
    append(pool, 1, pos, 0, pos == 80 ? 3 : pos == 96 ? 4 : pos == 112 ? 5 : 6);
  EXPECT_EQ(pool.stats().counters.seals, 1); // B full last128 seals first.
  append(pool, 0, 256, 0, 7); // A old partial last64 seals later.
  EXPECT_EQ(pool.stats().counters.seals, 2);
  EXPECT_EQ(pool.stats().gauges.sealed_partial_slack, 2);
  const auto old_a = pool.seek(0, 0).block;
  const auto old_b = pool.seek(1, 0).block;
  append(pool, 2, 272, 72, 6, 4, 2);
  EXPECT_EQ(pool.metadata()[old_a].partition, 2);
  EXPECT_EQ(pool.metadata()[old_a].gen, 1);
  EXPECT_EQ(pool.metadata()[old_b].partition, 1);
  EXPECT_EQ(pool.metadata()[old_b].gen, 0);
  EXPECT_EQ(pool.stats().counters.heap_pops, 1);
  EXPECT_EQ(pool.stats().gauges.sealed_partial_slack, 0);
  EXPECT_EQ(positions(pool, 1, 72), (std::vector<LogPos>{80, 96, 112, 128}));
}

TEST(IndexDelta, V37WideBeforeNarrowProductionSpanAndExactOverflowBoundary) {
  Index pool({4, 4, 0});
  constexpr LogPos span = LogPos{1} << 35U;
  append(pool, 0, 0, 0, 1);
  append(pool, 0, span - 8, 0, 2);
  EXPECT_EQ(pool.stats().gauges.allocated_blocks, 1);
  append(pool, 0, span, 0, 3);
  EXPECT_EQ(pool.stats().gauges.allocated_blocks, 2);
  EXPECT_EQ(pool.stats().gauges.sealed_partial_slack, 2);
  EXPECT_EQ(positions(pool, 0, 0), (std::vector<LogPos>{0, span - 8, span}));
}

TEST(IndexAccounting, V17OpenSealedExpiredFreeSlotsAreSeparateAndExact) {
  Index pool({4, 4, 0, 3}); // test span64.
  append(pool, 0, 0, 0, 1);
  append(pool, 0, 16, 0, 2);
  append(pool, 0, 64, 0,
         3); // partial seal count2/slack2, new open count1/slack3.
  append(pool, 1, 80, 8, 3, 4,
         1); // old pos0 stale allocated; last16 retains block.
  const auto g = pool.stats().gauges;
  EXPECT_EQ(g.live_entries, 3);
  EXPECT_EQ(g.expired_allocated_entries, 1);
  EXPECT_EQ(g.allocated_entries, 4);
  EXPECT_EQ(g.open_slack, 6);
  EXPECT_EQ(g.sealed_partial_slack, 2);
  EXPECT_EQ(g.free_block_slots, 4);
  EXPECT_EQ(g.live_entries + g.expired_allocated_entries + g.open_slack +
                g.sealed_partial_slack + g.free_block_slots,
            16);
  EXPECT_EQ(pool.stats().memory.heap_used_bytes, 16);
  EXPECT_GE(pool.stats().memory.partition_list_reserved_bytes,
            pool.stats().memory.partition_list_used_bytes);
}

TEST(IndexCursor, V18B1B2CachedPositionAndGenerationDefendRecycledBlocks) {
  for (const auto b : {1U, 2U}) {
    Index pool({1, b, 0});
    append(pool, 0, 0, 0, 1);
    auto old = pool.seek(0, 0);
    const auto old_block = old.block;
    append(pool, 1, 32, 32, 1, 4, 1);
    ASSERT_EQ(pool.seek(1, 32).block, old_block);
    EXPECT_THROW(pool.advance(old, 32), index::StaleCursor);
    // Deliberately corrupt the cached guard to reach the generation defense.
    old.pos = 32;
    EXPECT_THROW(pool.advance(old, 32), index::StaleCursor);
    auto current = pool.seek(1, 32);
    EXPECT_FALSE(pool.advance(current, 32));
    EXPECT_FALSE(current.valid());
    EXPECT_THROW(pool.advance(current, 32), index::StaleCursor);
  }
}

TEST(IndexCursor, V16BinarySeekAcrossChainsAndNoIteratorDependenceOnGrowth) {
  Index pool({40, 2, 0});
  std::vector<LogPos> expected;
  for (std::uint32_t i = 0; i < 50; ++i) {
    const auto pos = static_cast<LogPos>(i) * 16;
    append(pool, 0, pos, 0, i + 1, 1);
    expected.push_back(pos);
  }
  for (LogPos lower = 0; lower < 816; lower += 8) {
    const auto first =
        std::lower_bound(expected.begin(), expected.end(), lower);
    EXPECT_EQ(positions(pool, 0, lower),
              (std::vector<LogPos>(first, expected.end())));
  }
  auto cursor = pool.seek(0, 0);
  append(pool, 20, 800, 0, 51, 21);
  EXPECT_TRUE(pool.advance(cursor, 0));
  EXPECT_EQ(cursor.pos, 16);
  EXPECT_EQ(pool.estimate_count(0, 0, 800), 50);
  EXPECT_EQ(pool.estimate_count(99, 0, 800), 0);
  EXPECT_EQ(pool.estimate_count(0, 800, 800), 0);
}

TEST(IndexRandom, V15V16V17B1B2AndPartialBlocksMatchIndependentHistory) {
  for (const auto b : {1U, 2U, 4U}) {
    Index pool({256, b, 13, 5});
    std::mt19937_64 rng(20191230 + b);
    std::vector<std::pair<PartitionId, LogPos>> history;
    std::uint64_t maximum_allocated = 0;
    LogPos tail = 0;
    LogPos pos = 0;
    std::uint64_t previously_retained = 0;
    for (std::uint32_t i = 0; i < 6000; ++i) {
      pos += (1 + rng() % 8) * 8;
      const auto partition = static_cast<PartitionId>(rng() % 11);
      if (pos > 1024)
        tail = std::max(tail, (pos - 1024) & ~LogPos{7});
      history.emplace_back(partition, pos);
      std::vector<std::pair<PartitionId, LogPos>> expected;
      for (const auto &entry : history)
        if (entry.second >= tail)
          expected.push_back(entry);
      const auto live = expected.size();
      const auto evicted = previously_retained + 1 - live;
      append(pool, partition, pos, tail, live, 11, evicted);
      previously_retained = live;
      std::sort(expected.begin(), expected.end());
      ASSERT_EQ(retained(pool, tail), expected);
      const auto stats = pool.stats();
      maximum_allocated =
          std::max(maximum_allocated, stats.gauges.allocated_blocks);
      ASSERT_EQ(stats.allocated_high_water, maximum_allocated);
      for (PartitionId p = 0; p < 11; ++p) {
        std::vector<LogPos> wanted;
        for (const auto &[owner, at] : expected)
          if (owner == p)
            wanted.push_back(at);
        ASSERT_EQ(positions(pool, p, tail), wanted);
      }
    }
  }
}

TEST(IndexSizing, V19Generic16AndEnforced32AmpleBoundNeverNeedsPressure) {
  constexpr std::uint64_t capacity = 4096;
  constexpr std::uint32_t partitions = 13;
  for (const auto minimum : {16U, 32U}) {
    for (const auto b : {1U, 2U, 16U}) {
      const auto n = Index::sizing_blocks(capacity, minimum, b, partitions);
      Index pool({n, b, 10000});
      std::mt19937 rng(42 + b + minimum);
      std::uint64_t previous_live = 0;
      for (std::uint32_t i = 0; i < 5000; ++i) {
        const auto pos = static_cast<LogPos>(i) * minimum;
        const auto tail =
            pos + minimum > capacity ? pos + minimum - capacity : 0;
        const auto live = std::min<std::uint64_t>(i + 1, capacity / minimum);
        append(pool, static_cast<PartitionId>(rng() % partitions), pos, tail,
               live, partitions, previous_live + 1 - live);
        previous_live = live;
      }
      EXPECT_LE(pool.stats().allocated_high_water, n);
    }
  }
}

TEST(IndexPreparation, V15RejectsInvalidInputsWithoutLogicalMutation) {
  Index pool({2, 2});
  append(pool, 0, 0, 0, 1);
  const auto metadata = pool.metadata();
  EXPECT_THROW((void)pool.prepare_append(index::none, 16, 0, 4),
               std::invalid_argument);
  EXPECT_THROW((void)pool.prepare_append(4, 16, 0, 4), std::invalid_argument);
  EXPECT_THROW((void)pool.prepare_append(0, 15, 0, 4), std::invalid_argument);
  EXPECT_THROW((void)pool.prepare_append(0, 16, 1, 4), std::invalid_argument);
  // An aligned tail above pos is invalid too.
  EXPECT_THROW((void)pool.prepare_append(0, 16, 24, 4), std::invalid_argument);
  EXPECT_THROW((void)pool.prepare_append(0, 0, 0, 4), std::invalid_argument);
  EXPECT_EQ(pool.metadata(), metadata);
}
} // namespace
