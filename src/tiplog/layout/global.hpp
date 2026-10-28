#pragma once

#include "tiplog/layout/model.hpp"

namespace tiplog::layout {

// Actual materialized-store count indexes the curve. At infinity a value is
// either proven infeasible (complete curve) or unknown (incomplete curve).
struct CostCurve {
  std::vector<Cost> values;
  Cost scale{1};
  std::uint32_t maximum_count{0};
  bool certified_complete{false};
};

struct GlobalPoint {
  std::string status;
  Cost objective{0}, penalized{0}, scale{1};
  std::uint64_t stores{0};
  std::vector<std::uint32_t> counts;
  bool certified{false};
};

GlobalPoint penalized(const std::vector<CostCurve>& curves, Rational lambda);

// A signed rational represented without relying on the signed __int128 range.
struct BudgetBound {
  bool available{false}, negative{false};
  Cost magnitude{0}, scale{1};
};

BudgetBound budget_bound(const std::vector<CostCurve>& curves, Rational lambda,
                         std::uint64_t budget);

} // namespace tiplog::layout
