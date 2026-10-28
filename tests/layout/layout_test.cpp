#include "tiplog/layout/exact.hpp"
#include "tiplog/layout/global.hpp"
#include "../../tools/tiplog_layout/input_budget.hpp"
#include <sstream>

#include <gtest/gtest.h>

#include <algorithm>
#include <cstdint>
#include <limits>
#include <numeric>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace tiplog::layout;

void same_evaluation(const Evaluation& a, const Evaluation& b) {
  EXPECT_EQ(cost_string(a.objective), cost_string(b.objective));
  EXPECT_EQ(a.stores, b.stores);
  EXPECT_EQ(a.read_bytes, b.read_bytes);
  EXPECT_EQ(a.useful_bytes, b.useful_bytes);
  EXPECT_EQ(a.waste_bytes, b.waste_bytes);
  EXPECT_EQ(a.stores_touched, b.stores_touched);
}

Problem exact_reads(std::vector<Node> nodes) {
  Problem result;
  result.nodes = std::move(nodes);
  for (const auto& node : result.nodes) {
    if (node.bytes != 0)
      result.consumers.push_back({node.path, {1, 1}, {{TermKind::Exact, node.path}}});
  }
  return result;
}

Layout numbered_layout(std::size_t nodes, std::uint64_t mask) {
  Layout result(nodes, 0);
  for (std::size_t i = 1; i < nodes; ++i)
    result[i] = static_cast<std::uint8_t>((mask >> (i - 1)) & 1U);
  return result;
}

// Independent breadth-first connected components, rather than production's
// evaluators or the threshold residual recurrence. Zero-only components do not
// count; the hot-node exception requires an actual singleton component.
struct ThresholdCheck { bool valid{true}; std::uint32_t stores{0}; };
ThresholdCheck check_threshold_components(const Problem& p, const Layout& cuts,
                                          std::uint64_t threshold_bytes) {
  ThresholdCheck result;
  std::vector<bool> seen(p.nodes.size(), false);
  for (std::size_t start = 0; start < p.nodes.size(); ++start) {
    if (seen[start]) continue;
    std::vector<std::size_t> component{start};
    seen[start] = true;
    std::uint64_t bytes = 0;
    for (std::size_t cursor = 0; cursor < component.size(); ++cursor) {
      const auto node = component[cursor];
      bytes += p.nodes[node].bytes;
      for (std::size_t child = 1; child < p.nodes.size(); ++child) {
        if (cuts[child]) continue;
        const auto parent = static_cast<std::size_t>(p.nodes[child].parent);
        const auto other = child == node ? parent : parent == node ? child : p.nodes.size();
        if (other < p.nodes.size() && !seen[other]) {
          seen[other] = true;
          component.push_back(other);
        }
      }
    }
    if (bytes > threshold_bytes && component.size() != 1) result.valid = false;
    if (bytes != 0) ++result.stores;
  }
  return result;
}

std::uint32_t threshold_oracle(const Problem& p, std::uint64_t threshold_bytes) {
  if (p.nodes.empty()) return 0;
  auto best = static_cast<std::uint32_t>(p.nodes.size());
  const auto possibilities = std::uint64_t{1} << (p.nodes.size() - 1);
  for (std::uint64_t mask = 0; mask < possibilities; ++mask) {
    const auto candidate = check_threshold_components(
        p, numbered_layout(p.nodes.size(), mask), threshold_bytes);
    if (candidate.valid) best = std::min(best, candidate.stores);
  }
  return best;
}

Limits generous_limits() {
  Limits limits;
  limits.max_states = 10000000;
  limits.max_work = 100000000;
  limits.time_limit_ms = 60000;
  return limits;
}

void reconstructed(const Prepared& p, const ExactResult& result) {
  for (std::size_t k = 0; k < result.curve.size(); ++k) {
    const auto& point = result.curve[k];
    if (!point.feasible) continue;
    const auto formula = evaluate_formula(p, point.cuts);
    same_evaluation(formula, evaluate_materialized(p, point.cuts));
    EXPECT_EQ(formula.stores, k);
    EXPECT_EQ(cost_string(formula.objective), cost_string(point.objective));
  }
}

