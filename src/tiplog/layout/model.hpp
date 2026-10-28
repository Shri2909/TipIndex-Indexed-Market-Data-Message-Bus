#pragma once

#include <cstdint>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

namespace tiplog::layout {
// Approved GCC/Clang extension; all public exact costs retain their scale.
__extension__ typedef unsigned __int128 Cost;
inline constexpr Cost infinity = ~Cost{0};
inline constexpr std::uint32_t no_parent = std::numeric_limits<std::uint32_t>::max();

struct Rational {
  std::uint64_t numerator{0};
  std::uint64_t denominator{1};
};
enum class TermKind { Exact, Subtree };
struct Term { TermKind kind{TermKind::Exact}; std::string path; };
struct Consumer { std::string name; Rational weight{1, 1}; std::vector<Term> terms; };
struct Node { std::string path; std::uint32_t parent{no_parent}; std::uint64_t bytes{0}; };
struct Problem {
  std::vector<Node> nodes;
  std::vector<Consumer> consumers;
  Rational alpha{1, 1}, beta{0, 1}, gamma{0, 1};
};
struct Prepared {
  Problem input;
  std::vector<std::vector<std::uint32_t>> children;
  std::vector<std::uint32_t> postorder;
  std::vector<std::vector<std::uint32_t>> node_classes;
  std::vector<Cost> weights;
  Cost alpha{0}, beta{0}, gamma{0}, scale{1}, objective_upper_bound{0};
  std::uint64_t total_bytes{0};
  std::uint32_t positive_nodes{0};
};
// cuts[v] is the parent edge of v; root cuts[0] must be false. Empty tree: [].
using Layout = std::vector<std::uint8_t>;
struct Evaluation {
  Cost objective{0};
  std::uint32_t stores{0};
  std::vector<std::uint64_t> read_bytes, useful_bytes, waste_bytes;
  std::vector<std::uint32_t> stores_touched;
};
Cost checked_add(Cost a, Cost b);
Cost checked_mul(Cost a, Cost b);
std::string cost_string(Cost value);
Cost parse_cost(std::string_view value);
bool matches(std::string_view path, const Term& term);
// Preparation is outside the exact solver's measured interval and state/work
// limits. Bound its own cross-product traversal and materialized memberships.
struct PreparationLimits {
  std::uint64_t max_work{100000000};
  std::uint64_t max_memberships{2000000};
};
std::uint64_t preparation_work_bound(const Problem& input);
Prepared prepare(const Problem& input, const PreparationLimits& limits = {});
Evaluation evaluate_formula(const Prepared& problem, const Layout& cuts);
Evaluation evaluate_materialized(const Prepared& problem, const Layout& cuts);
Layout baseline(const Prepared& problem);
Layout threshold(const Prepared& problem, std::uint64_t maximum_bytes);
struct HeuristicResult {
  std::string status;
  Layout cuts;
  Evaluation evaluation;
  std::uint64_t threshold_bytes{0};
};
HeuristicResult km_min(const Prepared& problem, std::uint32_t budget);
HeuristicResult km_max(const Prepared& problem, std::uint32_t budget);
} // namespace tiplog::layout
