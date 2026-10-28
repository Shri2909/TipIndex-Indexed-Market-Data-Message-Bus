#include "differential/poll_campaign.hpp"
#include <gtest/gtest.h>

TEST(PollDifferential, InterleavedRetainedAndExpiredReadersAgainstLogicalOracle) {
  const auto result = tiplog::poll_differential::run(1, 24, 1024);
  EXPECT_EQ(result.operations, 24U * 1024U);
  EXPECT_EQ(result.mode_kernel_mask, 4095U);
  EXPECT_GT(result.tail_opens, 100U);
  EXPECT_GT(result.inspection_yields, 100U);
  EXPECT_GT(result.zero_polls, 100U);
  EXPECT_GT(result.pad_inspections, 0U);
  EXPECT_GT(result.errors, 0U);
  EXPECT_GT(result.delivered, 100U);
}