TEST(LayoutPaths, ExactSubtreeAboveRootAndSegmentBoundaries) {
  EXPECT_TRUE(matches("market/symbol/add", {TermKind::Exact, "market/symbol/add"}));
  EXPECT_FALSE(matches("market/symbol/add/x", {TermKind::Exact, "market/symbol/add"}));
  EXPECT_TRUE(matches("market/symbol/add", {TermKind::Subtree, "market"}));
  EXPECT_TRUE(matches("market/symbol/add", {TermKind::Subtree, "market/symbol/add"}));
  EXPECT_FALSE(matches("market/symbol/addition", {TermKind::Subtree, "market/symbol/add"}));
  EXPECT_FALSE(matches("market/symbolx/add", {TermKind::Subtree, "market/symbol"}));
}

TEST(LayoutEvaluation, InternalMessagesBasketsAndMatchedZeroNodes) {
  Problem problem;
  problem.nodes = {{"market/symbol", no_parent, 2}, {"market/symbol/a", 0, 3},
                   {"market/symbol/a/x", 1, 5}, {"market/symbol/b", 0, 0}};
  problem.consumers = {
      {"basket", {2, 1}, {{TermKind::Exact, "market/symbol/a"},
                          {TermKind::Exact, "market/symbol/a/x"},
                          {TermKind::Subtree, "market/symbol/a"}}},
      {"above", {3, 1}, {{TermKind::Subtree, "market"}}},
      {"zero", {9, 1}, {{TermKind::Exact, "market/symbol/b"}}},
      {"boundary", {7, 1}, {{TermKind::Subtree, "market/symbol/ax"}}}};
  problem.beta = {4, 1};
  problem.gamma = {7, 1};
  const auto p = prepare(problem);
  const auto joined = evaluate_formula(p, Layout(4, 0));
  same_evaluation(joined, evaluate_materialized(p, Layout(4, 0)));
  EXPECT_EQ(cost_string(joined.objective), "77");
  EXPECT_EQ(joined.stores, 1U);
  EXPECT_EQ(joined.read_bytes, (std::vector<std::uint64_t>{10, 10, 0, 0}));
  EXPECT_EQ(joined.useful_bytes, (std::vector<std::uint64_t>{8, 10, 0, 0}));
  EXPECT_EQ(joined.waste_bytes, (std::vector<std::uint64_t>{2, 0, 0, 0}));
  EXPECT_EQ(joined.stores_touched, (std::vector<std::uint32_t>{1, 1, 0, 0}));
  const Layout split{0, 1, 0, 1};
  const auto separate = evaluate_formula(p, split);
  same_evaluation(separate, evaluate_materialized(p, split));
  EXPECT_EQ(separate.stores, 2U);
  EXPECT_EQ(cost_string(separate.objective), "92");
  EXPECT_EQ(separate.read_bytes, (std::vector<std::uint64_t>{8, 10, 0, 0}));
}

TEST(LayoutBaseline, RootOwnMessagesShortPathsAndNoPhantomStores) {
  const auto p = prepare(exact_reads({{"market/symbol", no_parent, 7},
      {"market/symbol/a", 0, 4}, {"market/symbol/a/x", 1, 3},
      {"market/symbol/b", 0, 0}, {"market/symbol/b/y", 3, 6},
      {"market/symbol/empty", 0, 0}}));
  const auto cuts = baseline(p);
  EXPECT_EQ(cuts, (Layout{0, 1, 0, 1, 0, 1}));
  const auto e = evaluate_formula(p, cuts);
  same_evaluation(e, evaluate_materialized(p, cuts));
  EXPECT_EQ(e.stores, 3U);
  EXPECT_EQ(cost_string(e.objective), "27");
  for (const auto* path : {"market", "market/symbol"}) {
    const auto one = prepare(exact_reads({{path, no_parent, 5}}));
    EXPECT_EQ(baseline(one), (Layout{0}));
    EXPECT_EQ(evaluate_formula(one, baseline(one)).stores, 1U);
  }
}

