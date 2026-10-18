#include "scan_oracle.hpp"

#include <gtest/gtest.h>

#include <array>
#include <limits>
#include <stdexcept>
#include <vector>

namespace {
using namespace tiplog;
using ref::OracleRecord;
using ref::ScanOracle;

SubscriptionSpec subtree(std::string path) { return {{{Term::Subtree, std::move(path)}}}; }
SubscriptionSpec exact(std::string path) { return {{{Term::Exact, std::move(path)}}}; }
std::vector<std::byte> bytes(std::size_t n) { return std::vector<std::byte>(n, std::byte{42}); }

TEST(OracleRetention, V09HandComputedPadAndWrap) {
  ScanOracle oracle({64, 32});
  EXPECT_EQ(oracle.tail_seq(), 1);
  EXPECT_EQ(oracle.head_seq(), 1);
  EXPECT_EQ(oracle.publish("itch/A/add", bytes(10)), 1);
  EXPECT_EQ(oracle.publish("itch/A/add", bytes(4)), 2);
  EXPECT_EQ(oracle.head_pos(), 56);
  EXPECT_EQ(oracle.tail_pos(), 0);
  EXPECT_EQ(oracle.publish("itch/B/add", bytes(8)), 3);
  EXPECT_EQ(oracle.head_pos(), 88);
  EXPECT_EQ(oracle.tail_pos(), 32);
  EXPECT_EQ(oracle.tail_seq(), 2);
  ASSERT_EQ(oracle.items().size(), 4);
  EXPECT_EQ(oracle.items()[2], (ref::OracleItem{56, 8, std::nullopt}));
  EXPECT_EQ(oracle.publish("itch/A/add", bytes(0)), 4);
  EXPECT_EQ(oracle.head_pos(), 104);
  EXPECT_EQ(oracle.tail_pos(), 56);  // PAD is retained as a whole item.
  EXPECT_EQ(oracle.tail_seq(), 3);
  EXPECT_EQ(oracle.publish("itch/A/add", bytes(8)), 5);
  EXPECT_EQ(oracle.head_pos(), 128);
  EXPECT_EQ(oracle.tail_pos(), 64);
  EXPECT_EQ(oracle.tail_seq(), 3);
  ASSERT_EQ(oracle.full_records().size(), 5);
  EXPECT_EQ(oracle.full_records()[3].size, 16);  // Empty DATA is not an 8-byte PAD.
  const auto retained = oracle.retained_records();
  ASSERT_EQ(retained.size(), 3);
  EXPECT_EQ(retained.front().seq, 3);
  EXPECT_EQ(retained.back().seq, 5);
}

TEST(OracleRetention, V09ExactPhysicalFitHasNoPadAndWholeRecordEviction) {
  ScanOracle oracle({64, 32});
  for (unsigned i = 0; i < 3; ++i) oracle.publish("a/b", bytes(16));
  ASSERT_EQ(oracle.items().size(), 3);
  EXPECT_EQ(oracle.head_pos(), 96);
  EXPECT_EQ(oracle.tail_pos(), 32);
  EXPECT_EQ(oracle.tail_seq(), 2);
  EXPECT_EQ(oracle.retained_records().size(), 2);
  for (const auto& item : oracle.items()) EXPECT_TRUE(item.seq.has_value());
}

TEST(OracleRetention, RejectsInvalidConfigsAndOversizedPublicationWithoutMutation) {
  EXPECT_THROW(ScanOracle({63, 24}), std::invalid_argument);
  EXPECT_THROW(ScanOracle({64, 48}), std::invalid_argument);
  EXPECT_THROW(ScanOracle({64, 8}), std::invalid_argument);
  EXPECT_THROW(ScanOracle({64, 17}), std::invalid_argument);
  ScanOracle oracle({64, 32});
  oracle.publish("a/b", bytes(10));
  const auto old_records = oracle.full_records();
  const auto old_items = oracle.items();
  EXPECT_THROW(oracle.publish("a/b", bytes(17)), std::length_error);
  EXPECT_THROW(oracle.publish("a//b", bytes(0)), std::invalid_argument);
  EXPECT_EQ(oracle.full_records(), old_records);
  EXPECT_EQ(oracle.items(), old_items);
  EXPECT_EQ(oracle.head_pos(), 32);
  EXPECT_EQ(oracle.head_seq(), 2);
  EXPECT_EQ(oracle.tail_pos(), 0);
}

TEST(OracleRetention, RejectsSyntheticLifetimeLimitsBeforeMutation) {
  ScanOracle position({64, 32, 65, 100});
  position.publish("a", bytes(16));
  position.publish("a", bytes(16));
  const auto before = position.full_records();
  EXPECT_THROW(position.publish("a", bytes(0)), std::overflow_error);
  EXPECT_EQ(position.full_records(), before);
  EXPECT_EQ(position.tail_pos(), 0);
  ScanOracle sequence({64, 32, 1000, 3});
  sequence.publish("a", bytes(0));
  sequence.publish("a", bytes(0));
  EXPECT_THROW(sequence.publish("a", bytes(0)), std::overflow_error);
  EXPECT_EQ(sequence.head_seq(), 3);
}

TEST(OracleMatching, IndependentPathBoundaryAndUnion) {
  const SubscriptionSpec spec{{{Term::Subtree, "itch/A"}, {Term::Exact, "itch/A/add"},
                                {Term::Subtree, "itch/A/add"}, {Term::Exact, "other/path"}}};
  EXPECT_TRUE(ScanOracle::matches(spec, "itch/A"));
  EXPECT_TRUE(ScanOracle::matches(spec, "itch/A/add/anon"));
  EXPECT_TRUE(ScanOracle::matches(spec, "other/path"));
  EXPECT_FALSE(ScanOracle::matches(spec, "itch/AB/add"));
  EXPECT_FALSE(ScanOracle::matches(spec, "other/path/child"));
  ScanOracle oracle({128, 64});
  oracle.publish("itch/A/add", bytes(1));
  auto replay = oracle.open_replay(spec, 0);
  std::vector<OracleRecord> out;
  EXPECT_EQ(replay.next_batch(10, out), Status::Done);
  EXPECT_EQ(out.size(), 1);
}

TEST(OracleMatching, InvalidSubscriptionsAreRejectedIndependently) {
  ScanOracle oracle({64, 32});
  EXPECT_THROW((void)oracle.open_replay({}, 0), std::invalid_argument);
  EXPECT_THROW((void)oracle.open_replay(exact("/a"), 0), std::invalid_argument);
  const SubscriptionSpec invalid{{{static_cast<Term::Kind>(99), "a"}}};
  EXPECT_THROW((void)oracle.open_replay(invalid, 0), std::invalid_argument);
}

TEST(OracleReplay, CapturedUpperExcludesLaterPublicationAndCopiesPayload) {
  ScanOracle oracle({128, 64});
  auto payload = bytes(1);
  oracle.publish("a/b", payload);
  oracle.publish("a/b", payload);
  payload[0] = std::byte{99};
  auto replay = oracle.open_replay(subtree("a"), 0);
  oracle.publish("a/b", payload);
  std::vector<OracleRecord> out;
  EXPECT_EQ(replay.next_batch(10, out), Status::Done);
  ASSERT_EQ(out.size(), 2);
  EXPECT_EQ(out.back().seq, 2);
  EXPECT_EQ(out.front().payload[0], std::byte{42});
  EXPECT_EQ(replay.upper_seq(), 2);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{2, 48}));
}

