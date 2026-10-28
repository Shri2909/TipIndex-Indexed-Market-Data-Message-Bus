// Negative controls for the invariant checkers adopted from AUD-003.
// Each checker must reject corrupted state: a no-op checker must fail this suite.
// Each test corrupts one field of otherwise valid state through the public
// read-only views (the underlying storage is non-const) and requires a throw.
#include "tiplog/engine/engine.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <stdexcept>
#include <vector>

namespace tiplog {
namespace {

Engine populated(std::size_t ring = 256) {
  EngineConfig config;
  config.ring_bytes = ring;
  config.max_record_bytes = 64;
  config.index.entries_per_block = 2;
  config.index.blocks = 64;
  return Engine(config);
}

void fill(Engine& engine, int records) {
  const auto a = engine.intern("x/A/e");
  const auto b = engine.intern("x/B/e");
  for (int i = 0; i < records; ++i)
    engine.publish(i % 3 ? a : b, std::vector<std::byte>(static_cast<std::size_t>(5 + i % 7), std::byte{9}));
}

std::byte* mutable_ring(const Engine& engine) {
  return const_cast<std::byte*>(engine.ring().storage_bytes().data());
}

TEST(InvariantChecker, RingDetectsNonzeroFill) {
  auto engine = populated();
  fill(engine, 3);  // record 1: 16+5 -> 24 bytes with 3 fill bytes at [21,24)
  ASSERT_NO_THROW(engine.ring().check_invariants());
  mutable_ring(engine)[22] = std::byte{1};
  EXPECT_THROW(engine.ring().check_invariants(), std::logic_error);
}

TEST(InvariantChecker, RingDetectsSequenceGap) {
  auto engine = populated();
  fill(engine, 3);
  ASSERT_NO_THROW(engine.ring().check_invariants());
  mutable_ring(engine)[24 + 8] = std::byte{7};  // seq field of the second record
  EXPECT_THROW(engine.ring().check_invariants(), std::logic_error);
}

TEST(InvariantChecker, IndexDetectsCorruptedBlockCount) {
  auto engine = populated();
  fill(engine, 9);
  ASSERT_NO_THROW(engine.index()->check_invariants(engine.ring().tail_pos()));
  auto& meta = const_cast<std::vector<index::BlockMeta>&>(engine.index()->metadata());
  const auto victim = std::find_if(meta.begin(), meta.end(),
                                   [](const auto& m) { return m.partition != index::none && m.count > 1; });
  ASSERT_NE(victim, meta.end());
  --victim->count;
  EXPECT_THROW(engine.index()->check_invariants(engine.ring().tail_pos()), std::logic_error);
}

TEST(InvariantChecker, EngineDetectsRetainedRecordOnWrongTopicPartition) {
  auto engine = populated();
  fill(engine, 6);
  ASSERT_NO_THROW(engine.check_invariants());
  // Re-label the first retained record as topic x/B/e (id 4) while its index
  // posting stays in x/A's partition: the ring/index cover check must fail.
  const auto first = engine.ring().at(engine.ring().tail_pos());
  const auto other = first.topic == engine.registry().find("x/A/e") ? *engine.registry().find("x/B/e")
                                                                    : *engine.registry().find("x/A/e");
  auto* header = mutable_ring(engine) + (engine.ring().tail_pos() % engine.config().ring_bytes);
  for (int i = 0; i < 4; ++i) header[4 + i] = static_cast<std::byte>((other >> (8 * i)) & 0xff);
  EXPECT_THROW(engine.check_invariants(), std::logic_error);
}

}  // namespace
}  // namespace tiplog