TEST(LayoutThreshold, ExhaustiveOwnProblemHotSingletonsEqualityAndMonotonicity) {
  for (std::uint64_t seed = 0; seed < 64; ++seed) {
    SCOPED_TRACE(seed);
    std::mt19937_64 random(seed);
    Problem raw;
    raw.nodes.push_back({"r", no_parent, random() % 7});
    const std::size_t count = 2 + static_cast<std::size_t>(random() % 5);
    for (std::size_t v = 1; v < count; ++v) {
      const auto parent = static_cast<std::uint32_t>(random() % v);
      raw.nodes.push_back({raw.nodes[parent].path + "/n" + std::to_string(v),
                           parent, random() % 7});
    }
    const auto p = prepare(raw);
    auto previous = static_cast<std::uint32_t>(count);
    for (std::uint64_t t = 0; t <= p.total_bytes; ++t) {
      SCOPED_TRACE(t);
      const auto cuts = threshold(p, t);
      EXPECT_EQ(cuts, threshold(p, t));
      const auto e = evaluate_formula(p, cuts);
      const auto independent = check_threshold_components(raw, cuts, t);
      EXPECT_TRUE(independent.valid);
      EXPECT_EQ(e.stores, independent.stores);
      EXPECT_EQ(e.stores, threshold_oracle(raw, t));
      EXPECT_LE(e.stores, previous);
      previous = e.stores;
      for (std::size_t v = 0; v < raw.nodes.size(); ++v) {
        if (raw.nodes[v].bytes <= t) continue;
        if (v != 0) EXPECT_TRUE(cuts[v]);
        for (std::size_t child = 1; child < raw.nodes.size(); ++child)
          if (raw.nodes[child].parent == v) EXPECT_TRUE(cuts[child]);
      }
    }
  }
}

TEST(LayoutThreshold, DeterministicEqualChildTiesAndFinitePlateau) {
  const auto p = prepare(exact_reads({{"r", no_parent, 0}, {"r/a", 0, 2},
                                    {"r/b", 0, 2}, {"r/c", 0, 2}}));
  EXPECT_EQ(threshold(p, 4), (Layout{0, 1, 0, 0}));
  EXPECT_EQ(threshold(p, 2), (Layout{0, 1, 1, 0}));
  const auto low = km_min(p, 1);
  const auto high = km_max(p, 1);
  EXPECT_EQ(low.status, "feasible");
  EXPECT_EQ(high.status, "feasible");
  EXPECT_EQ(low.threshold_bytes, 6U);
  EXPECT_EQ(high.threshold_bytes, 6U);
  EXPECT_EQ(km_min(p, 0).status, "infeasible");
  const auto maximum = std::numeric_limits<std::uint64_t>::max();
  const auto huge = prepare(exact_reads({{"r", no_parent, maximum}}));
  EXPECT_EQ(km_min(huge, 1).threshold_bytes, 0U);
  EXPECT_EQ(km_max(huge, 1).threshold_bytes, maximum);
}

TEST(LayoutArithmetic, ExactRationalCoefficientsWeightsAndNormalizedScale) {
  auto raw = exact_reads({{"r", no_parent, 2}, {"r/a", 0, 3}});
  raw.alpha = {2, 3}; raw.beta = {5, 7}; raw.gamma = {11, 13};
  raw.consumers[0].weight = {3, 5}; raw.consumers[1].weight = {7, 11};
  const auto p = prepare(raw);
  const auto joined = evaluate_formula(p, {0, 0});
  const auto split = evaluate_formula(p, {0, 1});
  EXPECT_EQ(joined.objective * 3003, p.scale * 17569);
  EXPECT_EQ(split.objective * 5005, p.scale * 23264);
  same_evaluation(joined, evaluate_materialized(p, {0, 0}));
  same_evaluation(split, evaluate_materialized(p, {0, 1}));
  raw.alpha = {4, 6}; raw.beta = {10, 14}; raw.gamma = {22, 26};
  raw.consumers[0].weight = {6, 10}; raw.consumers[1].weight = {14, 22};
  const auto equivalent = prepare(raw);
  EXPECT_EQ(p.scale, equivalent.scale);
  EXPECT_EQ(joined.objective, evaluate_formula(equivalent, {0, 0}).objective);
}

