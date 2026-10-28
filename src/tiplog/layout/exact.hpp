#pragma once
#include "tiplog/layout/model.hpp"

namespace tiplog::layout {
struct Limits {
  std::uint32_t enum_max_edges{22};
  std::uint32_t dp_max_classes{16};
  std::uint64_t max_states{2000000};
  std::uint64_t max_work{2000000};
  std::uint64_t time_limit_ms{500};
};
struct ExactCount {
  bool feasible{false};
  Cost objective{infinity};
  Layout cuts;
};
struct ExactResult {
  std::string status; // solved / infeasible / state_limit / timeout / representation_limit
  std::vector<ExactCount> curve; // exact materialized-store counts, not at-most budgets
  bool complete_domain{false}; // every count 0..positive_nodes was requested and solved
  std::uint64_t states{0}, work{0};
  double seconds{0};
};
ExactResult enumerate(const Prepared& problem, std::uint32_t maximum_stores, const Limits& limits = {});
ExactResult mask_dp(const Prepared& problem, std::uint32_t maximum_stores, const Limits& limits = {});
ExactCount at_most(const ExactResult& result, std::uint32_t budget);
} // namespace tiplog::layout
