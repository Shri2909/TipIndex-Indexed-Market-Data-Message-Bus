// Audit TDD red specifications (Stage 2 acceptance contract). Each test
// encodes the CORRECT behavior for a confirmed finding and is expected to FAIL
// on the audited baseline, for the reason stated next to it.
#include "tiplog/engine/engine.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <chrono>
#include <string>
#include <vector>

namespace tiplog {
namespace {
using Clock = std::chrono::steady_clock;
double seconds_since(Clock::time_point t) {
  return std::chrono::duration<double>(Clock::now() - t).count();
}
std::string deep_path(std::size_t depth) {
  std::string path = "a";
  for (std::size_t i = 1; i < depth; ++i) path += "/a";
  return path;
}

// RED-01 (finding AUD-001). A pathological topic path must either be rejected
// as a representation limit before mutation, or be handled without cubic
// matching work. Baseline: intern accepts it and compile() hashes every prefix
// of every ancestor (~depth^3/3 bytes): measured 2.6 s at depth 4000 and
// 20.6 s at depth 8000 on the audit host (release build).
TEST(AuditRedSpec, RED01_DeepTopicPathIsRejectedOrMatchedEfficiently) {
  Engine engine;
  const auto hooked = engine.compile({{{Term::Subtree, "a"}}});
  bool rejected = false;
  const auto t0 = Clock::now();
  try {
    (void)engine.intern(deep_path(4000));
  } catch (const topics::RepresentationLimit&) {
    rejected = true;
  }
  const double intern_s = seconds_since(t0);
  if (rejected) {
    EXPECT_EQ(engine.registry().topic_count(), 1U) << "rejection must precede mutation";
    return;
  }
  const auto t1 = Clock::now();
  (void)engine.compile({{{Term::Subtree, "zz/q"}}});
  const double compile_s = seconds_since(t1);
  EXPECT_LT(intern_s, 0.25) << "intern with a live subtree hook took " << intern_s << " s";
  EXPECT_LT(compile_s, 0.25) << "compile over the deep registry took " << compile_s << " s";
  (void)hooked;
}

// RED-04 (finding AUD-002). Notifying N live subtree subscriptions about one
// new topic must cost O(N): quadrupling N should roughly quadruple the cost.
// Baseline: Registry::intern deduplicates affected observers with a linear
// std::find_if per hook slot, so cost grows ~N^2 (measured 0.43 ms -> 5.7 ms
// per new topic for N = 2000 -> 8000, ratio ~13).
TEST(AuditRedSpec, RED04_SubtreeHookFanoutIsLinearInSubscriptions) {
  auto per_topic_seconds = [](std::size_t subscriptions) {
    double best = 1e9;
    for (int repeat = 0; repeat < 3; ++repeat) {
      Engine engine;
      std::vector<subs::CompiledSubscription> keep;
      keep.reserve(subscriptions);
      for (std::size_t i = 0; i < subscriptions; ++i)
        keep.push_back(engine.compile({{{Term::Subtree, "s/X"}}}));
      const auto t = Clock::now();
      for (int i = 0; i < 20; ++i) (void)engine.intern("s/X/t" + std::to_string(i));
      best = std::min(best, seconds_since(t) / 20.0);
    }
    return best;
  };
  const double small = per_topic_seconds(2000);
  const double large = per_topic_seconds(8000);
  EXPECT_LT(large / small, 6.0) << "per-topic cost " << small * 1e3 << " ms -> " << large * 1e3
                                << " ms for 4x subscriptions (linear ~4x, quadratic ~16x)";
}

}  // namespace
}  // namespace tiplog
