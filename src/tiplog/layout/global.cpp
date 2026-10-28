#include "tiplog/layout/global.hpp"

#include <algorithm>
#include <limits>
#include <numeric>
#include <stdexcept>

namespace tiplog::layout {
namespace {

Rational reduce_penalty(Rational value) {
  if (value.denominator == 0) {
    throw std::invalid_argument("global penalty has a zero denominator");
  }
  const auto divisor = std::gcd(value.numerator, value.denominator);
  return {value.numerator / divisor, value.denominator / divisor};
}

Cost gcd_scale(Cost left, Cost right) {
  while (right != 0) {
    const Cost remainder = left % right;
    left = right;
    right = remainder;
  }
  return left;
}

Cost common_scale(const std::vector<CostCurve>& curves, Rational penalty) {
  Cost result = penalty.denominator;
  for (const auto& curve : curves) {
    if (curve.scale == 0) {
      throw std::invalid_argument("global cost curve scale must be positive");
    }
    if (curve.scale == infinity) {
      throw std::overflow_error("global cost curve scale reaches reserved infinity");
    }
    result = checked_mul(result / gcd_scale(result, curve.scale), curve.scale);
  }
  return result;
}

bool complete_domain(const CostCurve& curve) {
  const auto required = static_cast<std::uint64_t>(curve.maximum_count) + 1;
  return curve.certified_complete && curve.values.size() == required;
}

} // namespace

GlobalPoint penalized(const std::vector<CostCurve>& curves, Rational lambda) {
  lambda = reduce_penalty(lambda);
  GlobalPoint result;
  result.scale = common_scale(curves, lambda);
  const Cost scaled_lambda = checked_mul(lambda.numerator, result.scale / lambda.denominator);
  result.certified = std::all_of(curves.begin(), curves.end(), complete_domain);
  result.counts.reserve(curves.size());
  for (const auto& curve : curves) {
    const Cost multiplier = result.scale / curve.scale;
    const auto declared_entries = static_cast<std::uint64_t>(curve.maximum_count) + 1;
    const auto entries = std::min<std::uint64_t>(curve.values.size(), declared_entries);
    Cost best_penalized = infinity;
    Cost best_objective = 0;
    std::uint32_t best_count = 0;
    for (std::uint64_t count = 0; count < entries; ++count) {
      const Cost value = curve.values[static_cast<std::size_t>(count)];
      if (value == infinity) {
        continue;
      }
      const Cost objective = checked_mul(value, multiplier);
      const Cost candidate = checked_add(objective, checked_mul(scaled_lambda, count));
      // Ascending actual counts and strict improvement choose fewer stores on
      // every tie. Nominal budget indexes never enter the penalty calculation.
      if (candidate < best_penalized) {
        best_penalized = candidate;
        best_objective = objective;
        best_count = static_cast<std::uint32_t>(count);
      }
    }
    if (best_penalized == infinity) {
      GlobalPoint infeasible;
      infeasible.status = result.certified ? "infeasible" : "no_feasible_incumbent";
      infeasible.scale = result.scale;
      return infeasible;
    }
    result.objective = checked_add(result.objective, best_objective);
    result.penalized = checked_add(result.penalized, best_penalized);
    if (best_count > std::numeric_limits<std::uint64_t>::max() - result.stores) {
      throw std::overflow_error("global store count exceeds uint64");
    }
    result.stores += best_count;
    result.counts.push_back(best_count);
  }
  result.status = result.certified ? "feasible" : "feasible_uncertified";
  return result;
}

BudgetBound budget_bound(const std::vector<CostCurve>& curves, Rational lambda,
                         std::uint64_t budget) {
  const auto point = penalized(curves, lambda);
  BudgetBound result;
  result.scale = point.scale;
  if (!point.certified || point.status != "feasible") {
    return result;
  }
  lambda = reduce_penalty(lambda);
  const Cost scaled_lambda = checked_mul(lambda.numerator, point.scale / lambda.denominator);
  const Cost budget_penalty = checked_mul(scaled_lambda, budget);
  result.available = true;
  if (budget_penalty > point.penalized) {
    result.negative = true;
    result.magnitude = budget_penalty - point.penalized;
  } else {
    result.magnitude = point.penalized - budget_penalty;
  }
  return result;
}

} // namespace tiplog::layout