TEST(OracleReplay, HistoryExpiredHasExactFieldsAndStableTerminalState) {
  ScanOracle oracle({64, 32});
  for (unsigned i = 0; i < 4; ++i) oracle.publish("a/b", bytes(16));
  auto replay = oracle.open_replay(subtree("a"), 1);
  EXPECT_EQ(replay.status(), Status::Error);
  EXPECT_EQ(replay.error(), (ReplayError{ReplayError::HistoryExpired, 1, 1, 3}));
  std::vector<OracleRecord> out;
  EXPECT_EQ(replay.next_batch(0, out), Status::Error);
  EXPECT_EQ(replay.next_batch(100, out), Status::Error);
  EXPECT_TRUE(out.empty());
}

TEST(OracleReplay, ConservativeExpiryIncludesIrrelevantRecordsAndZeroBudgetDefersCheck) {
  ScanOracle oracle({64, 32});
  oracle.publish("a/irrelevant", bytes(16));
  oracle.publish("b/match", bytes(16));
  auto replay = oracle.open_replay(subtree("b"), 0);
  const auto checkpoint = replay.checkpoint();
  oracle.publish("a/irrelevant", bytes(16));
  std::vector<OracleRecord> out;
  EXPECT_EQ(replay.next_batch(0, out), Status::More);
  EXPECT_EQ(replay.checkpoint(), checkpoint);
  EXPECT_FALSE(replay.error());
  EXPECT_EQ(replay.next_batch(1, out), Status::Error);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(replay.error(), (ReplayError{ReplayError::FellBehind, 0, 0, 2}));
}

TEST(OracleReplay, ErrorPreservesExactDeliveredPrefixAndLastDelivered) {
  ScanOracle oracle({64, 32});
  oracle.publish("a", bytes(16));
  oracle.publish("a", bytes(16));
  auto replay = oracle.open_replay(exact("a"), 0);
  std::vector<OracleRecord> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  ASSERT_EQ(out.size(), 1);
  EXPECT_EQ(out[0].seq, 1);
  oracle.publish("b", bytes(16));
  oracle.publish("b", bytes(16));
  EXPECT_EQ(replay.next_batch(1, out), Status::Error);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(replay.error(), (ReplayError{ReplayError::FellBehind, 0, 1, 3}));
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 32}));
}

