#include <array>
#include <span>

#include <gtest/gtest.h>

TEST(Plumbing, Cxx20AndGoogleTest) {
  constexpr std::array values{2, 3, 5};
  const std::span<const int> view{values};
  EXPECT_EQ(view.size(), 3U);
  EXPECT_EQ(view.back(), 5);
}