TEST(LayoutArithmetic, RejectsSentinelScaleAndIndependentVolumeOverflow) {
  EXPECT_EQ(checked_add(infinity - 2, 1), infinity - 1);
  EXPECT_THROW((void)checked_add(infinity - 1, 1), std::exception);
  EXPECT_THROW((void)checked_mul(infinity / 2 + 1, 2), std::exception);
  EXPECT_EQ(parse_cost(cost_string(infinity - 1)), infinity - 1);
  EXPECT_THROW((void)parse_cost(cost_string(infinity)), std::exception);
  EXPECT_THROW((void)parse_cost("-1"), std::exception);
  auto raw = exact_reads({{"r", no_parent, std::numeric_limits<std::uint64_t>::max()},
                          {"r/a", 0, 1}});
  raw.alpha = {0, 1};
  EXPECT_THROW((void)prepare(raw), std::exception);
  raw = exact_reads({{"r", no_parent, 1}});
  raw.alpha.denominator = 0;
  EXPECT_THROW((void)prepare(raw), std::exception);
  const auto maximum = std::numeric_limits<std::uint64_t>::max();
  raw.alpha = {1, maximum}; raw.beta = {1, maximum - 1};
  raw.gamma = {1, maximum - 2}; raw.consumers[0].weight = {1, maximum - 3};
  EXPECT_THROW((void)prepare(raw), std::exception);
  raw.alpha = {maximum, 1}; raw.beta = {maximum, 1}; raw.gamma = {maximum, 1};
  raw.nodes[0].bytes = maximum; raw.consumers[0].weight = {maximum, 1};
  EXPECT_THROW((void)prepare(raw), std::exception);
}

TEST(LayoutExact, HandDerivedChainEveryCountAndReconstruction) {
  Problem raw;
  raw.nodes = {{"r", no_parent, 1}, {"r/a", 0, 2}, {"r/a/b", 1, 3}};
  raw.consumers = {{"one", {1, 1}, {{TermKind::Exact, "r"}, {TermKind::Exact, "r/a/b"}}},
                   {"two", {1, 1}, {{TermKind::Exact, "r/a"}}}};
  const auto p = prepare(raw);
  const std::vector<std::string> costs{"12", "11", "9", "6"};
  for (std::uint64_t mask = 0; mask < 4; ++mask)
    EXPECT_EQ(cost_string(evaluate_formula(p, numbered_layout(3, mask)).objective), costs[mask]);
  for (const auto& result : {enumerate(p, 3, generous_limits()), mask_dp(p, 3, generous_limits())}) {
    ASSERT_EQ(result.status, "solved");
    ASSERT_EQ(result.curve.size(), 4U);
    EXPECT_TRUE(result.complete_domain);
    EXPECT_FALSE(result.curve[0].feasible);
    EXPECT_EQ(cost_string(result.curve[1].objective), "12");
    EXPECT_EQ(cost_string(result.curve[2].objective), "9");
    EXPECT_EQ(cost_string(result.curve[3].objective), "6");
    EXPECT_EQ(cost_string(at_most(result, 99).objective), "6");
    reconstructed(p, result);
  }
}

TEST(LayoutExact, EmptyAllZeroNoConsumersAndZeroBudget) {
  auto all_zero = exact_reads({{"r", no_parent, 0}, {"r/a", 0, 0}});
  all_zero.beta = {3, 1}; all_zero.gamma = {9, 1};
  all_zero.consumers = {{"above", {7, 1}, {{TermKind::Subtree, "r"}}}};
  for (const auto& raw : {Problem{}, all_zero}) {
    const auto p = prepare(raw);
    EXPECT_EQ(evaluate_formula(p, baseline(p)).stores, 0U);
    EXPECT_EQ(km_min(p, 0).status, "feasible");
    EXPECT_EQ(km_max(p, 0).status, "feasible");
    for (const auto& result : {enumerate(p, 0), mask_dp(p, 0)}) {
      EXPECT_EQ(result.status, "solved");
      ASSERT_EQ(result.curve.size(), 1U);
      EXPECT_TRUE(result.curve[0].feasible);
      EXPECT_EQ(cost_string(result.curve[0].objective), "0");
      EXPECT_TRUE(result.complete_domain);
      reconstructed(p, result);
    }
  }
  Problem raw;
  raw.nodes = {{"r", no_parent, 3}, {"r/a", 0, 4}};
  raw.gamma = {5, 1};
  const auto p = prepare(raw);
  EXPECT_EQ(enumerate(p, 0).status, "infeasible");
  EXPECT_EQ(mask_dp(p, 0).status, "infeasible");
  for (const auto& result : {enumerate(p, 2), mask_dp(p, 2)}) {
    ASSERT_EQ(result.status, "solved");
    EXPECT_EQ(cost_string(result.curve[1].objective), "5");
    EXPECT_EQ(cost_string(result.curve[2].objective), "10");
    EXPECT_EQ(cost_string(at_most(result, 2).objective), "5");
    reconstructed(p, result);
  }
}