TEST(OracleReplay, ExactFinalBudgetIsDoneBeforeExpiryOnNextPositiveCall) {
  ScanOracle oracle({32, 16});
  oracle.publish("a", bytes(0));
  auto replay = oracle.open_replay(exact("a"), 0);
  std::vector<OracleRecord> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 16}));
  for (unsigned i = 0; i < 4; ++i) oracle.publish("b", bytes(0));
  EXPECT_EQ(replay.next_batch(0, out), Status::More);
  EXPECT_EQ(replay.next_batch(1, out), Status::Done);
  EXPECT_FALSE(replay.error());
  EXPECT_EQ(replay.next_batch(0, out), Status::Done);
}

TEST(OracleReplay, FullBudgetDoesNotLookAheadAcrossFilteredGap) {
  ScanOracle oracle({128, 64});
  oracle.publish("a", bytes(0));
  oracle.publish("b", bytes(0));
  oracle.publish("b", bytes(0));
  auto replay = oracle.open_replay(exact("a"), 0);
  std::vector<OracleRecord> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{1, 16}));
  for (unsigned i = 0; i < 7; ++i) oracle.publish("b", bytes(0));
  EXPECT_EQ(replay.next_batch(1, out), Status::Error);
  EXPECT_EQ(replay.error(), (ReplayError{ReplayError::FellBehind, 0, 1, 3}));
}

TEST(OracleReplay, CompletedZeroOutputSnapshotAdvancesProgressAndChainsFromUpper) {
  ScanOracle oracle({128, 64});
  oracle.publish("b", bytes(0));
  oracle.publish("b", bytes(0));
  auto replay = oracle.open_replay(exact("a"), 0);
  std::vector<OracleRecord> out;
  EXPECT_EQ(replay.next_batch(10, out), Status::Done);
  EXPECT_TRUE(out.empty());
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{2, 32}));
  oracle.publish("a", bytes(0));
  auto next = oracle.open_replay(exact("a"), replay.checkpoint()->after_seq);
  EXPECT_EQ(next.next_batch(10, out), Status::Done);
  ASSERT_EQ(out.size(), 1);
  EXPECT_EQ(out[0].seq, 3);
}

TEST(OracleReplay, EmptyFutureAndExtremeQueriesAvoidOverflow) {
  ScanOracle oracle({64, 32});
  auto empty = oracle.open_replay(exact("a"), 0);
  EXPECT_EQ(empty.status(), Status::Done);
  EXPECT_EQ(empty.checkpoint(), (ResumeCheckpoint{0, 0}));
  oracle.publish("a", bytes(0));
  auto at_head = oracle.open_replay(exact("a"), 1);
  EXPECT_EQ(at_head.status(), Status::Done);
  EXPECT_EQ(at_head.checkpoint(), (ResumeCheckpoint{1, 16}));
  auto future = oracle.open_replay(exact("a"), std::numeric_limits<Seq>::max());
  EXPECT_EQ(future.status(), Status::Done);
  EXPECT_FALSE(future.checkpoint());
  EXPECT_FALSE(future.error());
}

TEST(OracleReplay, SeqOnlyOpenSkipsPadWhileFullBatchCanCheckpointBeforePad) {
  ScanOracle oracle({64, 32});
  oracle.publish("a", bytes(10));
  oracle.publish("a", bytes(4));
  oracle.publish("a", bytes(8));
  auto replay = oracle.open_replay(exact("a"), 2);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{2, 64}));
  std::vector<OracleRecord> out;
  EXPECT_EQ(replay.next_batch(1, out), Status::More);
  EXPECT_EQ(replay.checkpoint(), (ResumeCheckpoint{3, 88}));
}

TEST(OracleReplay, EqualValuedDistinctSequenceEventsSurviveUnion) {
  ScanOracle oracle({128, 64});
  const SubscriptionSpec overlapping{{{Term::Exact, "a/b"}, {Term::Subtree, "a"}}};
  for (unsigned i = 0; i < 3; ++i) oracle.publish("a/b", bytes(1));
  auto replay = oracle.open_replay(overlapping, 0);
  std::vector<OracleRecord> out;
  EXPECT_EQ(replay.next_batch(10, out), Status::Done);
  ASSERT_EQ(out.size(), 3);
  EXPECT_EQ(out[0].seq, 1);
  EXPECT_EQ(out[1].seq, 2);
  EXPECT_EQ(out[2].seq, 3);
  EXPECT_EQ(out[0].payload, out[2].payload);
}
}  // namespace
