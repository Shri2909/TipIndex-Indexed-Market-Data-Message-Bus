#include "oracle_tail.hpp"
#include <gtest/gtest.h>
#include <limits>
namespace tiplog::ref {
namespace {
SubscriptionSpec exact() { return {{{Term::Exact, "m/A/event"}}}; }
std::vector<std::byte> bytes(std::size_t length) { return std::vector<std::byte>(length, std::byte{9}); }
TEST(OracleTail, EmptyFutureAndZeroBudget) {
  ScanOracle model({64,32}); OracleTail tail(model,exact(),0);
  std::vector<OracleRecord> out;
  EXPECT_EQ(tail.poll(0,out),Status::Done);
  model.publish("m/A/event",bytes(0));
  EXPECT_EQ(tail.poll(0,out),Status::Done);
  EXPECT_EQ(tail.checkpoint(),(ResumeCheckpoint{0,0}));
  EXPECT_EQ(tail.poll(2,out),Status::Done); ASSERT_EQ(out.size(),1U);
  EXPECT_EQ(tail.checkpoint(),(ResumeCheckpoint{1,16}));
  EXPECT_THROW((OracleTail(model,exact(),UINT64_MAX)),std::invalid_argument);
}
TEST(OracleTail, SharedBudgetCompletesOldAndFreshRanges) {
  ScanOracle model({256,128}); model.publish("m/A/event",bytes(8));
  OracleTail tail(model,exact(),0);
  model.publish("m/A/event",bytes(8)); model.publish("m/A/event",bytes(8));
  std::vector<OracleRecord> out;
  EXPECT_EQ(tail.poll(2,out),Status::More);ASSERT_EQ(out.size(),2U);
  EXPECT_EQ(out[0].seq,1U);EXPECT_EQ(out[1].seq,2U);
  EXPECT_EQ(tail.checkpoint(),(ResumeCheckpoint{2,48}));
  EXPECT_EQ(tail.poll(2,out),Status::Done);ASSERT_EQ(out.size(),1U);EXPECT_EQ(out[0].seq,3U);
}
TEST(OracleTail, ZeroOutputRangesPreserveGlobalErrorPrefix) {
  ScanOracle model({64,32}); OracleTail tail(model,exact(),0);
  model.publish("m/B/event",bytes(16));std::vector<OracleRecord> out;
  EXPECT_EQ(tail.poll(8,out),Status::Done);EXPECT_TRUE(out.empty());
  for(int i=0;i<3;++i) model.publish("m/B/event",bytes(16));
  EXPECT_EQ(tail.poll(1,out),Status::Error);
  EXPECT_EQ(tail.error(),(ReplayError{ReplayError::FellBehind,0,0,3}));
  EXPECT_EQ(tail.checkpoint(),(ResumeCheckpoint{1,32}));
}
TEST(OracleTail, ExpiredCompletedPadDoesNotLoseRetainedData) {
  ScanOracle model({64,32});model.publish("m/A/event",bytes(10));model.publish("m/A/event",bytes(4));
  OracleTail tail(model,exact(),1);std::vector<OracleRecord> out;
  EXPECT_EQ(tail.poll(1,out),Status::More);EXPECT_EQ(tail.checkpoint(),(ResumeCheckpoint{2,56}));
  model.publish("m/A/event",bytes(8));model.publish("m/A/event",bytes(0));model.publish("m/A/event",bytes(8));
  EXPECT_EQ(model.tail_pos(),64U);EXPECT_EQ(model.tail_seq(),3U);
  EXPECT_EQ(tail.poll(4,out),Status::Done);ASSERT_EQ(out.size(),3U);
  EXPECT_EQ(out[0].seq,3U);EXPECT_EQ(out[2].seq,5U);EXPECT_FALSE(tail.error());
  EXPECT_EQ(tail.checkpoint(),(ResumeCheckpoint{5,128}));
}
TEST(OracleTail, InitialHistoryExpiredRemainsInitial) {
  ScanOracle model({64,32});for(int i=0;i<4;++i)model.publish("m/A/event",bytes(16));
  OracleTail tail(model,exact(),0);std::vector<OracleRecord> out;
  EXPECT_EQ(tail.poll(8,out),Status::Error);
  EXPECT_EQ(tail.error(),(ReplayError{ReplayError::HistoryExpired,0,0,3}));EXPECT_FALSE(tail.checkpoint());
}
} // namespace
} // namespace tiplog::ref