TEST(LayoutExact, ForwardParentIdsAndMultipleChildStages) {
  auto raw = exact_reads({{"r", no_parent, 2}, {"r/b/c", 3, 3},
                         {"r/a", 0, 4}, {"r/b", 0, 0}, {"r/b/d", 3, 5}});
  raw.beta = {7, 3}; raw.gamma = {11, 2};
  const auto p = prepare(raw);
  const auto expected = enumerate(p, 4, generous_limits());
  const auto actual = mask_dp(p, 4, generous_limits());
  ASSERT_EQ(expected.status, "solved"); ASSERT_EQ(actual.status, "solved");
  ASSERT_EQ(actual.curve.size(), expected.curve.size());
  for (std::size_t k = 0; k < expected.curve.size(); ++k) {
    EXPECT_EQ(actual.curve[k].feasible, expected.curve[k].feasible);
    if (expected.curve[k].feasible)
      EXPECT_EQ(actual.curve[k].objective, expected.curve[k].objective);
  }
  reconstructed(p, expected); reconstructed(p, actual);
}

TEST(LayoutRepresentation, InvalidTreesAndLayoutsAreRejected) {
  auto raw = exact_reads({{"r", no_parent, 1}, {"r/a", 0, 2}});
  const auto p = prepare(raw);
  for (const auto& invalid : {Layout{}, Layout{0}, Layout{1, 0}, Layout{0, 2}}) {
    EXPECT_THROW((void)evaluate_formula(p, invalid), std::exception);
    EXPECT_THROW((void)evaluate_materialized(p, invalid), std::exception);
  }
  raw.nodes[1].parent = no_parent;
  EXPECT_THROW((void)prepare(raw), std::exception);
  raw.nodes[1].parent = 1;
  EXPECT_THROW((void)prepare(raw), std::exception);
  raw.nodes[1].parent = 0;
  raw.nodes[1].path = "r/a/skipped";
  EXPECT_THROW((void)prepare(raw), std::exception);
  raw.nodes[1].path = "r";
  EXPECT_THROW((void)prepare(raw), std::exception);
}

TEST(LayoutRepresentation, EnumerationAndEvaluatorsSupportMoreThanOneWordOfClasses) {
  Problem raw;
  raw.nodes = {{"r", no_parent, 1}, {"r/a", 0, 2}};
  for (unsigned j = 0; j < 65; ++j)
    raw.consumers.push_back({std::to_string(j), {1, 1}, {{TermKind::Exact, "r"}}});
  const auto p = prepare(raw);
  same_evaluation(evaluate_formula(p, {0, 0}), evaluate_materialized(p, {0, 0}));
  const auto result = enumerate(p, 2, generous_limits());
  ASSERT_EQ(result.status, "solved");
  EXPECT_EQ(cost_string(result.curve[1].objective), "195");
  EXPECT_EQ(cost_string(result.curve[2].objective), "65");
  reconstructed(p, result);
  EXPECT_EQ(mask_dp(p, 2, generous_limits()).status, "representation_limit");
}

TEST(LayoutExact, RepresentationWorkStateAndTimeCapsAreExplicit) {
  const auto p = prepare(exact_reads({{"r", no_parent, 1}, {"r/a", 0, 2}}));
  auto limits = generous_limits();
  limits.enum_max_edges = 0;
  EXPECT_EQ(enumerate(p, 2, limits).status, "representation_limit");
  limits = generous_limits(); limits.dp_max_classes = 0;
  EXPECT_EQ(mask_dp(p, 2, limits).status, "representation_limit");
  limits = generous_limits(); limits.max_states = 0;
  const auto state_limited = mask_dp(p, 2, limits);
  EXPECT_EQ(state_limited.status, "state_limit");
  EXPECT_FALSE(state_limited.complete_domain);
  limits = generous_limits(); limits.max_work = 0;
  EXPECT_EQ(enumerate(p, 2, limits).status, "state_limit");
  EXPECT_EQ(mask_dp(p, 2, limits).status, "state_limit");
  limits = generous_limits(); limits.time_limit_ms = 0;
  EXPECT_EQ(enumerate(p, 2, limits).status, "timeout");
  EXPECT_EQ(mask_dp(p, 2, limits).status, "timeout");
}

std::uint64_t waste(const Evaluation& evaluation) {
  return std::accumulate(evaluation.waste_bytes.begin(), evaluation.waste_bytes.end(), std::uint64_t{0});
}

