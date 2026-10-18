#include "scan_oracle.hpp"
#include "tiplog/engine/engine.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <gtest/gtest.h>
#include <limits>
#include <string>

namespace tiplog {
namespace {
struct Choice { ReplayMode mode; MergeKernel kernel; };
constexpr std::array<Choice, 9> choices{{
    {ReplayMode::Scan, MergeKernel::StdPQ},
    {ReplayMode::Indexed, MergeKernel::StdPQ},
    {ReplayMode::Indexed, MergeKernel::BinHeap},
    {ReplayMode::Indexed, MergeKernel::Quad},
    {ReplayMode::Indexed, MergeKernel::Loser},
    {ReplayMode::Auto, MergeKernel::StdPQ},
    {ReplayMode::Auto, MergeKernel::BinHeap},
    {ReplayMode::Auto, MergeKernel::Quad},
    {ReplayMode::Auto, MergeKernel::Loser}}};
EngineConfig config(std::size_t capacity = 1024) {
  EngineConfig c;
  c.ring_bytes = capacity;
  c.max_record_bytes = capacity / 2;
  c.index.blocks = static_cast<std::uint32_t>(capacity / 16 + 128);
  c.index.entries_per_block = 2;
  c.index.sweep_evictions = 3;
  c.auto_max_partitions = 65535;
  c.auto_max_index_fraction = 1;
  return c;
}
std::vector<std::byte> payload(std::size_t size = 8) {
  return std::vector<std::byte>(size, std::byte{19});
}
SubscriptionSpec spec() {
  return {{{Term::Subtree, "itch/A/add"}, {Term::Exact, "itch/A/add"},
           {Term::Subtree, "itch/B"}, {Term::Exact, "itch/C/cancel"}}};
}
void compare(Engine &engine, Replay &actual, ref::OracleReplay &expected,
             std::size_t budget) {
  std::vector<Delivered> out;
  std::vector<ref::OracleRecord> reference;
  EXPECT_EQ(actual.next_batch(budget, out), expected.next_batch(budget, reference));
  EXPECT_EQ(actual.status(), expected.status());
  EXPECT_EQ(actual.error(), expected.error());
  EXPECT_EQ(actual.checkpoint(), expected.checkpoint());
  EXPECT_EQ(actual.upper_seq(), expected.upper_seq());
  EXPECT_EQ(actual.upper_pos(), expected.upper_pos());
  ASSERT_EQ(out.size(), reference.size());
  for (std::size_t i = 0; i < out.size(); ++i) {
    EXPECT_EQ(out[i].seq, reference[i].seq);
    EXPECT_EQ(out[i].pos, reference[i].pos);
    EXPECT_EQ(engine.registry().get(out[i].topic).path, reference[i].path);
    EXPECT_TRUE(std::ranges::equal(out[i].payload, reference[i].payload));
  }
}
TEST(EngineMerge, V21FourKernelsAndAutoEqualIndependentOracle) {
  for (const auto choice : choices) {
    Engine e(config(8192));
    ref::ScanOracle oracle({8192, 4096});
    const auto subscription = spec();
    const auto sub = e.compile(subscription);
    for (unsigned i = 0; i < 90; ++i) {
      const std::string name = i % 4 == 0 ? "itch/A/add/anon" :
          i % 4 == 1 ? "itch/B/delete" :
          i % 4 == 2 ? "itch/C/cancel" : "itch/A/ignore";
      const auto data = payload(i % 20);
      EXPECT_EQ(e.publish(e.intern(name), data), oracle.publish(name, data));
    }
    auto actual = e.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    auto expected = oracle.open_replay(subscription, 0);
    EXPECT_EQ(actual.effective_mode(), choice.mode == ReplayMode::Scan
                                              ? ReplayMode::Scan
                                              : ReplayMode::Indexed);
    if (choice.mode != ReplayMode::Scan) {
      EXPECT_EQ(actual.selected_partition_count(), 3U);
    }
    for (unsigned i = 0; i < 200 && actual.status() == Status::More; ++i)
      compare(e, actual, expected, i % 7);
    EXPECT_EQ(actual.status(), Status::Done);
    compare(e, actual, expected, 0);
    e.check_invariants();
  }
}
TEST(EngineMerge, V23InterleavedPublicationPreservesUpperAndErrorPrefix) {
  for (const auto choice : choices) {
    Engine e(config(128));
    ref::ScanOracle oracle({128, 64});
    const auto subscription = spec();
    const auto sub = e.compile(subscription);
    for (unsigned i = 0; i < 3; ++i) {
      const std::string name = i % 2 ? "itch/A/add" : "itch/B/add";
      e.publish(e.intern(name), payload(8));
      oracle.publish(name, payload(8));
    }
    auto actual = e.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    auto expected = oracle.open_replay(subscription, 0);
    compare(e, actual, expected, 1);
    for (unsigned i = 0; i < 9; ++i) {
      const std::string name = i % 2 ? "itch/B/later" : "itch/C/cancel";
      e.publish(e.intern(name), payload(8));
      oracle.publish(name, payload(8));
      e.check_invariants();
    }
    compare(e, actual, expected, 0);
    compare(e, actual, expected, 2);
    EXPECT_EQ(actual.status(), Status::Error);
    EXPECT_EQ(actual.error()->kind, ReplayError::FellBehind);
    EXPECT_EQ(actual.error()->last_delivered, 1U);
  }
}
TEST(EngineMerge, V35AllModesConservativeIrrelevantExpiry) {
  for (const auto choice : choices) {
    Engine e(config(64));
    const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
    e.publish(a, payload(16));
    e.publish(b, payload(16));
    auto r = e.open_replay(e.compile({{{Term::Exact, "itch/B/add"}}}), Seq{0},
                            choice.mode, choice.kernel);
    e.publish(b, payload(16));
    const auto checkpoint = r.checkpoint();
    std::vector<Delivered> out;
    EXPECT_EQ(r.next_batch(0, out), Status::More);
    EXPECT_EQ(r.checkpoint(), checkpoint);
    EXPECT_EQ(r.next_batch(1, out), Status::Error);
    EXPECT_TRUE(out.empty());
    EXPECT_EQ(r.error(), (ReplayError{ReplayError::FellBehind, 0, 0, 2}));
  }
}
TEST(EngineMerge, V35FullBudgetAvoidsLookaheadAndFinalExpiry) {
  for (const auto choice : choices) {
    Engine e(config(64));
    const auto a = e.intern("itch/A/add");
    e.publish(a, payload(16));
    auto r = e.open_replay(e.compile({{{Term::Exact, "itch/A/add"}}}), Seq{0},
                            choice.mode, choice.kernel);
    std::vector<Delivered> out;
    EXPECT_EQ(r.next_batch(1, out), Status::More);
    EXPECT_EQ(r.checkpoint(), (ResumeCheckpoint{1, 32}));
    for (unsigned i = 0; i < 5; ++i)
      e.publish(a, payload(16));
    EXPECT_EQ(r.next_batch(0, out), Status::More);
    EXPECT_EQ(r.next_batch(1, out), Status::Done);
    EXPECT_FALSE(r.error());
    EXPECT_EQ(r.checkpoint(), (ResumeCheckpoint{1, 32}));
  }
}
TEST(EngineMerge, V23GrowingFiltersBetweenBatchesRemainSafe) {
  for (const auto choice : choices) {
    Engine e(config(8192));
    const auto sub = e.compile(spec());
    const auto a = e.intern("itch/A/add/a"), b = e.intern("itch/B/add");
    e.publish(a, payload());
    e.publish(b, payload());
    e.publish(a, payload());
    auto r = e.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> out;
    EXPECT_EQ(r.next_batch(1, out), Status::More);
    for (unsigned i = 0; i < 100; ++i)
      static_cast<void>(e.intern("itch/A/add/new" + std::to_string(i)));
    e.publish(e.intern("itch/C/cancel"), payload());
    EXPECT_EQ(r.next_batch(100, out), Status::Done);
    ASSERT_EQ(out.size(), 2U);
    EXPECT_EQ(out[0].seq, 2U);
    EXPECT_EQ(out[1].seq, 3U);
  }
}
TEST(EngineMerge, V23WideTermsAlwaysUseScan) {
  for (const auto choice : choices) {
    Engine e(config());
    const auto t = e.intern("itch/A/add");
    e.publish(t, payload());
    auto r = e.open_replay(e.compile({{{Term::Subtree, "itch"}}}), Seq{0},
                            choice.mode, choice.kernel);
    EXPECT_EQ(r.effective_mode(), ReplayMode::Scan);
    std::vector<Delivered> out;
    EXPECT_EQ(r.next_batch(8, out), Status::Done);
    EXPECT_EQ(out.size(), 1U);
  }
}
TEST(EngineMerge, V38EmptyActiveCursorsAndUnevenExhaustion) {
  for (const auto choice : choices) {
    Engine e(config());
    const auto b = e.intern("itch/B/add");
    const auto sub = e.compile({{{Term::Exact, "itch/A/add"},
                                 {Term::Exact, "itch/B/add"},
                                 {Term::Exact, "itch/C/add"}}});
    for (unsigned i = 0; i < 6; ++i)
      e.publish(b, payload());
    auto r = e.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> out;
    EXPECT_EQ(r.next_batch(20, out), Status::Done);
    ASSERT_EQ(out.size(), 6U);
    for (std::size_t i = 0; i < out.size(); ++i)
      EXPECT_EQ(out[i].seq, i + 1);
    auto empty = e.open_replay(e.compile({{{Term::Exact, "itch/Z/add"}}}),
                                Seq{0}, choice.mode, choice.kernel);
    EXPECT_EQ(empty.next_batch(20, out), Status::Done);
    EXPECT_TRUE(out.empty());
    EXPECT_EQ(empty.checkpoint(), (ResumeCheckpoint{6, 144}));
  }
}
TEST(EngineMerge, V38LargeNonPowerOfTwoCursorSet) {
  for (const auto kernel : {MergeKernel::StdPQ, MergeKernel::BinHeap,
                            MergeKernel::Quad, MergeKernel::Loser}) {
    Engine e(config(8192));
    SubscriptionSpec subscription;
    for (unsigned i = 0; i < 129; ++i) {
      const auto name = "itch/S" + std::to_string(i) + "/add";
      subscription.terms.push_back({Term::Exact, name});
      e.publish(e.intern(name), payload(0));
    }
    auto r = e.open_replay(e.compile(subscription), Seq{0}, ReplayMode::Indexed,
                            kernel);
    EXPECT_EQ(r.selected_partition_count(), 129U);
    std::vector<Delivered> out;
    EXPECT_EQ(r.next_batch(200, out), Status::Done);
    ASSERT_EQ(out.size(), 129U);
    for (std::size_t i = 0; i < out.size(); ++i)
      EXPECT_EQ(out[i].seq, i + 1);
    e.check_invariants();
  }
}
TEST(EngineMerge, AutoPoliciesAreExplicitValidatedAndUncalibrated) {
  auto c = config();
  c.auto_max_index_fraction = 0.5;
  c.auto_max_partitions = 2;
  Engine e(c);
  const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
  for (unsigned i = 0; i < 8; ++i)
    e.publish(b, payload(0));
  e.publish(a, payload(0));
  const auto asub = e.compile({{{Term::Exact, "itch/A/add"}}});
  auto sparse = e.open_replay(asub, Seq{0}, ReplayMode::Auto);
  EXPECT_EQ(sparse.effective_mode(), ReplayMode::Indexed);
  auto dense = e.open_replay(e.compile({{{Term::Subtree, "itch/B"}}}), Seq{0},
                              ReplayMode::Auto);
  EXPECT_EQ(dense.effective_mode(), ReplayMode::Scan);
  auto many = e.open_replay(e.compile({{{Term::Exact, "itch/A/add"},
                                        {Term::Exact, "itch/B/add"},
                                        {Term::Exact, "itch/C/add"}}}), Seq{0},
                             ReplayMode::Auto);
  EXPECT_EQ(many.effective_mode(), ReplayMode::Scan);
  EXPECT_DOUBLE_EQ(e.config().auto_max_index_fraction, 0.5);
  EXPECT_EQ(e.config().auto_max_partitions, 2U);
  for (const auto bad : {-0.01, 1.01, std::numeric_limits<double>::infinity(),
                         std::numeric_limits<double>::quiet_NaN()}) {
    c.auto_max_index_fraction = bad;
    EXPECT_THROW(Engine invalid(c), std::invalid_argument);
  }
  c.auto_max_index_fraction = 1;
  c.auto_max_partitions = 65536;
  EXPECT_THROW(Engine invalid(c), std::invalid_argument);
}
TEST(EngineMerge, AutoWithDisabledIndexFallsBackToScan) {
  auto c = config();
  c.index_enabled = false;
  Engine e(c);
  const auto a = e.intern("itch/A/add");
  e.publish(a, payload());
  auto r = e.open_replay(e.compile({{{Term::Exact, "itch/A/add"}}}), Seq{0},
                          ReplayMode::Auto);
  EXPECT_EQ(r.effective_mode(), ReplayMode::Scan);
  std::vector<Delivered> out;
  EXPECT_EQ(r.next_batch(8, out), Status::Done);
  ASSERT_EQ(out.size(), 1U);
}
TEST(EngineMerge, V38PackedPositionAndIDLimitsDoNotMutateEngine) {
  auto c = config(64);
  c.position_limit = 128;
  Engine e(c);
  const auto a = e.intern("itch/A/add");
  for (unsigned i = 0; i < 3; ++i)
    e.publish(a, payload(16));
  const auto before = e.stats();
  EXPECT_THROW(e.publish(a, payload(16)), std::overflow_error);
  EXPECT_EQ(e.stats().head_pos, before.head_pos);
  EXPECT_EQ(e.stats().tail_pos, before.tail_pos);
  EXPECT_EQ(e.stats().head_seq, before.head_seq);
  EXPECT_EQ(merge::pack((LogPos{1} << 51) - 8, 65534), UINT64_MAX - 1);
  EXPECT_THROW(static_cast<void>(merge::pack(LogPos{1} << 51, 0)),
               std::invalid_argument);
  EXPECT_THROW(static_cast<void>(merge::pack(0, 65535, 65536)),
               std::invalid_argument);
  EXPECT_THROW(static_cast<void>(merge::position(merge::sentinel)),
               std::invalid_argument);
  e.check_invariants();
}
TEST(EngineMerge, V18RecycledDeliveredBlockIsReseekedForEveryKernel) {
  for (const auto choice : choices) {
    auto c = config(64);
    c.index.entries_per_block = 1;
    Engine e(c);
    const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
    e.publish(a, payload(16));
    e.publish(b, payload(16));
    const auto sub = e.compile({{{Term::Exact, "itch/A/add"},
                                 {Term::Exact, "itch/B/add"}}});
    auto r = e.open_replay(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> out;
    ASSERT_EQ(r.next_batch(1, out), Status::More);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 1U);
    EXPECT_EQ(r.checkpoint(), (ResumeCheckpoint{1, 32}));
    e.publish(a, payload(16)); // The delivered first posting's block is freed.
    EXPECT_EQ(e.stats().tail_pos, 32U);
    EXPECT_GT(e.index()->stats().counters.frees, 0U);
    ASSERT_EQ(r.next_batch(1, out), Status::More);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
    EXPECT_EQ(r.next_batch(1, out), Status::Done);
    EXPECT_TRUE(out.empty()); // seq3 belongs to a later captured range.
    e.check_invariants();
  }
}
TEST(EngineTail, V14RearmsExhaustedAndInitiallyEmptyPartitions) {
  for (const auto choice : choices) {
    Engine e(config());
    const auto sub = e.compile({{{Term::Subtree, "itch/A"},
                                 {Term::Subtree, "itch/B"},
                                 {Term::Exact, "itch/C/add"}}});
    auto tail = e.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
    e.publish(a, payload());
    e.publish(b, payload());
    std::vector<Delivered> out;
    EXPECT_EQ(tail.poll(8, out), Status::Done);
    ASSERT_EQ(out.size(), 2U);
    EXPECT_EQ(out[0].seq, 1U);
    EXPECT_EQ(out[1].seq, 2U);
    e.publish(b, payload());
    e.publish(e.intern("itch/A/new/deep"), payload());
    e.publish(e.intern("itch/C/add"), payload());
    EXPECT_EQ(tail.poll(8, out), Status::Done);
    ASSERT_EQ(out.size(), 3U);
    for (std::size_t i = 0; i < out.size(); ++i)
      EXPECT_EQ(out[i].seq, i + 3); // Equal payload values remain distinct events.
    EXPECT_EQ(tail.checkpoint(), (ResumeCheckpoint{5, 120}));
    EXPECT_EQ(tail.poll(8, out), Status::Done);
    EXPECT_TRUE(out.empty());
  }
}
TEST(EngineTail, V24WideHookIncludesNewMatchingPartitions) {
  for (const auto choice : choices) {
    Engine e(config());
    auto tail = e.open_tail(e.compile({{{Term::Subtree, "itch"}}}), Seq{0},
                            choice.mode, choice.kernel);
    std::vector<Delivered> out;
    e.publish(e.intern("itch/A/add"), payload(0));
    EXPECT_EQ(tail.poll(8, out), Status::Done);
    ASSERT_EQ(out.size(), 1U);
    e.publish(e.intern("itch/brand_new_partition/add"), payload(0));
    EXPECT_EQ(tail.poll(8, out), Status::Done);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
    EXPECT_EQ(tail.effective_mode(), ReplayMode::Scan);
  }
}
TEST(EngineTail, V35ZeroBudgetDoesNotCaptureOrChangeProgress) {
  for (const auto choice : choices) {
    Engine e(config());
    const auto sub = e.compile({{{Term::Exact, "itch/A/add"}}});
    auto tail = e.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    const auto original = tail.checkpoint();
    e.publish(e.intern("itch/A/add"), payload());
    std::vector<Delivered> out{{999, 999, 0, {}}};
    EXPECT_EQ(tail.poll(0, out), Status::Done);
    EXPECT_TRUE(out.empty());
    EXPECT_EQ(tail.checkpoint(), original);
    EXPECT_EQ(tail.upper_seq(), 0U);
    EXPECT_EQ(tail.upper_pos(), 0U);
    EXPECT_EQ(tail.poll(1, out), Status::More);
    ASSERT_EQ(out.size(), 1U);
    const auto consumed = tail.checkpoint();
    e.publish(e.intern("itch/A/add"), payload());
    EXPECT_EQ(tail.poll(0, out), Status::More);
    EXPECT_TRUE(out.empty());
    EXPECT_EQ(tail.checkpoint(), consumed);
    EXPECT_EQ(tail.upper_seq(), 1U);
    EXPECT_EQ(tail.poll(8, out), Status::Done);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
  }
}
TEST(EngineTail, V14OldRangeFinishesBeforeFreshRangeWithOneSharedBudget) {
  for (const auto choice : choices) {
    Engine e(config());
    const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
    const auto sub = e.compile({{{Term::Exact, "itch/A/add"},
                                 {Term::Exact, "itch/B/add"}}});
    e.publish(a, payload());
    e.publish(b, payload());
    auto tail = e.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> out;
    ASSERT_EQ(tail.poll(1, out), Status::More);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 1U);
    e.publish(b, payload());
    e.publish(a, payload());
    ASSERT_EQ(tail.poll(3, out), Status::More);
    ASSERT_EQ(out.size(), 3U);
    for (std::size_t i = 0; i < out.size(); ++i)
      EXPECT_EQ(out[i].seq, i + 2);
    EXPECT_EQ(tail.upper_seq(), 4U);
    EXPECT_EQ(tail.checkpoint(), (ResumeCheckpoint{4, 96}));
    EXPECT_EQ(tail.poll(8, out), Status::Done);
    EXPECT_TRUE(out.empty());
  }
}
TEST(EngineTail, V35ZeroOutputCompletionUsesRangeUpperAndGlobalFailureFields) {
  for (const auto choice : choices) {
    Engine e(config(64));
    const auto a = e.intern("itch/A/add"), b = e.intern("itch/B/add");
    const auto sub = e.compile({{{Term::Exact, "itch/A/add"}}});
    e.publish(b, payload(8));
    auto tail = e.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    std::vector<Delivered> out;
    EXPECT_EQ(tail.poll(8, out), Status::Done);
    EXPECT_TRUE(out.empty());
    EXPECT_EQ(tail.checkpoint(), (ResumeCheckpoint{1, 24}));
    e.publish(a, payload(8));
    ASSERT_EQ(tail.poll(1, out), Status::More);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
    for (unsigned i = 0; i < 8; ++i)
      e.publish(b, payload(8));
    const auto consumed = tail.checkpoint();
    EXPECT_EQ(tail.poll(0, out), Status::More);
    EXPECT_EQ(tail.checkpoint(), consumed);
    EXPECT_EQ(tail.poll(8, out), Status::Error);
    EXPECT_TRUE(out.empty());
    EXPECT_EQ(tail.error(), (ReplayError{ReplayError::FellBehind, 0, 2,
                                        e.stats().tail_seq}));
    const auto terminal = tail.error();
    e.publish(a, payload());
    EXPECT_EQ(tail.poll(8, out), Status::Error);
    EXPECT_TRUE(out.empty());
    EXPECT_EQ(tail.error(), terminal);
  }
}
TEST(EngineTail, V35CompletedPadCheckpointMayExpireWithAllNewDataRetained) {
  for (const auto choice : choices) {
    Engine e(config(64));
    const auto a = e.intern("itch/A/add");
    const auto sub = e.compile({{{Term::Exact, "itch/A/add"}}});
    e.publish(a, payload(10));
    e.publish(a, payload(4));
    auto tail = e.open_tail(sub, Seq{2}, choice.mode, choice.kernel);
    EXPECT_EQ(tail.checkpoint(), (ResumeCheckpoint{2, 56}));
    e.publish(a, payload(0));
    e.publish(a, payload(10));
    e.publish(a, payload(0));
    ASSERT_EQ(e.stats().head_pos, 128U);
    ASSERT_EQ(e.stats().tail_pos, 64U);
    ASSERT_EQ(e.stats().tail_seq, 3U);
    std::vector<Delivered> out;
    EXPECT_EQ(tail.poll(8, out), Status::Done);
    EXPECT_FALSE(tail.error());
    ASSERT_EQ(out.size(), 3U);
    for (std::size_t i = 0; i < out.size(); ++i)
      EXPECT_EQ(out[i].seq, i + 3);
    EXPECT_EQ(tail.checkpoint(), (ResumeCheckpoint{5, 128}));
  }
}
TEST(EngineTail, V35InitialExpiryAndFutureTailInputsRemainDistinct) {
  for (const auto choice : choices) {
    Engine e(config(64));
    const auto a = e.intern("itch/A/add");
    const auto sub = e.compile({{{Term::Exact, "itch/A/add"}}});
    EXPECT_THROW(static_cast<void>(e.open_tail(sub, Seq{1}, choice.mode,
                                              choice.kernel)), InvalidRange);
    EXPECT_THROW(static_cast<void>(e.open_tail(sub, UINT64_MAX, choice.mode,
                                              choice.kernel)), InvalidRange);
    for (unsigned i = 0; i < 4; ++i)
      e.publish(a, payload(16));
    auto expired = e.open_tail(sub, Seq{0}, choice.mode, choice.kernel);
    EXPECT_EQ(expired.status(), Status::Error);
    EXPECT_EQ(expired.error(), (ReplayError{ReplayError::HistoryExpired, 0, 0, 3}));
    std::vector<Delivered> out;
    EXPECT_EQ(expired.poll(1, out), Status::Error);
    EXPECT_TRUE(out.empty());
    auto future = e.open_replay(sub, UINT64_MAX, choice.mode, choice.kernel);
    EXPECT_EQ(future.status(), Status::Done);
    EXPECT_FALSE(future.checkpoint());
    auto caught_up = e.open_tail(sub, Seq{4}, choice.mode, choice.kernel);
    for (unsigned i = 0; i < 3; ++i) {
      EXPECT_EQ(caught_up.poll(1, out), Status::Done);
      EXPECT_TRUE(out.empty());
      EXPECT_EQ(caught_up.checkpoint(), (ResumeCheckpoint{4, 128}));
    }
  }
}
TEST(EngineTail, MoveTransfersSingleActiveRangeAndRejectsMovedFromPoll) {
  Engine e(config());
  const auto a = e.intern("itch/A/add");
  const auto sub = e.compile({{{Term::Exact, "itch/A/add"}}});
  e.publish(a, payload());
  auto original = e.open_tail(sub, Seq{0}, ReplayMode::Indexed, MergeKernel::Loser);
  auto moved = std::move(original);
  std::vector<Delivered> out;
  EXPECT_THROW(original.poll(1, out), std::logic_error);
  EXPECT_EQ(moved.poll(8, out), Status::Done);
  ASSERT_EQ(out.size(), 1U);
  auto assigned = e.open_tail(sub, Seq{1});
  assigned = std::move(moved);
  EXPECT_THROW(moved.poll(1, out), std::logic_error);
  e.publish(a, payload());
  EXPECT_EQ(assigned.poll(8, out), Status::Done);
  ASSERT_EQ(out.size(), 1U);
  EXPECT_EQ(out[0].seq, 2U);
}
} // namespace
} // namespace tiplog
