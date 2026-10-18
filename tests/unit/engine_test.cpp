#include "scan_oracle.hpp"
#include "tiplog/engine/engine.hpp"

#include <algorithm>
#include <array>
#include <gtest/gtest.h>
#include <limits>
#include <memory>
#include <optional>

namespace tiplog {
namespace {
SubscriptionSpec exact(std::string path) {
  return {{{Term::Exact, std::move(path)}}};
}
SubscriptionSpec subtree(std::string path) {
  return {{{Term::Subtree, std::move(path)}}};
}
std::vector<std::byte> payload(std::size_t size, unsigned char value = 7) {
  return std::vector<std::byte>(size, static_cast<std::byte>(value));
}
TEST(Engine, V12EmptyAndExtremeFutureRanges) {
  Engine engine({64, 32});
  const auto sub = engine.compile(subtree("itch"));
  auto at_head = engine.open_replay(sub, Seq{0});
  EXPECT_EQ(at_head.status(), Status::Done);
  EXPECT_EQ(at_head.checkpoint(), (ResumeCheckpoint{0, 0}));
  auto future = engine.open_replay(sub, std::numeric_limits<Seq>::max());
  EXPECT_EQ(future.status(), Status::Done);
  EXPECT_FALSE(future.checkpoint());
  std::vector<Delivered> out{{1, 0, 0, {}}};
  EXPECT_EQ(future.next_batch(0, out), Status::Done);
  EXPECT_TRUE(out.empty());
}
TEST(Engine, V12EmptySpecRejectedAndNonexistentExactMatchesNothing) {
  Engine engine;
  EXPECT_THROW(static_cast<void>(engine.compile({})), std::invalid_argument);
  const auto topic = engine.intern("itch/AAPL/add");
  engine.publish(topic, payload(8));
  auto replay =
      engine.open_replay(engine.compile(exact("missing/topic")), Seq{0});
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(3, out), Status::Done);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 24}));
}
TEST(Engine, V12OverlapUnionDistinctEqualEventsAndFutureTopicHook) {
  Engine engine;
  const auto sub = engine.compile({{{Term::Subtree, "itch/AAPL"},
                                    {Term::Exact, "itch/AAPL/add"},
                                    {Term::Subtree, "itch/AAPL/add"}}});
  const auto topic = engine.intern("itch/AAPL/add/anon");
  engine.publish(topic, payload(4));
  engine.publish(topic, payload(4));
  const auto other = engine.intern("itch/AAPLX/add");
  engine.publish(other, payload(4));
  auto replay = engine.open_replay(sub, Seq{0});
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(8, out), Status::Done);
  ASSERT_EQ(out.size(), 2U);
  EXPECT_EQ(out[0].seq, 1U);
  EXPECT_EQ(out[1].seq, 2U);
  EXPECT_EQ(out[0].payload.size(), 4U);
  EXPECT_TRUE(std::ranges::equal(out[0].payload, out[1].payload));
}
TEST(Engine, V13HistoryExpiredFieldsAndTerminalStability) {
  Engine engine({64, 32});
  const auto topic = engine.intern("itch/A/add");
  const auto sub = engine.compile(subtree("itch"));
  for (int i = 0; i < 4; ++i)
    engine.publish(topic, payload(16));
  auto replay = engine.open_replay(sub, Seq{0});
  EXPECT_EQ(replay.status(), Status::Error);
  EXPECT_EQ(replay.error(),
            (ReplayError{ReplayError::HistoryExpired, 0, 0, 3}));
  EXPECT_FALSE(replay.checkpoint());
  std::vector<Delivered> out;
  engine.publish(topic, payload(16));
  EXPECT_EQ(replay.next_batch(10, out), Status::Error);
  EXPECT_EQ(replay.error()->oldest_retained, 3U);
}
TEST(Engine, V13FellBehindPreservesCorrectDeliveredPrefixAndRequestedFloor) {
  Engine engine({128, 64});
  const auto topic = engine.intern("itch/A/add");
  const auto sub = engine.compile(subtree("itch"));
  for (int i = 0; i < 4; ++i)
    engine.publish(topic, payload(8));
  auto replay = engine.open_replay(sub, Seq{0});
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  ASSERT_EQ(out.size(), 1U);
  EXPECT_EQ(out[0].seq, 1U);
  for (int i = 0; i < 6; ++i)
    engine.publish(topic, payload(8));
  const auto checkpoint = replay.checkpoint();
  EXPECT_EQ(replay.next_batch(0, out), Status::More);
  EXPECT_EQ(replay.checkpoint(), checkpoint);
  EXPECT_EQ(replay.next_batch(1, out), Status::Error);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(replay.error(), (ReplayError{ReplayError::FellBehind, 0, 1,
                                         engine.stats().tail_seq}));
}
TEST(Engine, V35IrrelevantRecordExpiryIsConservative) {
  Engine engine({64, 32});
  const auto a = engine.intern("itch/A/add"), b = engine.intern("itch/B/add");
  engine.publish(a, payload(16));
  engine.publish(b, payload(16));
  auto replay = engine.open_replay(engine.compile(exact("itch/B/add")), Seq{0});
  engine.publish(b, payload(16)); // only irrelevant seq1 expired
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(0, out), Status::More);
  EXPECT_EQ(replay.next_batch(1, out), Status::Error);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(replay.error(), (ReplayError{ReplayError::FellBehind, 0, 0, 2}));
}
TEST(Engine, V35ExactFinalBudgetCompletesBeforeExpiry) {
  Engine engine({64, 32});
  const auto topic = engine.intern("itch/A/add");
  engine.publish(topic, payload(16));
  auto replay = engine.open_replay(engine.compile(subtree("itch")), Seq{0});
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 32}));
  for (int i = 0; i < 4; ++i)
    engine.publish(topic, payload(16));
  EXPECT_EQ(replay.next_batch(0, out), Status::More);
  EXPECT_EQ(replay.next_batch(1, out), Status::Done);
  EXPECT_FALSE(replay.error());
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 32}));
}
TEST(Engine, V35FullBudgetDoesNotLookPastLongFilteredGap) {
  Engine engine({1024, 512});
  const auto a = engine.intern("itch/A/add"), b = engine.intern("itch/B/add");
  engine.publish(a, payload(0));
  for (int i = 0; i < 20; ++i)
    engine.publish(b, payload(0));
  auto replay = engine.open_replay(engine.compile(exact("itch/A/add")), Seq{0});
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 16}));
  EXPECT_EQ(replay.next_batch(1, out), Status::Done);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{21, 336}));
}
TEST(Engine, V14CapturedUpperExcludesLaterPublish) {
  Engine engine;
  const auto topic = engine.intern("itch/A/add");
  const auto sub = engine.compile(subtree("itch"));
  engine.publish(topic, payload(8));
  auto replay = engine.open_replay(sub, Seq{0});
  engine.publish(topic, payload(8));
  std::vector<Delivered> out;
  EXPECT_EQ(replay.upper_seq(), 1U);
  EXPECT_EQ(replay.upper_pos(), 24U);
  EXPECT_EQ(replay.next_batch(8, out), Status::Done);
  ASSERT_EQ(out.size(), 1U);
  EXPECT_EQ(out[0].seq, 1U);
}
TEST(Engine, V14ZeroOutputSnapshotAdvancesChain) {
  Engine engine;
  const auto a = engine.intern("itch/A/add"), b = engine.intern("itch/B/add");
  const auto sub = engine.compile(exact("itch/A/add"));
  engine.publish(b, payload(8));
  auto first = engine.open_replay(sub, Seq{0});
  std::vector<Delivered> out;
  EXPECT_EQ(first.next_batch(8, out), Status::Done);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(first.checkpoint(), (ResumeCheckpoint{1, 24}));
  engine.publish(a, payload(8));
  auto second = engine.open_replay(sub, *first.checkpoint());
  EXPECT_EQ(second.next_batch(8, out), Status::Done);
  ASSERT_EQ(out.size(), 1U);
  EXPECT_EQ(out[0].seq, 2U);
}
TEST(Engine, V14ChainedRangesEqualSingleRange) {
  Engine engine({4096, 2048});
  const auto a = engine.intern("itch/A/add"), b = engine.intern("itch/B/add");
  const auto sub = engine.compile(exact("itch/A/add"));
  Seq after = 0;
  std::vector<Seq> chained;
  std::vector<Delivered> out;
  for (int round = 0; round < 20; ++round) {
    engine.publish(b, payload(8));
    engine.publish(a, payload(8));
    auto replay = engine.open_replay(sub, after);
    while (replay.next_batch(1, out) == Status::More) {
      for (const auto &r : out)
        chained.push_back(r.seq);
    }
    for (const auto &r : out)
      chained.push_back(r.seq);
    after = replay.checkpoint()->after_seq;
  }
  auto all = engine.open_replay(sub, Seq{0});
  EXPECT_EQ(all.next_batch(100, out), Status::Done);
  ASSERT_EQ(out.size(), chained.size());
  for (std::size_t i = 0; i < out.size(); ++i)
    EXPECT_EQ(out[i].seq, chained[i]);
}
TEST(Engine, V36PadCheckpointAndSequenceSeekHaveExplicitBoundaries) {
  Engine engine({64, 32});
  const auto topic = engine.intern("itch/A/add");
  const auto sub = engine.compile(subtree("itch"));
  engine.publish(topic, payload(10));
  engine.publish(topic, payload(4));
  auto old = engine.open_replay(sub, Seq{1});
  std::vector<Delivered> out;
  EXPECT_EQ(old.next_batch(1, out), Status::More);
  EXPECT_EQ(old.checkpoint(), (ResumeCheckpoint{2, 56}));
  engine.publish(topic, payload(8));
  auto checkpoint = engine.open_replay(sub, *old.checkpoint());
  auto sequence = engine.open_replay(sub, Seq{2});
  EXPECT_EQ(checkpoint.checkpoint(), (ResumeCheckpoint{2, 56}));
  EXPECT_EQ(sequence.checkpoint(), (ResumeCheckpoint{2, 64}));
  EXPECT_EQ(checkpoint.next_batch(8, out), Status::Done);
  ASSERT_EQ(out.size(), 1U);
  EXPECT_EQ(out[0].seq, 3U);
}
TEST(Engine, V36RetainedTailPadCheckpointSurvivesPrecedingDataExpiry) {
  Engine engine({64, 32});
  const auto topic = engine.intern("itch/A/add");
  const auto sub = engine.compile(subtree("itch"));
  engine.publish(topic, payload(10));
  engine.publish(topic, payload(4));
  engine.publish(topic, payload(8));
  engine.publish(topic, payload(0));
  ASSERT_EQ(engine.stats().tail_pos, 56U);
  ASSERT_EQ(engine.stats().tail_seq, 3U);
  auto replay = engine.open_replay(sub, ResumeCheckpoint{2, 56});
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{2, 56}));
  engine.publish(topic,
                 payload(8)); // Expire only the conservative PAD checkpoint.
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::Error);
  EXPECT_EQ(replay.error(), (ReplayError{ReplayError::FellBehind, 2, 2, 3}));
}
TEST(Engine, V36MalformedCheckpointFallsBackToSafeSequenceSeek) {
  Engine engine;
  const auto topic = engine.intern("itch/A/add");
  engine.publish(topic, payload(16));
  engine.publish(topic, payload(16));
  const auto sub = engine.compile(subtree("itch"));
  for (const LogPos pos : std::array<LogPos, 5>{1, 8, 24, 999, UINT64_MAX}) {
    auto replay = engine.open_replay(sub, ResumeCheckpoint{1, pos});
    EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 32}));
    std::vector<Delivered> out;
    EXPECT_EQ(replay.next_batch(10, out), Status::Done);
    ASSERT_EQ(out.size(), 1U);
    EXPECT_EQ(out[0].seq, 2U);
  }
}
TEST(Engine, V36OversizeInvalidTopicAndLifetimeLimitsPreserveState) {
  Engine engine({64, 32, 8, 128, 4});
  const auto topic = engine.intern("itch/A/add");
  engine.publish(topic, payload(16));
  const auto before = engine.stats();
  EXPECT_THROW(engine.publish(topic, payload(17)), std::length_error);
  EXPECT_THROW(engine.publish(0, payload(0)), std::out_of_range);
  EXPECT_THROW(engine.publish(UINT32_MAX, payload(0)), std::out_of_range);
  EXPECT_EQ(engine.stats().head_pos, before.head_pos);
  EXPECT_EQ(engine.stats().tail_pos, before.tail_pos);
  engine.publish(topic, payload(16));
  engine.publish(topic, payload(16));
  const auto near = engine.stats();
  EXPECT_THROW(engine.publish(topic, payload(16)), std::overflow_error);
  EXPECT_EQ(engine.stats().head_pos, near.head_pos);
  EXPECT_EQ(engine.stats().tail_seq, near.tail_seq);
  engine.check_invariants();
}
TEST(Engine, V36InvalidConfigAndForeignSubscriptionsRejected) {
  EXPECT_THROW(Engine(EngineConfig{64, 48}), std::invalid_argument);
  Engine a, b;
  const auto sub = a.compile(subtree("itch"));
  EXPECT_THROW(static_cast<void>(b.open_replay(sub, Seq{0})),
               std::invalid_argument);
  auto wide = a.open_replay(sub, Seq{0}, ReplayMode::Indexed);
  EXPECT_EQ(wide.effective_mode(), ReplayMode::Scan);
  EXPECT_EQ(wide.status(), Status::Done);
  EXPECT_THROW(static_cast<void>(a.open_replay(sub, Seq{0}, ReplayMode::Auto)),
               std::invalid_argument);
}
TEST(Engine, ReplayLifetimeAndMoveAreChecked) {
#ifndef NDEBUG
  EXPECT_DEATH(
      {
        auto engine = std::make_unique<Engine>();
        auto live =
            engine->open_replay(engine->compile(subtree("itch")), Seq{0});
        engine.reset();
      },
      "Replay must be closed");
#else
  std::optional<Replay> replay;
  {
    auto engine = std::make_unique<Engine>();
    const auto sub = engine->compile(subtree("itch"));
    const auto topic = engine->intern("itch/A/add");
    engine->publish(topic, payload(8));
    replay.emplace(engine->open_replay(sub, Seq{0}));
  }
  std::vector<Delivered> stale_out;
  EXPECT_THROW(replay->next_batch(1, stale_out), std::logic_error);
#endif
  std::vector<Delivered> out;
  Engine engine;
  const auto topic = engine.intern("itch/A/add");
  engine.publish(topic, payload(8));
  auto initial = engine.open_replay(engine.compile(subtree("itch")), Seq{0});
  auto moved = std::move(initial);
  EXPECT_THROW(initial.next_batch(1, out), std::logic_error);
  EXPECT_EQ(moved.next_batch(8, out), Status::Done);
  ASSERT_EQ(out.size(), 1U);
  auto assigned = engine.open_replay(engine.compile(subtree("itch")), Seq{0});
  assigned = std::move(moved);
  EXPECT_EQ(assigned.next_batch(8, out), Status::Done);
}
} // namespace
} // namespace tiplog
