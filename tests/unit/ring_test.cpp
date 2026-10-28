#include "tiplog/ring/ring.hpp"

#include <gtest/gtest.h>

#include <array>
#include <limits>
#include <random>
#include <stdexcept>
#include <utility>
#include <vector>

namespace {
using namespace tiplog;
using ring::Ring;
using ring::RingConfig;

std::vector<std::byte> payload(std::size_t size, unsigned char fill = 42) {
  return std::vector<std::byte>(size, static_cast<std::byte>(fill));
}

struct Snapshot {
  LogPos head;
  LogPos tail;
  Seq head_seq;
  Seq tail_seq;
  ring::RingStats stats;
  std::vector<std::byte> bytes;
  bool operator==(const Snapshot&) const = default;
};
Snapshot snapshot(const Ring& ring) {
  return {ring.head_pos(), ring.tail_pos(), ring.head_seq(), ring.tail_seq(), ring.stats(),
          {ring.storage_bytes().begin(), ring.storage_bytes().end()}};
}
std::vector<Seq> retained(const Ring& ring) {
  std::vector<Seq> result;
  for (auto pos = ring.tail_pos(); pos < ring.head_pos();) {
    const auto item = ring.at(pos);
    if (!item.pad) result.push_back(item.seq);
    pos += item.size;
  }
  return result;
}

TEST(RingConfig, V10V36RejectsInvalidCapacityAndMaxRecord) {
  for (const auto capacity : {0U, 8U, 16U, 63U, 96U}) {
    EXPECT_THROW(Ring((RingConfig{capacity, 16})), std::invalid_argument);
  }
  for (const auto maximum : {0U, 8U, 17U, 24U, 40U, 48U, 64U}) {
    if (maximum == 24) continue;
    EXPECT_THROW(Ring((RingConfig{64, maximum})), std::invalid_argument);
  }
  EXPECT_NO_THROW(Ring((RingConfig{32, 16})));
  EXPECT_NO_THROW(Ring((RingConfig{64, 24})));
  EXPECT_THROW(Ring((RingConfig{std::size_t{1} << 32U, 16})), std::invalid_argument);
  EXPECT_THROW(Ring((RingConfig{64, 32, 63})), std::invalid_argument);
  EXPECT_THROW(Ring((RingConfig{64, 32, 8, (LogPos{1} << 51U) + 1})), std::invalid_argument);
  EXPECT_THROW(Ring((RingConfig{64, 32, 8, 16})), std::invalid_argument);
  EXPECT_THROW(Ring((RingConfig{64, 32, 8, 100, 1})), std::invalid_argument);
}

TEST(RingFraming, V10V36HandComputedEightBytePadAndWrap) {
  Ring ring({64, 32});
  EXPECT_EQ(ring.append(11, payload(10)), 1);
  EXPECT_EQ(ring.append(12, payload(4)), 2);
  EXPECT_EQ(ring.head_pos(), 56);
  EXPECT_EQ(ring.tail_pos(), 0);
  ring.check_invariants();
  EXPECT_EQ(ring.append(13, payload(8)), 3);
  EXPECT_EQ(ring.head_pos(), 88);
  EXPECT_EQ(ring.tail_pos(), 32);
  EXPECT_EQ(ring.tail_seq(), 2);
  const auto pad = ring.at(56);
  EXPECT_TRUE(pad.pad);
  EXPECT_EQ(pad.size, 8);
  EXPECT_TRUE(pad.payload.empty());
  ring.check_invariants();
  EXPECT_EQ(ring.append(14, payload(0)), 4);
  EXPECT_EQ(ring.head_pos(), 104);
  EXPECT_EQ(ring.tail_pos(), 56);
  EXPECT_EQ(ring.tail_seq(), 3);
  EXPECT_EQ(ring.at(88).size, 16);
  EXPECT_FALSE(ring.at(88).pad);
  ring.check_invariants();
  EXPECT_EQ(ring.append(15, payload(8)), 5);
  EXPECT_EQ(ring.head_pos(), 128);
  EXPECT_EQ(ring.tail_pos(), 64);
  EXPECT_EQ(ring.tail_seq(), 3);
  EXPECT_EQ(retained(ring), (std::vector<Seq>{3, 4, 5}));
  EXPECT_EQ(ring.stats().pad_items_appended, 1);
  EXPECT_EQ(ring.stats().pad_bytes_appended, 8);
  EXPECT_EQ(ring.stats().pad_items_evicted, 1);
  ring.check_invariants();
}

TEST(RingFraming, V10ExactFitAndFullCapacityHaveNoPad) {
  Ring ring({64, 32});
  ring.append(1, payload(16));
  ring.append(2, payload(16));
  EXPECT_EQ(ring.head_pos(), 64);
  EXPECT_EQ(ring.tail_pos(), 0);
  EXPECT_EQ(ring.stats().pad_items_appended, 0);
  ring.append(3, payload(16));
  EXPECT_EQ(ring.head_pos(), 96);
  EXPECT_EQ(ring.tail_pos(), 32);
  EXPECT_EQ(retained(ring), (std::vector<Seq>{2, 3}));
  EXPECT_EQ(ring.stats().data_bytes_evicted, 32);
  ring.check_invariants();
}

TEST(RingFraming, V10V36GenericZeroPayloadMinimumIsSixteen) {
  Ring ring({64, 32});
  for (unsigned i = 0; i < 4; ++i) ring.append(i, {});
  EXPECT_EQ(ring.head_pos(), 64);
  EXPECT_EQ(ring.tail_pos(), 0);
  EXPECT_EQ(retained(ring), (std::vector<Seq>{1, 2, 3, 4}));
  ring.append(4, {});
  EXPECT_EQ(ring.tail_pos(), 16);
  EXPECT_EQ(ring.tail_seq(), 2);
  for (auto pos = ring.tail_pos(); pos < ring.head_pos(); pos += 16) {
    const auto item = ring.at(pos);
    EXPECT_FALSE(item.pad);
    EXPECT_EQ(item.size, 16);
    EXPECT_TRUE(item.payload.empty());
  }
  ring.check_invariants();
}

TEST(RingFraming, V10ExplicitLittleEndianHeaderAndFill) {
  for (std::size_t length = 0; length <= 16; ++length) {
    Ring ring({64, 32});
    ring.append(0x12345678U, payload(length, 0xa5));
    const auto item = ring.at(0);
    const auto bytes = ring.storage_bytes();
    const auto size = ((16 + length + 7) / 8) * 8;
    const auto fill = size - 16 - length;
    EXPECT_EQ(item.size, size);
    EXPECT_EQ(item.topic, 0x12345678U);
    EXPECT_EQ(item.seq, 1);
    EXPECT_EQ(std::to_integer<unsigned>(bytes[0]), size | fill);
    EXPECT_EQ(bytes[1], std::byte{0});
    EXPECT_EQ(bytes[2], std::byte{0});
    EXPECT_EQ(bytes[3], std::byte{0});
    EXPECT_EQ(bytes[4], std::byte{0x78});
    EXPECT_EQ(bytes[5], std::byte{0x56});
    EXPECT_EQ(bytes[6], std::byte{0x34});
    EXPECT_EQ(bytes[7], std::byte{0x12});
    EXPECT_EQ(bytes[8], std::byte{1});
    for (std::size_t i = 9; i < 16; ++i) EXPECT_EQ(bytes[i], std::byte{0});
    EXPECT_EQ(item.payload.size(), length);
    for (const auto byte : item.payload) EXPECT_EQ(byte, std::byte{0xa5});
    for (auto i = 16 + length; i < size; ++i) EXPECT_EQ(bytes[i], std::byte{0});
    ring.check_invariants();
  }
}

TEST(RingRejection, V36OversizedAndSizeMaxLeaveAllObservableStateUnchanged) {
  Ring ring({64, 32});
  ring.append(1, payload(16));
  ring.append(2, payload(16));
  const auto before = snapshot(ring);
  EXPECT_THROW(ring.append(3, payload(17)), std::length_error);
  EXPECT_EQ(snapshot(ring), before);
  EXPECT_THROW((void)ring.dry_run(std::numeric_limits<std::size_t>::max()), std::length_error);
  EXPECT_EQ(snapshot(ring), before);
  ring.check_invariants();
}

TEST(RingRejection, V36PositionLimitIsCheckedBeforeEviction) {
  Ring ring({64, 32, 8, 81});
  ring.append(1, payload(16));
  ring.append(2, payload(16));
  const auto before = snapshot(ring);
  // A 24-byte item would evict seq1, but must fail before that eviction.
  EXPECT_THROW(ring.append(3, payload(1)), std::overflow_error);
  EXPECT_EQ(snapshot(ring), before);
  ring.append(3, {});  // resulting head=80 is strictly below 81.
  EXPECT_EQ(ring.head_pos(), 80);
  ring.check_invariants();
  Ring exact_limit({64, 32, 8, 64});
  exact_limit.append(1, payload(16));
  const auto exact_before = snapshot(exact_limit);
  EXPECT_THROW(exact_limit.append(2, payload(16)), std::overflow_error);
  EXPECT_EQ(snapshot(exact_limit), exact_before);
}

TEST(RingRejection, V36SequenceLimitRejectsWithoutChangingBytesOrRetention) {
  Ring ring({64, 32, 8, 1000, 3});
  ring.append(1, payload(16));
  ring.append(2, payload(16));
  const auto before = snapshot(ring);
  EXPECT_THROW(ring.append(3, {}), std::overflow_error);
  EXPECT_EQ(snapshot(ring), before);
  EXPECT_EQ(ring.head_seq(), 3);
  ring.check_invariants();
}

TEST(RingTransaction, PreparedAndAbandonedAppendDoesNotMutateState) {
  Ring ring({64, 32});
  ring.append(1, payload(16));
  ring.append(2, payload(8));
  const auto before = snapshot(ring);
  {
    const auto input = payload(16);
    auto plan = ring.plan_append(input);
    EXPECT_EQ(plan.layout().padding_bytes, 8);
    EXPECT_EQ(plan.layout().data_pos, 64);
    EXPECT_EQ(plan.layout().end_pos, 96);
    EXPECT_EQ(plan.layout().tail_pos, 32);
    EXPECT_EQ(plan.layout().data_evicted, 1);
    EXPECT_EQ(snapshot(ring), before);
  }
  EXPECT_EQ(snapshot(ring), before);
}

TEST(RingTransaction, RingAliasedSourceIsCopiedBeforeHeaderWrites) {
  Ring ring({64, 32});
  ring.append(1, payload(16));
  // A legal ring-storage span which the next DATA header will overwrite.
  const auto source = ring.storage_bytes().subspan(32, 16);
  const std::vector<std::byte> expected(source.begin(), source.end());
  auto plan = ring.plan_append(source);
  const auto published = ring.commit(std::move(plan), 0xffffffffU);
  const auto item = ring.at(published.pos);
  EXPECT_EQ(std::vector<std::byte>(item.payload.begin(), item.payload.end()), expected);
  ring.check_invariants();
}

TEST(RingTransaction, BorrowedPayloadMayBeRepublishedAcrossWrapAndEviction) {
  Ring ring({64, 32});
  ring.append(1, payload(10, 0xc3));
  ring.append(2, payload(4, 0x5e));
  const auto source = ring.at(0).payload;
  const std::vector<std::byte> expected(source.begin(), source.end());
  auto plan = ring.plan_append(source);
  EXPECT_EQ(plan.layout().padding_bytes, 8);
  const auto record = ring.commit(std::move(plan), 3);
  EXPECT_EQ(ring.tail_seq(), 2);
  const auto result = ring.at(record.pos).payload;
  EXPECT_EQ(std::vector<std::byte>(result.begin(), result.end()), expected);
  ring.check_invariants();
}

TEST(RingSeek, V36PadAwareLookupReturnsDataNotInterveningPad) {
  Ring ring({64, 32, 2});
  ring.append(1, payload(10));
  ring.append(2, payload(4));
  ring.append(3, payload(8));
  EXPECT_EQ(ring.seek_after(1), 32);
  EXPECT_EQ(ring.seek_after(2), 64);
  EXPECT_EQ(ring.last_seek_metrics().pads_examined, 1);
  EXPECT_LE(ring.last_seek_metrics().data_examined, 4);
  EXPECT_EQ(ring.seek_after(3), 88);
  EXPECT_EQ(ring.seek_after(std::numeric_limits<Seq>::max()), 88);
  EXPECT_THROW((void)ring.seek_after(0), std::out_of_range);
  ring.append(4, {});
  EXPECT_EQ(ring.tail_pos(), 56);
  EXPECT_TRUE(ring.is_boundary(56));
  EXPECT_EQ(ring.seek_after(2), 64);
  EXPECT_FALSE(ring.is_boundary(72));
  EXPECT_TRUE(ring.is_boundary(ring.head_pos()));
  ring.check_invariants();
}

TEST(RingSeek, V36CheckpointStorageUsesGenericSixteenByteMinimum) {
  Ring ring({65536, 32768});
  EXPECT_EQ(ring.checkpoint_slots(), 18);  // 65536/16/256 + 2.
  for (Seq seq = 1; seq <= 12000; ++seq) {
    ring.append(1, {});
    if (seq % 257 == 0) ring.check_invariants();
  }
  for (auto after = ring.tail_seq() - 1; after < ring.head_seq(); ++after) {
    const auto pos = ring.seek_after(after);
    if (after < ring.head_seq() - 1) {
      EXPECT_EQ(ring.at(pos).seq, after + 1);
      EXPECT_LE(ring.last_seek_metrics().data_examined, 256);
    } else {
      EXPECT_EQ(pos, ring.head_pos());
    }
  }
  ring.check_invariants();
}

TEST(RingSeek, V36SparseFloorSurvivesCheckpointRingReuseAndExpiredFloors) {
  Ring ring({256, 128, 2});
  for (Seq seq = 1; seq <= 1000; ++seq) {
    ring.append(static_cast<TopicId>(seq), payload(static_cast<std::size_t>((seq * 7) % 33)));
    for (auto after = ring.tail_seq() - 1; after < ring.head_seq() - 1; ++after) {
      const auto pos = ring.seek_after(after);
      EXPECT_EQ(ring.at(pos).seq, after + 1);
      EXPECT_LE(ring.last_seek_metrics().data_examined, 4);
    }
    ring.check_invariants();
  }
}

TEST(RingRetention, V36DeclaredPressureDiffersFromCapacityOnlyAndIsCounted) {
  Ring ring({128, 64});
  for (unsigned i = 0; i < 4; ++i) ring.append(i, payload(16));
  const auto before = snapshot(ring);
  EXPECT_THROW((void)ring.dry_run(0, 40), std::invalid_argument);
  EXPECT_THROW((void)ring.dry_run(0, 136), std::invalid_argument);
  EXPECT_EQ(snapshot(ring), before);
  auto plan = ring.plan_append({}, 96);
  EXPECT_EQ(plan.layout().tail_pos, 96);
  EXPECT_EQ(plan.layout().data_evicted, 3);
  EXPECT_EQ(plan.layout().pressure_data_evicted, 2);
  EXPECT_EQ(plan.layout().pressure_bytes_evicted, 64);
  const auto record = ring.commit(std::move(plan), 5);
  EXPECT_EQ(record.seq, 5);
  EXPECT_EQ(ring.tail_pos(), 96);
  EXPECT_EQ(ring.tail_seq(), 4);
  EXPECT_EQ(retained(ring), (std::vector<Seq>{4, 5}));
  EXPECT_EQ(ring.stats().pressure_data_evicted, 2);
  EXPECT_EQ(ring.stats().pressure_bytes_evicted, 64);
  ring.check_invariants();
}

TEST(RingInvariants, V11RandomizedAppendChecksEveryOperation) {
  for (std::uint64_t seed = 0; seed < 32; ++seed) {
    std::mt19937_64 random(seed);
    Ring ring({256, 128, 3});
    for (unsigned operation = 0; operation < 2000; ++operation) {
      const auto length = static_cast<std::size_t>(random() % 113);
      const auto input = payload(length, static_cast<unsigned char>(random()));
      auto plan = ring.plan_append(input);
      const auto expected_tail = plan.layout().tail_pos;
      const auto record = ring.commit(std::move(plan), static_cast<TopicId>(random()));
      ASSERT_EQ(ring.tail_pos(), expected_tail);
      ASSERT_NO_THROW(ring.check_invariants());
      const auto item = ring.at(record.pos);
      ASSERT_EQ(item.seq, record.seq);
      ASSERT_EQ(std::vector<std::byte>(item.payload.begin(), item.payload.end()), input);
    }
  }
}

TEST(RingAccess, RejectsUnalignedAndExpiredPositionsAndRecognizesBoundaries) {
  Ring ring({64, 32});
  EXPECT_TRUE(ring.is_boundary(0));
  EXPECT_THROW((void)ring.at(0), std::out_of_range);
  ring.append(1, payload(16));
  EXPECT_THROW((void)ring.at(1), std::out_of_range);
  EXPECT_THROW((void)ring.at(32), std::out_of_range);
  EXPECT_FALSE(ring.is_boundary(8));
  EXPECT_FALSE(ring.is_boundary(1));
  ring.append(2, payload(16));
  ring.append(3, payload(16));
  EXPECT_THROW((void)ring.at(0), std::out_of_range);
  EXPECT_FALSE(ring.is_boundary(0));
  EXPECT_TRUE(ring.is_boundary(32));
  EXPECT_TRUE(ring.is_boundary(96));
  EXPECT_FALSE(ring.is_boundary(104));
  ring.check_invariants();
}

TEST(RingFraming, CheckedAccessRejectsForgedInteriorHeadersAndAcceptsWrappedBoundaries) {
  Ring ring({128, 64});
  std::vector<std::byte> forged(40, std::byte{0});
  forged[0] = std::byte{24};
  forged[4] = std::byte{1};
  forged[8] = std::byte{57};
  ring.append(1, forged);
  EXPECT_FALSE(ring.is_boundary(16));
  EXPECT_THROW((void)ring.at_checked(16), std::out_of_range);
  EXPECT_EQ(ring.at_checked(0).seq, 1U);
  EXPECT_THROW((void)ring.at_checked(ring.head_pos()), std::out_of_range);
  EXPECT_THROW((void)ring.at_checked(1), std::out_of_range);
  ring.append(2, payload(40));
  ring.append(3, payload(8));
  EXPECT_THROW((void)ring.at_checked(0), std::out_of_range);
  bool saw_pad = false;
  for (auto pos = ring.tail_pos(); pos < ring.head_pos();) {
    const auto checked = ring.at_checked(pos);
    EXPECT_EQ(checked.pos, pos);
    EXPECT_EQ(checked.seq, ring.at(pos).seq);
    saw_pad |= checked.pad;
    pos += checked.size;
  }
  EXPECT_TRUE(saw_pad);
  ring.check_invariants();
}
}  // namespace
