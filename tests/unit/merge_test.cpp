#include "tiplog/merge/kernels.hpp"

#include <gtest/gtest.h>

#include <array>
#include <iterator>
#include <random>

namespace {
using namespace tiplog;
using merge::Key;
using Lists = std::vector<std::vector<Key>>;
constexpr std::array kinds{MergeKernel::StdPQ, MergeKernel::BinHeap,
                           MergeKernel::Quad, MergeKernel::Loser};

std::vector<Key> reference(Lists lists) {
  // A balanced sequence of std::merge calls is independent of all tested
  // priority structures, and scales to 65,535 singleton/empty inputs.
  while (lists.size() > 1) {
    Lists next;
    next.reserve((lists.size() + 1) / 2);
    for (std::size_t i = 0; i < lists.size(); i += 2) {
      if (i + 1 == lists.size())
        next.push_back(std::move(lists[i]));
      else {
        std::vector<Key> joined;
        joined.reserve(lists[i].size() + lists[i + 1].size());
        std::merge(lists[i].begin(), lists[i].end(), lists[i + 1].begin(),
                   lists[i + 1].end(), std::back_inserter(joined));
        next.push_back(std::move(joined));
      }
    }
    lists = std::move(next);
  }
  return lists.empty() ? std::vector<Key>{} : std::move(lists[0]);
}
void compare(const Lists &lists) {
  std::vector<Key> heads(lists.size(), merge::sentinel);
  for (std::size_t i = 0; i < lists.size(); ++i)
    if (!lists[i].empty())
      heads[i] = lists[i][0];
  const auto expected = reference(lists);
  for (const auto kind : kinds) {
    auto kernel = merge::make_kernel(kind, heads);
    std::vector<std::size_t> offsets(lists.size());
    std::vector<Key> actual;
    std::visit(
        [&](auto &concrete) {
          while (!concrete.empty()) {
            const auto value = concrete.top();
            actual.push_back(value);
            const auto id = merge::cursor_id(value);
            ++offsets[id];
            if (offsets[id] == lists[id].size())
              concrete.pop();
            else
              concrete.replace_top(lists[id][offsets[id]]);
          }
          EXPECT_EQ(concrete.top(), merge::sentinel);
        },
        kernel);
    ASSERT_EQ(actual, expected);
    ASSERT_TRUE(std::adjacent_find(actual.begin(), actual.end(),
                                   [](Key a, Key b) { return a >= b; }) ==
                actual.end());
  }
  // Padding0 is a separately exposed Quad layout, preserving the same output.
  merge::Quad unpadded(heads, 0);
  std::vector<Key> actual;
  std::vector<std::size_t> offsets(lists.size());
  while (!unpadded.empty()) {
    const auto value = unpadded.top();
    actual.push_back(value);
    const auto id = merge::cursor_id(value);
    ++offsets[id];
    unpadded.replace_top(offsets[id] == lists[id].size()
                             ? merge::sentinel
                             : lists[id][offsets[id]]);
  }
  EXPECT_EQ(actual, expected);
}

TEST(MergeKeys, V35BoundarySentinelIdentityAndAlignmentGuards) {
  const auto maximum = merge::position_limit - 8;
  EXPECT_EQ(merge::pack(maximum, 65534), merge::sentinel - 1);
  EXPECT_EQ(merge::position(merge::pack(maximum, 65534)), maximum);
  EXPECT_EQ(merge::cursor_id(merge::pack(maximum, 65534)), 65534);
  EXPECT_EQ(merge::pack(0, 0, 1), 0);
  EXPECT_THROW((void)merge::pack(7, 0), std::invalid_argument);
  EXPECT_THROW((void)merge::pack(merge::position_limit, 0),
               std::invalid_argument);
  EXPECT_THROW((void)merge::pack(0, 65535), std::invalid_argument);
  EXPECT_THROW((void)merge::pack(0, 0, 0), std::invalid_argument);
  EXPECT_THROW((void)merge::pack(0, 1, 1), std::invalid_argument);
  EXPECT_THROW((void)merge::pack(0, 0, 65536), std::invalid_argument);
  EXPECT_THROW((void)merge::position(merge::sentinel), std::invalid_argument);
  EXPECT_THROW((void)merge::cursor_id(merge::sentinel), std::invalid_argument);
}
TEST(MergeKernels, V21EmptySingletonAndInitialEmptyLeaves) {
  compare({});
  compare({{}});
  compare({{}, {}, {}});
  compare({{merge::pack(0, 0)}});
  compare({{}, {merge::pack(0, 1), merge::pack(8, 1)}, {}});
  compare({{merge::pack(0, 0)},
           {},
           {merge::pack(8, 2)},
           {},
           {},
           {merge::pack(16, 5), merge::pack(24, 5)}});
}
TEST(MergeKernels, V21PackedMaximumAndSentinelExhaustion) {
  const auto end = merge::position_limit;
  compare({{merge::pack(end - 32, 0), merge::pack(end - 8, 0)},
           {merge::pack(end - 24, 1)},
           {},
           {merge::pack(end - 16, 3)}});
}
TEST(MergeKernels, V21AllNonPowerOfTwoCountsAndStaggeredExhaustion) {
  for (std::uint32_t k = 1; k <= 67; ++k) {
    Lists lists(k);
    for (std::uint32_t n = 0; n < 413; ++n) {
      const auto owner = (n * 17 + n / 7) % k;
      if ((owner % 5) != 0 || k == 1)
        lists[owner].push_back(merge::pack(static_cast<LogPos>(n) * 8, owner));
    }
    compare(lists);
  }
}
TEST(MergeKernels, V21UniformRandomListsVersusIndependentStdMerge) {
  std::mt19937_64 rng(20191230);
  for (unsigned round = 0; round < 100; ++round) {
    const auto k = static_cast<std::uint32_t>(1 + rng() % 180);
    Lists lists(k);
    for (std::uint32_t i = 0; i < 2500; ++i) {
      const auto owner = static_cast<std::uint32_t>(rng() % k);
      lists[owner].push_back(merge::pack(static_cast<LogPos>(i) * 8, owner));
    }
    compare(lists);
  }
}
TEST(MergeKernels, V21SevereSkewLongRunsAndAlternation) {
  for (const auto k : {2U, 7U, 64U, 4096U}) {
    Lists lists(k);
    for (std::uint32_t i = 0; i < 16000; ++i) {
      const auto owner = i < 12000 ? 0U : i % k;
      lists[owner].push_back(merge::pack(static_cast<LogPos>(i) * 8, owner));
    }
    compare(lists);
  }
}
TEST(MergeKernels, V21LargeAndMaximumCursorCounts) {
  for (const auto k : {16384U, 65535U}) {
    Lists lists(k);
    for (std::uint32_t i = 0; i < k; ++i) {
      const auto owner = k - 1 - i;
      if (owner % 3 != 1)
        lists[owner].push_back(merge::pack(static_cast<LogPos>(i) * 8, owner));
    }
    compare(lists);
  }
}
TEST(MergeKernels, V35RejectsInvalidHeadsAndReplacementBeforeMutation) {
  const std::vector<Key> too_many(65536, merge::sentinel);
  const std::vector<Key> wrong_id{merge::pack(0, 1)};
  for (const auto kind : kinds) {
    EXPECT_THROW((void)merge::make_kernel(kind, too_many),
                 std::invalid_argument);
    EXPECT_THROW((void)merge::make_kernel(kind, wrong_id),
                 std::invalid_argument);
    const std::array heads{merge::pack(16, 0), merge::pack(24, 1)};
    auto kernel = merge::make_kernel(kind, heads);
    std::visit(
        [&](auto &concrete) {
          EXPECT_THROW(concrete.replace_top(merge::pack(8, 0)),
                       std::invalid_argument);
          EXPECT_THROW(concrete.replace_top(merge::pack(16, 0)),
                       std::invalid_argument);
          EXPECT_THROW(concrete.replace_top(merge::pack(32, 1)),
                       std::invalid_argument);
          EXPECT_EQ(concrete.top(), heads[0]);
          concrete.replace_top(merge::sentinel);
          EXPECT_EQ(concrete.top(), heads[1]);
          concrete.pop();
          EXPECT_TRUE(concrete.empty());
          EXPECT_THROW(concrete.replace_top(merge::pack(40, 1)),
                       std::invalid_argument);
        },
        kernel);
  }
  EXPECT_THROW((void)merge::make_kernel(static_cast<MergeKernel>(88), {}),
               std::invalid_argument);
}
TEST(MergeQuad, V21AlignedAllocationAndThreeWordPaddingGeometry) {
  std::vector<Key> heads;
  for (std::uint32_t i = 0; i < 257; ++i)
    heads.push_back(merge::pack(i * 8U, i));
  merge::Quad padded(heads), plain(heads, 0);
  EXPECT_EQ(reinterpret_cast<std::uintptr_t>(padded.physical_base()) % 64, 0);
  EXPECT_EQ(padded.logical_base() - padded.physical_base(), 3);
  bool unpadded_crosses = false;
  for (std::size_t i = 0; 4 * i + 4 < heads.size(); ++i) {
    const auto padded_start =
        reinterpret_cast<std::uintptr_t>(padded.logical_base() + 4 * i + 1);
    const auto plain_start =
        reinterpret_cast<std::uintptr_t>(plain.logical_base() + 4 * i + 1);
    EXPECT_LE(padded_start % 64, 32);
    if (plain_start % 64 > 32)
      unpadded_crosses = true;
  }
  EXPECT_TRUE(unpadded_crosses);
  merge::Quad moved(std::move(padded));
  EXPECT_TRUE(padded.empty());
  EXPECT_EQ(padded.top(), merge::sentinel);
  EXPECT_EQ(padded.logical_base(), nullptr);
  EXPECT_THROW(padded.pop(), std::out_of_range);
  EXPECT_FALSE(moved.empty());
  EXPECT_THROW((void)merge::Quad(heads, 1), std::invalid_argument);
}
TEST(MergeLoser, V21PaddedLeavesAndIdentityChangesAlongReplayPath) {
  const std::array heads{merge::pack(8, 0), merge::pack(0, 1),
                         merge::pack(24, 2), merge::sentinel,
                         merge::pack(16, 4)};
  merge::Loser kernel(heads);
  EXPECT_EQ(kernel.padded_leaves(), 8);
  EXPECT_EQ(kernel.top(), heads[1]);
  kernel.replace_top(merge::pack(40, 1));
  EXPECT_EQ(kernel.top(), heads[0]);
  kernel.replace_top(merge::pack(32, 0));
  EXPECT_EQ(kernel.top(), heads[4]);
  kernel.pop();
  EXPECT_EQ(kernel.top(), heads[2]);
}
TEST(MergeLoser, V21MovesTransferOwnershipAndLeaveEmptySource) {
  const std::array heads{merge::pack(16, 0), merge::pack(8, 1),
                         merge::pack(24, 2)};
  merge::Loser source(heads);
  merge::Loser destination(std::move(source));
  EXPECT_TRUE(source.empty());
  EXPECT_EQ(source.top(), merge::sentinel);
  EXPECT_THROW(source.pop(), std::out_of_range);
  EXPECT_EQ(destination.top(), heads[1]);
  source = std::move(destination);
  EXPECT_TRUE(destination.empty());
  EXPECT_EQ(destination.top(), merge::sentinel);
  EXPECT_THROW(destination.replace_top(merge::pack(32, 1)),
               std::invalid_argument);
  EXPECT_EQ(source.top(), heads[1]);
  source.replace_top(merge::pack(32, 1));
  EXPECT_EQ(source.top(), heads[0]);
}
} // namespace