TEST(LayoutWorkedExample, SeparatePartitionsJointBudgetAndThresholdEndpoints) {
  const auto left = prepare(exact_reads({{"L", no_parent, 0}, {"L/A", 0, 28500000},
      {"L/A/a1", 1, 10000000}, {"L/A/a2", 1, 2720000000}, {"L/b", 0, 148000}}));
  const auto right = prepare(exact_reads({{"R", no_parent, 0}, {"R/R1", 0, 0},
      {"R/R1/c1", 1, 197}, {"R/R1/c2", 1, 29300}, {"R/R2", 0, 0},
      {"R/R2/d1", 4, 10000}, {"R/R2/d2", 4, 421000}}));
  EXPECT_EQ(left.total_bytes + right.total_bytes, 2759108497ULL);
  EXPECT_EQ(waste(evaluate_formula(left, baseline(left))) +
            waste(evaluate_formula(right, baseline(right))), 5517460497ULL);
  const Layout figure_left{0, 1, 0, 1, 1};
  const Layout optimum_left{0, 0, 1, 1, 0};
  const Layout joined_right(7, 0);
  const auto figure = evaluate_formula(left, figure_left);
  const auto optimum = evaluate_formula(left, optimum_left);
  const auto r = evaluate_formula(right, joined_right);
  EXPECT_EQ(figure.stores + r.stores, 4U);
  EXPECT_EQ(optimum.stores + r.stores, 4U);
  EXPECT_EQ(waste(figure) + waste(r), 39881491ULL);
  EXPECT_EQ(waste(optimum) + waste(r), 30029491ULL);
  same_evaluation(figure, evaluate_materialized(left, figure_left));
  same_evaluation(optimum, evaluate_materialized(left, optimum_left));
  same_evaluation(r, evaluate_materialized(right, joined_right));

  const auto l_enum = enumerate(left, 4, generous_limits());
  const auto r_enum = enumerate(right, 4, generous_limits());
  const auto l_dp = mask_dp(left, 4, generous_limits());
  const auto r_dp = mask_dp(right, 4, generous_limits());
  ASSERT_EQ(l_enum.status, "solved"); ASSERT_EQ(r_enum.status, "solved");
  ASSERT_EQ(l_dp.status, "solved"); ASSERT_EQ(r_dp.status, "solved");
  Cost best = infinity;
  std::size_t best_l = 0, best_r = 0;
  for (std::size_t l = 1; l < l_enum.curve.size(); ++l) {
    for (std::size_t k = 1; k < r_enum.curve.size() && l + k <= 4; ++k) {
      const auto& a = l_enum.curve[l]; const auto& b = r_enum.curve[k];
      if (a.feasible && b.feasible && a.objective + b.objective < best) {
        best = a.objective + b.objective; best_l = l; best_r = k;
      }
    }
  }
  EXPECT_EQ(best_l, 3U); EXPECT_EQ(best_r, 1U);
  EXPECT_EQ(cost_string(best), "2789137988");
  EXPECT_GT(l_enum.curve[2].objective + r_enum.curve[2].objective, best);
  EXPECT_EQ(l_dp.curve[3].objective + r_dp.curve[1].objective, best);
  reconstructed(left, l_dp); reconstructed(right, r_dp);

  const auto count_at = [&](std::uint64_t t) {
    return evaluate_formula(left, threshold(left, t)).stores +
           evaluate_formula(right, threshold(right, t)).stores;
  };
  std::uint64_t lo = 0, hi = left.total_bytes + right.total_bytes;
  while (lo < hi) {
    const auto mid = lo + (hi - lo) / 2;
    if (count_at(mid) <= 4) hi = mid; else lo = mid + 1;
  }
  const auto minimum = lo;
  hi = left.total_bytes + right.total_bytes;
  while (lo < hi) {
    const auto distance = hi - lo;
    const auto mid = lo + distance / 2 + distance % 2;
    if (count_at(mid) == count_at(minimum)) lo = mid; else hi = mid - 1;
  }
  EXPECT_EQ(minimum, 28648000U); EXPECT_EQ(lo, 38647999U);
  EXPECT_EQ(count_at(minimum - 1), 5U);
  EXPECT_EQ(count_at(lo + 1), 3U);
  EXPECT_EQ(waste(evaluate_formula(left, threshold(left, minimum))) +
            waste(evaluate_formula(right, threshold(right, minimum))), 30029491ULL);
  EXPECT_EQ(waste(evaluate_formula(left, threshold(left, lo))) +
            waste(evaluate_formula(right, threshold(right, lo))), 39881491ULL);
  Problem subtree_problem = left.input;
  subtree_problem.consumers = {{"A", {1, 1}, {{TermKind::Subtree, "L/A"}}}};
  const auto subtree = prepare(subtree_problem);
  EXPECT_EQ(evaluate_formula(subtree, figure_left).waste_bytes[0], 0U);
  EXPECT_EQ(evaluate_formula(subtree, optimum_left).waste_bytes[0], 148000U);
}

