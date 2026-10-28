#include "differential/campaign.hpp"

#include <gtest/gtest.h>

namespace tiplog::differential {
namespace {
TEST(DifferentialCoverage, RetainedExecutionAndVariedPayloadsAcrossModesAndKernels) {
  for (const auto mode : {ReplayMode::Scan, ReplayMode::Indexed, ReplayMode::Auto}) {
    for (const auto kernel : {MergeKernel::StdPQ, MergeKernel::BinHeap,
                              MergeKernel::Quad, MergeKernel::Loser}) {
      SCOPED_TRACE(static_cast<unsigned>(mode));
      SCOPED_TRACE(static_cast<unsigned>(kernel));
      const auto result = run({1, 3, 2000, mode, kernel});
      EXPECT_EQ(result.operations, 6000U);
      EXPECT_GT(result.batches, 100U);
      // These are coverage requirements of the deterministic generator, not
      // time limits. Stale/future/empty cases must coexist with useful delivery.
      EXPECT_GT(result.indexed_execution_batches + result.scan_execution_batches,
                result.batches / 5);
      EXPECT_GT(result.delivered, result.operations / 10);
      EXPECT_GT(result.nonuniform_publications, result.publications / 2);
      EXPECT_GT(result.history_expired, 0U);
      EXPECT_GT(result.fell_behind, 0U);
      EXPECT_GT(result.empty_specs_rejected, 0U);
      if (mode == ReplayMode::Indexed) {
        EXPECT_GT(result.indexed_execution_batches, 0U);
        EXPECT_GT(result.multicursor_opens, 0U);
      }
    }
  }
}
}  // namespace
}  // namespace tiplog::differential
