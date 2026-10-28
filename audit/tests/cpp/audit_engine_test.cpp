// Audit: engine unit, integration and differential tests that the production
// suite does not already make. Each test states the property it checks.
#include "scan_oracle.hpp"
#include "oracle_tail.hpp"
#include "tiplog/engine/engine.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <optional>
#include <random>
#include <string>
#include <vector>

namespace tiplog {
namespace {

std::vector<std::byte> random_payload(std::mt19937_64& random, std::size_t size) {
  std::vector<std::byte> bytes(size);
  for (auto& b : bytes) b = static_cast<std::byte>(random());
  return bytes;
}

// INV-Q7 (ARCHITECTURE 10): with identical API schedules, Scan, Indexed with
// every kernel, and Auto produce identical outputs, statuses, checkpoints and
// errors. Payloads are random bytes (the production differential campaign
// fills each payload with one repeated byte, which cannot detect intra-payload
// offset or ordering corruption).
TEST(AuditEngine, ModeAndKernelEquivalenceWithRandomPayloads) {
  std::uint64_t compared_batches = 0, delivered = 0;
  for (std::uint64_t seed = 1; seed <= 300; ++seed) {
    std::mt19937_64 random(seed);
    const std::size_t capacity = std::size_t{1024} << (seed % 4);
    EngineConfig config;
    config.ring_bytes = capacity;
    config.max_record_bytes = capacity / 4;
    config.index.entries_per_block = 1U << (seed % 5);
    config.index.blocks = index::Index::sizing_blocks(capacity, 16,
                                                      config.index.entries_per_block, 32);
    config.auto_max_index_fraction = (seed % 2) ? 1.0 : 0.25;
    Engine engine(config);
    ref::ScanOracle oracle({capacity, capacity / 4});
    const std::vector<std::string> paths{"m/A/add", "m/A/del", "m/B/add", "m/B",
                                         "m/C/x/y", "n/A/add", "n"};
    const std::vector<SubscriptionSpec> specs{
        {{{Term::Subtree, "m/A"}}},
        {{{Term::Exact, "m/A/add"}, {Term::Exact, "m/B/add"}}},
        {{{Term::Subtree, "m/B"}, {Term::Subtree, "n/A"}, {Term::Exact, "m/C/x/y"}}},
        {{{Term::Subtree, "m"}}},
        {{{Term::Exact, "n"}}}};
    std::vector<subs::CompiledSubscription> compiled;
    for (const auto& s : specs) compiled.push_back(engine.compile(s));
    for (std::uint64_t round = 0; round < 40; ++round) {
      const auto publishes = random() % 40;
      for (std::uint64_t i = 0; i < publishes; ++i) {
        const auto& path = paths[random() % paths.size()];
        const auto bytes = random_payload(random, random() % (capacity / 4 - 15));
        ASSERT_EQ(engine.publish(engine.intern(path), bytes), oracle.publish(path, bytes));
      }
      const auto spec = random() % specs.size();
      const auto tail = engine.stats().tail_seq;
      const Seq after = tail - 1 + random() % (engine.stats().head_seq - tail + 1);
      struct Arm {
        Replay replay;
      };
      std::vector<Arm> arms;
      arms.push_back({engine.open_replay(compiled[spec], after, ReplayMode::Scan)});
      for (const auto k : {MergeKernel::StdPQ, MergeKernel::BinHeap, MergeKernel::Quad,
                           MergeKernel::Loser})
        arms.push_back({engine.open_replay(compiled[spec], after, ReplayMode::Indexed, k)});
      arms.push_back({engine.open_replay(compiled[spec], after, ReplayMode::Auto,
                                         MergeKernel::Loser)});
      auto expected = oracle.open_replay(specs[spec], after);
      for (int step = 0; step < 50; ++step) {
        // Occasionally publish between batches so FellBehind paths are compared.
        if (random() % 4 == 0) {
          const auto& path = paths[random() % paths.size()];
          const auto bytes = random_payload(random, random() % (capacity / 4 - 15));
          ASSERT_EQ(engine.publish(engine.intern(path), bytes), oracle.publish(path, bytes));
        }
        const auto budget = static_cast<std::size_t>(random() % 7);
        std::vector<ref::OracleRecord> want;
        const auto want_status = expected.next_batch(budget, want);
        for (auto& arm : arms) {
          std::vector<Delivered> got;
          ASSERT_EQ(arm.replay.next_batch(budget, got), want_status);
          ASSERT_EQ(got.size(), want.size());
          for (std::size_t i = 0; i < got.size(); ++i) {
            ASSERT_EQ(got[i].seq, want[i].seq);
            ASSERT_EQ(got[i].pos, want[i].pos);
            ASSERT_TRUE(std::ranges::equal(got[i].payload, want[i].payload));
            ASSERT_EQ(engine.registry().get(got[i].topic).path, want[i].path);
          }
          ASSERT_EQ(arm.replay.checkpoint(), expected.checkpoint());
          ASSERT_EQ(arm.replay.error(), expected.error());
          ++compared_batches;
        }
        delivered += want.size();
        if (want_status != Status::More) break;
      }
      engine.check_invariants();
    }
  }
  std::cout << "[audit] mode-equivalence batches=" << compared_batches
            << " delivered(per arm)=" << delivered << "\n";
  EXPECT_GT(delivered, 10000U) << "schedule must deliver real records";
}

// INV-Q6: a Tail's concatenated polls equal the oracle Tail over a moving head,
// for every mode/kernel, with random payloads and random publication bursts.
TEST(AuditEngine, TailChainingMatchesReferenceAcrossModes) {
  std::uint64_t delivered = 0;
  for (std::uint64_t seed = 1; seed <= 200; ++seed) {
    std::mt19937_64 random(seed * 7919);
    const std::size_t capacity = 2048;
    EngineConfig config;
    config.ring_bytes = capacity;
    config.max_record_bytes = 256;
    config.index.entries_per_block = 4;
    config.index.blocks = index::Index::sizing_blocks(capacity, 16, 4, 32);
    Engine engine(config);
    ref::ScanOracle oracle({capacity, 256});
    const std::vector<std::string> paths{"x/A/1", "x/A/2", "x/B/1", "y"};
    const SubscriptionSpec spec{{{Term::Subtree, "x/A"}, {Term::Exact, "y"}}};
    const auto sub = engine.compile(spec);
    const auto mode = static_cast<ReplayMode>(seed % 3);
    const auto kernel = static_cast<MergeKernel>(seed % 4);
    auto actual = engine.open_tail(sub, 0, mode, kernel);
    ref::OracleTail expected(oracle, spec, 0);
    for (int step = 0; step < 300; ++step) {
      const auto burst = random() % 6;
      for (std::uint64_t i = 0; i < burst; ++i) {
        const auto& path = paths[random() % paths.size()];
        const auto bytes = random_payload(random, random() % 60);
        ASSERT_EQ(engine.publish(engine.intern(path), bytes), oracle.publish(path, bytes));
      }
      const auto budget = static_cast<std::size_t>(random() % 9);
      std::vector<Delivered> got;
      std::vector<ref::OracleRecord> want;
      ASSERT_EQ(actual.poll(budget, got), expected.poll(budget, want));
      ASSERT_EQ(got.size(), want.size());
      for (std::size_t i = 0; i < got.size(); ++i) {
        ASSERT_EQ(got[i].seq, want[i].seq);
        ASSERT_TRUE(std::ranges::equal(got[i].payload, want[i].payload));
      }
      ASSERT_EQ(actual.checkpoint(), expected.checkpoint());
      ASSERT_EQ(actual.error(), expected.error());
      delivered += got.size();
      if (actual.status() == Status::Error) break;
    }
  }
  EXPECT_GT(delivered, 5000U);
}

// Publishing a borrowed delivered payload that the same publish overwrites.
// plan_append must copy aliasing sources before eviction/overwrite.
TEST(AuditEngine, RepublishingAliasedPayloadThatIsOverwrittenKeepsBytes) {
  Engine engine({64, 32});
  const auto topic = engine.intern("a/b/c");
  const std::vector<std::byte> original{std::byte{1}, std::byte{2}, std::byte{3},
                                        std::byte{4}, std::byte{5}, std::byte{6},
                                        std::byte{7}, std::byte{8}};
  engine.publish(topic, original);                       // [0,24)
  engine.publish(topic, std::vector<std::byte>(8));      // [24,48)
  auto replay = engine.open_replay(engine.compile({{{Term::Exact, "a/b/c"}}}), 0);
  std::vector<Delivered> out;
  ASSERT_EQ(replay.next_batch(1, out), Status::More);
  const auto borrowed = out.front().payload;  // physical [16,24)
  // Needs 24 bytes with 16 to the end: PAD at 48, DATA at 64 -> physical [0,24),
  // which overwrites the borrowed source bytes.
  const auto seq = engine.publish(topic, borrowed);
  const auto item = engine.ring().at(64);
  EXPECT_EQ(item.seq, seq);
  EXPECT_TRUE(std::ranges::equal(item.payload, original));
}

// Lifetime: a Replay/Tail used after its Engine is destroyed must fail safely
// (release builds; debug builds assert in ~Engine by design).
#ifdef NDEBUG
TEST(AuditEngine, ReplayAndTailOutlivingEngineThrowInsteadOfUseAfterFree) {
  std::optional<Replay> replay;
  std::optional<Tail> tail;
  {
    Engine engine({256, 64});
    const auto topic = engine.intern("a/b");
    engine.publish(topic, std::vector<std::byte>(4));
    const auto sub = engine.compile({{{Term::Subtree, "a"}}});
    replay.emplace(engine.open_replay(sub, 0));
    tail.emplace(engine.open_tail(sub, 0));
  }
  std::vector<Delivered> out;
  EXPECT_THROW((void)replay->next_batch(1, out), std::logic_error);
  EXPECT_THROW((void)tail->poll(1, out), std::logic_error);
}
#endif

// Invalid topic IDs are rejected before any visible state mutation.
TEST(AuditEngine, InvalidTopicPublishDoesNotMutate) {
  Engine engine({256, 64});
  engine.publish(engine.intern("a/b"), std::vector<std::byte>(4));
  const auto before = engine.stats();
  EXPECT_THROW((void)engine.publish(0, std::vector<std::byte>(4)), std::out_of_range);
  EXPECT_THROW((void)engine.publish(999, std::vector<std::byte>(4)), std::out_of_range);
  const auto after = engine.stats();
  EXPECT_EQ(before.head_seq, after.head_seq);
  EXPECT_EQ(before.head_pos, after.head_pos);
  engine.check_invariants();
}

// The ResumeCheckpoint overload must never interpret an arbitrary aligned
// offset as a record boundary: supplied positions are sanitized.
TEST(AuditEngine, ForgedResumeCheckpointPositionsAreIgnored) {
  Engine engine({1024, 256});
  const auto topic = engine.intern("a/b/c");
  for (int i = 0; i < 10; ++i) {
    std::vector<std::byte> bytes(40, std::byte{0});
    // Plant a plausible DATA header inside the payload.
    bytes[0] = std::byte{48};  // size 48, fill 0
    bytes[4] = std::byte{1};   // topic 1
    bytes[8] = std::byte{0xEE};
    engine.publish(topic, bytes);
  }
  const auto sub = engine.compile({{{Term::Subtree, "a"}}});
  auto honest = engine.open_replay(sub, Seq{3});
  for (LogPos forged = 0; forged < engine.stats().head_pos + 64; forged += 8) {
    auto replay = engine.open_replay(sub, ResumeCheckpoint{3, forged});
    ASSERT_EQ(replay.checkpoint(), honest.checkpoint()) << forged;
    std::vector<Delivered> a, b;
    auto honest_copy = engine.open_replay(sub, Seq{3});
    ASSERT_EQ(replay.next_batch(100, a), honest_copy.next_batch(100, b));
    ASSERT_EQ(a.size(), b.size());
    for (std::size_t i = 0; i < a.size(); ++i) ASSERT_EQ(a[i].seq, b[i].seq);
  }
}

}  // namespace
}  // namespace tiplog