TEST(LayoutGlobal, SupportedSelectionsAreOptimalForTheirOwnAtMostBudget) {
  const CostCurve a{{infinity, 10, 8, 0}, 1, 3, true};
  const CostCurve b{{infinity, 7, 2}, 1, 2, true};
  for (const auto lambda : {0U, 1U, 2U, 5U, 8U, 17U}) {
    SCOPED_TRACE(lambda);
    const auto point = penalized({a, b}, {lambda, 1});
    ASSERT_EQ(point.status, "feasible");
    ASSERT_TRUE(point.certified);
    ASSERT_EQ(point.counts.size(), 2U);
    EXPECT_EQ(point.stores, point.counts[0] + point.counts[1]);
    Cost independent_best = infinity;
    for (std::size_t i = 1; i < a.values.size(); ++i)
      for (std::size_t j = 1; j < b.values.size(); ++j)
        if (i + j <= point.stores)
          independent_best = std::min(independent_best, a.values[i] + b.values[j]);
    EXPECT_EQ(point.objective, point.scale * independent_best);
    EXPECT_EQ(point.penalized, point.objective + point.scale * lambda * point.stores);
    const auto bound = budget_bound({a, b}, {lambda, 1}, point.stores);
    EXPECT_TRUE(bound.available);
    EXPECT_FALSE(bound.negative);
    EXPECT_EQ(bound.magnitude * point.scale, point.objective * bound.scale);
  }
}

TEST(LayoutGlobal, UnsupportedBudgetBoundDoesNotClaimMissingSupportedPoint) {
  const CostCurve curve{{infinity, 10, 8, 0}, 1, 3, true};
  const auto point = penalized({curve}, {5, 1});
  ASSERT_EQ(point.status, "feasible");
  ASSERT_TRUE(point.certified);
  EXPECT_EQ(point.counts, (std::vector<std::uint32_t>{1}));
  EXPECT_EQ(point.objective, point.scale * 10);
  const auto bound = budget_bound({curve}, {5, 1}, 2);
  EXPECT_TRUE(bound.available);
  EXPECT_FALSE(bound.negative);
  EXPECT_EQ(bound.magnitude, bound.scale * 5);
  EXPECT_LT(bound.magnitude, bound.scale * curve.values[2]);
  for (std::uint64_t lambda = 0; lambda <= 16; ++lambda)
    EXPECT_NE(penalized({curve}, {lambda, 1}).counts[0], 2U);
}

TEST(LayoutGlobal, RationalCurvesAndPenaltyShareOneExactScale) {
  const CostCurve a{{infinity, 20, 12}, 2, 2, true};
  const CostCurve b{{infinity, 9, 6}, 3, 2, true};
  const auto point = penalized({a, b}, {1, 2});
  ASSERT_EQ(point.status, "feasible");
  EXPECT_TRUE(point.certified);
  EXPECT_EQ(point.counts, (std::vector<std::uint32_t>{2, 2}));
  EXPECT_EQ(point.stores, 4U);
  EXPECT_EQ(point.objective, point.scale * 8);
  EXPECT_EQ(point.penalized, point.scale * 10);
  const auto bound = budget_bound({a, b}, {1, 2}, 4);
  EXPECT_TRUE(bound.available);
  EXPECT_FALSE(bound.negative);
  EXPECT_EQ(bound.magnitude, bound.scale * 8);
}

