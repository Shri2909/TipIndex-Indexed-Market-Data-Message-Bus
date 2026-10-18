#include <array>
#include <span>

#include <gtest/gtest.h>

// Phase 0 checks compiler/library/test plumbing only; no engine exists yet.
TEST(Plumbing, Cxx20AndGoogleTest) {
  constexpr std::array values{2, 3, 5};
  const std::span<const int> view{values};
  EXPECT_EQ(view.size(), 3U);
  EXPECT_EQ(view.back(), 5);
}
