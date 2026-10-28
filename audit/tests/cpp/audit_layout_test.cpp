// Audit: storage-layout optimizer properties beyond the production CC-5 sweep
// (|V|<=12, b<=4, integer-ish costs). Larger trees, more classes, rational
// coefficients, brute-force KM optimality, and brute-force global allocation.
#include "tiplog/layout/exact.hpp"
#include "tiplog/layout/global.hpp"
#include "tiplog/layout/model.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <functional>
#include <map>
#include <random>
#include <string>
#include <vector>

namespace tiplog::layout {
namespace {

Problem random_problem(std::mt19937_64& random, std::size_t max_nodes, std::size_t max_classes) {
  Problem p;
  const auto n = 1 + random() % max_nodes;
  p.nodes.push_back({"R", no_parent, random() % 3 == 0 ? 0 : 1 + random() % 1000});
  for (std::size_t i = 1; i < n; ++i) {
    const auto parent = static_cast<std::uint32_t>(random() % i);
    const auto bytes = random() % 4 == 0 ? 0 : 1 + random() % 100000;
    p.nodes.push_back({p.nodes[parent].path + "/n" + std::to_string(i), parent, bytes});
  }
  const auto classes = random() % (max_classes + 1);
  for (std::size_t c = 0; c < classes; ++c) {
    Consumer consumer{"c" + std::to_string(c), {1 + random() % 9, 1 + random() % 6}, {}};
    const auto terms = 1 + random() % 3;
    for (std::size_t t = 0; t < terms; ++t) {
      const auto pick = random() % (n + 1);
      if (pick == n) {
        consumer.terms.push_back({TermKind::Subtree, "above"});  // above root: matches nothing
        consumer.terms.push_back({TermKind::Subtree, "R"});      // root subtree: matches all
      } else {
        consumer.terms.push_back({random() % 2 ? TermKind::Exact : TermKind::Subtree,
                                  p.nodes[pick].path});
      }
    }
    if (random() % 5 == 0) consumer.weight = {0, 1};
    p.consumers.push_back(std::move(consumer));
  }
  p.alpha = {1 + random() % 4, 1 + random() % 3};
  p.beta = {random() % 5000, 1 + random() % 7};
  p.gamma = {random() % 3000, 1 + random() % 5};
  return p;
}

// L3/CC-5 extended: MASK-DP equals ENUM at every exact store count, on trees
// up to 15 nodes and 6 classes with rational coefficients. Both reconstructed
// layouts are re-priced by the independent materializing evaluator.
TEST(AuditLayout, MaskDpEqualsEnumOnLargerRationalInstances) {
  Limits limits;
  limits.enum_max_edges = 14;
  limits.max_states = 50'000'000;
  limits.max_work = 4'000'000'000ULL;
  limits.time_limit_ms = 600'000;
  std::uint64_t compared = 0;
  for (std::uint64_t seed = 1; seed <= 1500; ++seed) {
    std::mt19937_64 random(seed);
    const auto problem = prepare(random_problem(random, 15, 6));
    const auto e = enumerate(problem, problem.positive_nodes, limits);
    const auto d = mask_dp(problem, problem.positive_nodes, limits);
    ASSERT_EQ(e.status, "solved") << seed;
    ASSERT_EQ(d.status, "solved") << seed;
    ASSERT_EQ(e.curve.size(), d.curve.size()) << seed;
    for (std::size_t k = 0; k < e.curve.size(); ++k) {
      ASSERT_EQ(e.curve[k].feasible, d.curve[k].feasible) << seed << " k=" << k;
      if (!e.curve[k].feasible) continue;
      ASSERT_TRUE(e.curve[k].objective == d.curve[k].objective)
          << "seed " << seed << " k=" << k << " enum=" << cost_string(e.curve[k].objective)
          << " dp=" << cost_string(d.curve[k].objective);
      const auto me = evaluate_materialized(problem, e.curve[k].cuts);
      const auto md = evaluate_materialized(problem, d.curve[k].cuts);
      ASSERT_TRUE(me.objective == e.curve[k].objective && md.objective == d.curve[k].objective);
      ASSERT_EQ(me.stores, k);
      ASSERT_EQ(md.stores, k);
      ++compared;
    }
  }
  std::cout << "[audit] MASK-DP/ENUM exact-count comparisons=" << compared << "\n";
}

// L2/V28: formula and materialized evaluators agree on random layouts.
TEST(AuditLayout, EvaluatorsAgreeOnRandomLayouts) {
  for (std::uint64_t seed = 1; seed <= 3000; ++seed) {
    std::mt19937_64 random(seed * 31);
    const auto problem = prepare(random_problem(random, 40, 8));
    Layout cuts(problem.input.nodes.size(), 0);
    for (std::size_t i = 1; i < cuts.size(); ++i) cuts[i] = random() % 2;
    const auto f = evaluate_formula(problem, cuts);
    const auto m = evaluate_materialized(problem, cuts);
    ASSERT_TRUE(f.objective == m.objective) << seed;
    ASSERT_EQ(f.stores, m.stores);
    ASSERT_EQ(f.read_bytes, m.read_bytes);
    ASSERT_EQ(f.useful_bytes, m.useful_bytes);
    ASSERT_EQ(f.stores_touched, m.stores_touched);
  }
}

// Brute force: the minimum number of materialized stores such that every
// materialized store has W<=T or is a single topic (ARCHITECTURE 6.6, P_T).
std::uint32_t brute_min_count(const Prepared& problem, std::uint64_t threshold) {
  const auto n = problem.input.nodes.size();
  std::uint32_t best = std::numeric_limits<std::uint32_t>::max();
  for (std::uint64_t mask = 0; mask < (std::uint64_t{1} << (n - 1)); ++mask) {
    Layout cuts(n, 0);
    for (std::size_t i = 1; i < n; ++i) cuts[i] = (mask >> (i - 1)) & 1U;
    std::vector<std::uint32_t> owner(n);
    std::vector<std::uint64_t> weight(n, 0), members(n, 0);
    for (std::size_t v = 0; v < n; ++v) {
      std::size_t o = v;
      while (o != 0 && cuts[o] == 0) o = problem.input.nodes[o].parent;
      owner[v] = static_cast<std::uint32_t>(o);
      weight[o] += problem.input.nodes[v].bytes;
      ++members[o];
    }
    std::uint32_t count = 0;
    bool feasible = true;
    for (std::size_t o = 0; o < n; ++o) {
      if (weight[o] == 0) continue;
      ++count;
      if (weight[o] > threshold && members[o] != 1) feasible = false;
    }
    if (feasible) best = std::min(best, count);
  }
  return best;
}

// V30: H-KM is exact for P_T and count(T) is non-increasing in T.
TEST(AuditLayout, ThresholdGreedyIsExactForItsProblemAndMonotone) {
  for (std::uint64_t seed = 1; seed <= 1500; ++seed) {
    std::mt19937_64 random(seed * 131);
    auto raw = random_problem(random, 11, 0);
    const auto problem = prepare(raw);
    std::vector<std::uint64_t> thresholds{0, problem.total_bytes};
    for (int i = 0; i < 12; ++i)
      thresholds.push_back(problem.total_bytes == 0 ? 0 : random() % (problem.total_bytes + 1));
    for (const auto& node : raw.nodes) {
      thresholds.push_back(node.bytes);
      if (node.bytes) thresholds.push_back(node.bytes - 1);
    }
    std::sort(thresholds.begin(), thresholds.end());
    std::uint32_t previous = std::numeric_limits<std::uint32_t>::max();
    for (const auto t : thresholds) {
      const auto greedy = evaluate_formula(problem, threshold(problem, t)).stores;
      ASSERT_EQ(greedy, brute_min_count(problem, t)) << "seed " << seed << " T=" << t;
      ASSERT_LE(greedy, previous) << "count(T) increased: seed " << seed << " T=" << t;
      previous = greedy;
    }
  }
}

// km_min returns the smallest feasible threshold; km_max the largest threshold
// with the same attained count; both respect the budget when feasible.
TEST(AuditLayout, KmBisectionEndpoints) {
  for (std::uint64_t seed = 1; seed <= 800; ++seed) {
    std::mt19937_64 random(seed * 977);
    const auto problem = prepare(random_problem(random, 14, 2));
    for (std::uint32_t budget = 0; budget <= problem.positive_nodes + 1; ++budget) {
      const auto lo = km_min(problem, budget);
      const auto hi = km_max(problem, budget);
      if (problem.total_bytes != 0 && budget == 0) {
        ASSERT_EQ(lo.status, "infeasible");
        continue;
      }
      ASSERT_EQ(lo.status, "feasible");
      ASSERT_LE(lo.evaluation.stores, budget == 0 ? 0U : budget);
      if (lo.threshold_bytes > 0) {
        ASSERT_GT(evaluate_formula(problem, threshold(problem, lo.threshold_bytes - 1)).stores, budget)
            << "km_min threshold not minimal, seed " << seed;
      }
      ASSERT_EQ(hi.evaluation.stores, lo.evaluation.stores);
      ASSERT_GE(hi.threshold_bytes, lo.threshold_bytes);
      if (hi.threshold_bytes < problem.total_bytes) {
        ASSERT_NE(evaluate_formula(problem, threshold(problem, hi.threshold_bytes + 1)).stores,
                  hi.evaluation.stores)
            << "km_max threshold not maximal, seed " << seed;
      }
    }
  }
}

// 6.5: the Lagrangian point is optimal for its own at-most budget, and the
// certified bound never exceeds the true optimum at any budget (brute force).
TEST(AuditLayout, GlobalPenaltyOwnBudgetOptimalityAndValidBounds) {
  for (std::uint64_t seed = 1; seed <= 2000; ++seed) {
    std::mt19937_64 random(seed * 7);
    const auto partitions = 1 + random() % 4;
    std::vector<CostCurve> curves;
    for (std::size_t p = 0; p < partitions; ++p) {
      CostCurve curve;
      curve.maximum_count = static_cast<std::uint32_t>(random() % 5);
      curve.scale = 1 + random() % 3;
      curve.certified_complete = true;
      for (std::uint32_t k = 0; k <= curve.maximum_count; ++k)
        curve.values.push_back(random() % 5 == 0 ? infinity : Cost{random() % 1000});
      curves.push_back(curve);
    }
    // Brute force every combination in the common scale.
    Cost common = 1;
    for (const auto& c : curves) {
      Cost a = common, b = c.scale;
      while (b) { const auto r = a % b; a = b; b = r; }
      common = common / a * c.scale;
    }
    std::map<std::uint64_t, Cost> best_at_total;  // exact total -> min objective
    std::function<void(std::size_t, std::uint64_t, Cost)> walk = [&](std::size_t i, std::uint64_t total, Cost sum) {
      if (i == curves.size()) {
        auto [it, inserted] = best_at_total.try_emplace(total, sum);
        if (!inserted) it->second = std::min(it->second, sum);
        return;
      }
      for (std::uint32_t k = 0; k <= curves[i].maximum_count; ++k) {
        if (curves[i].values[k] == infinity) continue;
        walk(i + 1, total + k, sum + curves[i].values[k] * (common / curves[i].scale));
      }
    };
    walk(0, 0, 0);
    for (const Rational lambda : {Rational{0, 1}, Rational{1, 1}, Rational{37, 2}, Rational{250, 1}, Rational{5000, 3}}) {
      const auto point = penalized(curves, lambda);
      if (best_at_total.empty()) {
        ASSERT_EQ(point.status, "infeasible");
        continue;
      }
      ASSERT_EQ(point.status, "feasible");
      const auto multiplier = point.scale / common;
      Cost optimum_at_most = infinity;
      for (const auto& [total, value] : best_at_total)
        if (total <= point.stores) optimum_at_most = std::min(optimum_at_most, value * multiplier);
      ASSERT_TRUE(point.objective == optimum_at_most)
          << "seed " << seed << " lambda " << lambda.numerator << "/" << lambda.denominator;
      for (std::uint64_t budget = 0; budget <= 16; ++budget) {
        Cost truth = infinity;
        for (const auto& [total, value] : best_at_total)
          if (total <= budget) truth = std::min(truth, value * multiplier);
        const auto bound = budget_bound(curves, lambda, budget);
        ASSERT_TRUE(bound.available);
        if (truth == infinity || bound.negative) continue;
        ASSERT_LE(bound.magnitude, truth) << "invalid lower bound, seed " << seed << " B=" << budget;
      }
    }
  }
}

}  // namespace
}  // namespace tiplog::layout