TEST(LayoutGlobal, IncompleteOrMissingPartitionTermsWithholdCertificates) {
  const CostCurve complete{{infinity, 7, 2}, 1, 2, true};
  const CostCurve incomplete{{infinity, 10, 8}, 1, 3, false};
  const auto point = penalized({complete, incomplete}, {5, 1});
  EXPECT_EQ(point.status, "feasible_uncertified");
  EXPECT_FALSE(point.certified);
  EXPECT_FALSE(budget_bound({complete, incomplete}, {5, 1}, 3).available);
  auto falsely_marked = incomplete;
  falsely_marked.certified_complete = true;
  EXPECT_FALSE(penalized({falsely_marked}, {5, 1}).certified);
  EXPECT_FALSE(budget_bound({falsely_marked}, {5, 1}, 2).available);
  const CostCurve no_candidate{{infinity, infinity}, 1, 2, false};
  EXPECT_EQ(penalized({complete, no_candidate}, {5, 1}).status, "no_feasible_incumbent");
  EXPECT_FALSE(budget_bound({complete, no_candidate}, {5, 1}, 3).available);
}

TEST(LayoutGlobal, EmptyForestZeroStorePartitionAndSignedBounds) {
  const auto empty = penalized({}, {0, 1});
  EXPECT_EQ(empty.status, "feasible");
  EXPECT_TRUE(empty.certified);
  EXPECT_EQ(empty.stores, 0U);
  EXPECT_TRUE(empty.counts.empty());
  EXPECT_EQ(cost_string(empty.objective), "0");
  const CostCurve zero{{0}, 1, 0, true};
  const auto point = penalized({zero, zero}, {1, 10});
  EXPECT_EQ(point.status, "feasible");
  EXPECT_TRUE(point.certified);
  EXPECT_EQ(point.counts, (std::vector<std::uint32_t>{0, 0}));
  EXPECT_EQ(cost_string(point.penalized), "0");
  const auto bound = budget_bound({}, {2, 1}, 7);
  EXPECT_TRUE(bound.available);
  EXPECT_TRUE(bound.negative);
  EXPECT_EQ(bound.magnitude, bound.scale * 14);
}

TEST(LayoutGlobal, RejectsZeroDenominatorsAndExactArithmeticOverflow) {
  const CostCurve one{{infinity, 1}, 1, 1, true};
  EXPECT_THROW((void)penalized({one}, {1, 0}), std::exception);
  EXPECT_THROW((void)budget_bound({one}, {1, 0}, 1), std::exception);
  const CostCurve bad_scale{{0}, 0, 0, true};
  EXPECT_THROW((void)penalized({bad_scale}, {0, 1}), std::exception);
  const CostCurve almost_infinity{{infinity, infinity - 1}, 1, 1, true};
  EXPECT_THROW((void)penalized({almost_infinity}, {1, 1}), std::exception);
  const CostCurve huge_scale_a{{0}, infinity - 1, 0, true};
  const CostCurve huge_scale_b{{0}, infinity - 2, 0, true};
  EXPECT_THROW((void)penalized({huge_scale_a, huge_scale_b}, {0, 1}), std::exception);
}
TEST(LayoutResourceBounds, PreparationRejectsWorkAndMembershipExcess) {
  const auto input = exact_reads({{"r", no_parent, 1}, {"r/a", 0, 1}});
  EXPECT_EQ(preparation_work_bound(input), 8);
  PreparationLimits limits;
  limits.max_work = 7;
  EXPECT_THROW(prepare(input, limits), std::length_error);
  limits.max_work = 8;
  limits.max_memberships = 1;
  EXPECT_THROW(prepare(input, limits), std::length_error);
  limits.max_memberships = 2;
  const auto p = prepare(input, limits);
  EXPECT_EQ(evaluate_formula(p, baseline(p)).objective,
            evaluate_materialized(p, baseline(p)).objective);
}

TEST(LayoutResourceBounds, FrontendBudgetsAreAggregateAndCheckBeforeGrowth) {
  cli::InputLimits limits;
  limits.max_bytes = 4;
  limits.max_curve_entries = 5;
  limits.preparation.max_work = 16;
  cli::InputBudget budget(limits);
  std::istringstream input("a\nbc\n");
  std::string line;
  ASSERT_TRUE(budget.getline(input, line));
  EXPECT_EQ(line, "a");
  EXPECT_THROW(budget.getline(input, line), std::length_error);
  EXPECT_EQ(line, "bc");
  budget.curve(3);
  budget.curve(2);
  EXPECT_THROW(budget.curve(1), std::length_error);
  EXPECT_THROW(budget.curve(UINT64_MAX), std::length_error);
  const auto raw = exact_reads({{"r", no_parent, 1}, {"r/a", 0, 1}});
  budget.prepare(raw);
  budget.prepare(raw);
  EXPECT_THROW(budget.prepare(raw), std::length_error);
}

} // namespace
