#include "tiplog/layout/model.hpp"

#include <algorithm>
#include <numeric>
#include <stdexcept>
#include <unordered_set>
#include <utility>

namespace tiplog::layout {
namespace {

bool valid_path(std::string_view path) {
  return !path.empty() && path.front() != '/' && path.back() != '/' &&
         path.find("//") == std::string_view::npos;
}

Rational reduced(Rational value) {
  if (value.denominator == 0) {
    throw std::invalid_argument("layout rational has a zero denominator");
  }
  const auto divisor = std::gcd(value.numerator, value.denominator);
  value.numerator /= divisor;
  value.denominator /= divisor;
  return value;
}

Cost gcd_cost(Cost left, Cost right) {
  while (right != 0) {
    const Cost remainder = left % right;
    left = right;
    right = remainder;
  }
  return left;
}

Cost checked_lcm(Cost left, std::uint64_t right) {
  return checked_mul(left / gcd_cost(left, right), right);
}

Cost scaled(Rational value, Cost scale) {
  return checked_mul(value.numerator, scale / value.denominator);
}

std::uint64_t add_bytes(std::uint64_t left, std::uint64_t right) {
  if (right > std::numeric_limits<std::uint64_t>::max() - left) {
    throw std::overflow_error("layout byte volume exceeds uint64");
  }
  return left + right;
}

void validate_layout(const Prepared& problem, const Layout& cuts) {
  if (cuts.size() != problem.input.nodes.size()) {
    throw std::invalid_argument("layout cut vector must have one entry per node");
  }
  if (!cuts.empty() && cuts[0] != 0) {
    throw std::invalid_argument("layout root has no parent edge to cut");
  }
  if (std::any_of(cuts.begin(), cuts.end(), [](std::uint8_t cut) { return cut > 1; })) {
    throw std::invalid_argument("layout cuts must be zero or one");
  }
}

Evaluation empty_evaluation(std::size_t classes) {
  Evaluation result;
  result.read_bytes.resize(classes);
  result.useful_bytes.resize(classes);
  result.waste_bytes.resize(classes);
  result.stores_touched.resize(classes);
  return result;
}

struct ThresholdLayout {
  Layout cuts;
  std::uint32_t stores{0};
};

ThresholdLayout threshold_layout(const Prepared& problem, std::uint64_t maximum_bytes) {
  const auto& nodes = problem.input.nodes;
  ThresholdLayout result{Layout(nodes.size(), 0), 0};
  std::vector<std::uint64_t> residual(nodes.size(), 0);
  for (std::size_t index = 1; index < nodes.size(); ++index) {
    const auto parent = nodes[index].parent;
    if (nodes[index].bytes > maximum_bytes || nodes[parent].bytes > maximum_bytes) {
      result.cuts[index] = 1;
    }
  }
  for (const auto node : problem.postorder) {
    residual[node] = nodes[node].bytes;
    if (nodes[node].bytes > maximum_bytes) {
      continue; // Every incident edge of a hot singleton is already cut.
    }
    std::vector<std::uint32_t> candidates;
    candidates.reserve(problem.children[node].size());
    for (const auto child : problem.children[node]) {
      if (result.cuts[child] == 0) {
        residual[node] = add_bytes(residual[node], residual[child]);
        if (residual[child] != 0) {
          candidates.push_back(child);
        }
      }
    }
    std::sort(candidates.begin(), candidates.end(), [&](auto left, auto right) {
      if (residual[left] != residual[right]) {
        return residual[left] > residual[right];
      }
      return left < right;
    });
    for (const auto child : candidates) {
      if (residual[node] <= maximum_bytes) {
        break;
      }
      result.cuts[child] = 1;
      residual[node] -= residual[child];
    }
    if (residual[node] > maximum_bytes) {
      throw std::logic_error("threshold forest retained an oversized non-hot component");
    }
  }
  for (std::size_t index = 0; index < nodes.size(); ++index) {
    if ((index == 0 || result.cuts[index] != 0) && residual[index] != 0) {
      ++result.stores;
    }
  }
  return result;
}

} // namespace

Cost checked_add(Cost left, Cost right) {
  if (left == infinity || right == infinity || right >= infinity - left) {
    throw std::overflow_error("layout exact addition reaches reserved infinity");
  }
  return left + right;
}

Cost checked_mul(Cost left, Cost right) {
  if (left == infinity || right == infinity ||
      (left != 0 && right > (infinity - 1) / left)) {
    throw std::overflow_error("layout exact multiplication reaches reserved infinity");
  }
  return left * right;
}

std::string cost_string(Cost value) {
  if (value == 0) {
    return "0";
  }
  std::string result;
  while (value != 0) {
    result.push_back(static_cast<char>('0' + static_cast<unsigned>(value % 10)));
    value /= 10;
  }
  std::reverse(result.begin(), result.end());
  return result;
}

Cost parse_cost(std::string_view value) {
  if (value.empty()) {
    throw std::invalid_argument("layout cost must contain decimal digits");
  }
  Cost result = 0;
  for (const char character : value) {
    if (character < '0' || character > '9') {
      throw std::invalid_argument("layout cost must be an unsigned decimal integer");
    }
    result = checked_add(checked_mul(result, 10), static_cast<unsigned>(character - '0'));
  }
  return result;
}

bool matches(std::string_view path, const Term& term) {
  if (term.kind == TermKind::Exact) {
    return path == term.path;
  }
  if (term.kind != TermKind::Subtree) {
    throw std::invalid_argument("unknown layout subscription term kind");
  }
  const std::string_view prefix = term.path;
  return path == prefix ||
         (path.size() > prefix.size() && path.starts_with(prefix) && path[prefix.size()] == '/');
}

std::uint64_t preparation_work_bound(const Problem& input) {
  std::uint64_t per_node = input.consumers.size();
  for (const auto& consumer : input.consumers) {
    if (consumer.terms.size() > UINT64_MAX - per_node)
      throw std::length_error("layout preparation work exceeds uint64 representation");
    per_node += consumer.terms.size();
  }
  const auto positive = static_cast<std::uint64_t>(std::count_if(
      input.nodes.begin(), input.nodes.end(), [](const auto& node) { return node.bytes != 0; }));
  if (per_node != 0 && positive > UINT64_MAX / per_node)
    throw std::length_error("layout preparation work exceeds uint64 representation");
  return positive * per_node;
}

Prepared prepare(const Problem& input, const PreparationLimits& limits) {
  const auto maximum_index = static_cast<std::size_t>(no_parent);
  if (input.nodes.size() > maximum_index || input.consumers.size() > maximum_index) {
    throw std::invalid_argument("layout node or class count exceeds uint32 representation");
  }
  if (preparation_work_bound(input) > limits.max_work)
    throw std::length_error("layout preparation exceeds work budget");
  Prepared result;
  result.input = input; // Retain raw terms and rationals for the independent simulator.
  result.children.resize(input.nodes.size());
  result.node_classes.resize(input.nodes.size());
  std::unordered_set<std::string_view> paths;
  paths.reserve(input.nodes.size());
  std::uint64_t memberships = 0;
  for (std::size_t index = 0; index < input.nodes.size(); ++index) {
    const auto& node = input.nodes[index];
    if (!valid_path(node.path) || !paths.insert(node.path).second) {
      throw std::invalid_argument("layout node paths must be valid and unique");
    }
    result.total_bytes = add_bytes(result.total_bytes, node.bytes);
    if (node.bytes != 0) {
      ++result.positive_nodes;
    }
    if (index == 0) {
      if (node.parent != no_parent) {
        throw std::invalid_argument("layout node zero must be the root");
      }
      continue;
    }
    if (node.parent >= input.nodes.size() || node.parent == index) {
      throw std::invalid_argument("layout non-root node has an invalid parent");
    }
    const auto& parent_path = input.nodes[node.parent].path;
    if (node.path.size() <= parent_path.size() + 1 ||
        !node.path.starts_with(parent_path) || node.path[parent_path.size()] != '/' ||
        node.path.find('/', parent_path.size() + 1) != std::string::npos) {
      throw std::invalid_argument("layout parent must be the immediate topic ancestor");
    }
    result.children[node.parent].push_back(static_cast<std::uint32_t>(index));
  }
  if (!input.nodes.empty()) {
    std::vector<std::uint32_t> order{0};
    std::vector<std::uint8_t> seen(input.nodes.size(), 0);
    seen[0] = 1;
    for (std::size_t index = 0; index < order.size(); ++index) {
      for (const auto child : result.children[order[index]]) {
        if (seen[child] != 0) {
          throw std::invalid_argument("layout tree contains a cycle");
        }
        seen[child] = 1;
        order.push_back(child);
      }
    }
    if (order.size() != input.nodes.size()) {
      throw std::invalid_argument("layout tree must be connected and rooted at node zero");
    }
    result.postorder.assign(order.rbegin(), order.rend());
  }

  const Rational alpha = reduced(input.alpha);
  const Rational beta = reduced(input.beta);
  const Rational gamma = reduced(input.gamma);
  Cost coefficient_scale = 1;
  for (const Rational value : {alpha, beta, gamma}) {
    coefficient_scale = checked_lcm(coefficient_scale, value.denominator);
  }
  Cost weight_scale = 1;
  std::vector<Rational> weights;
  weights.reserve(input.consumers.size());
  for (const auto& consumer : input.consumers) {
    weights.push_back(reduced(consumer.weight));
    weight_scale = checked_lcm(weight_scale, weights.back().denominator);
    for (const auto& term : consumer.terms) {
      if (!valid_path(term.path) ||
          (term.kind != TermKind::Exact && term.kind != TermKind::Subtree)) {
        throw std::invalid_argument("layout consumer term is invalid");
      }
    }
  }
  result.scale = checked_mul(coefficient_scale, weight_scale);
  result.alpha = scaled(alpha, coefficient_scale);
  result.beta = scaled(beta, coefficient_scale);
  result.gamma = checked_mul(scaled(gamma, coefficient_scale), weight_scale);
  Cost total_weight = 0;
  for (const auto value : weights) {
    result.weights.push_back(scaled(value, weight_scale));
    total_weight = checked_add(total_weight, result.weights.back());
  }
  const Cost node_count = input.nodes.size();
  const Cost upper_read_cost = checked_add(checked_mul(result.alpha, result.total_bytes),
                                          checked_mul(result.beta, node_count));
  result.objective_upper_bound = checked_add(checked_mul(upper_read_cost, total_weight),
                                             checked_mul(result.gamma, node_count));
  for (std::size_t index = 0; index < input.nodes.size(); ++index) {
    if (input.nodes[index].bytes == 0) {
      continue;
    }
    for (std::size_t class_index = 0; class_index < input.consumers.size(); ++class_index) {
      const auto& terms = input.consumers[class_index].terms;
      if (std::any_of(terms.begin(), terms.end(), [&](const Term& term) {
            return matches(input.nodes[index].path, term);
          })) {
        if (memberships == limits.max_memberships)
          throw std::length_error("layout preparation exceeds membership budget");
        ++memberships;
        result.node_classes[index].push_back(static_cast<std::uint32_t>(class_index));
      }
    }
  }
  return result;
}

Evaluation evaluate_formula(const Prepared& problem, const Layout& cuts) {
  validate_layout(problem, cuts);
  const auto& nodes = problem.input.nodes;
  Evaluation result = empty_evaluation(problem.weights.size());
  std::vector<std::uint32_t> component(nodes.size(), no_parent);
  std::vector<std::uint64_t> volumes(nodes.size(), 0);
  std::vector<std::vector<std::uint32_t>> readers(nodes.size());
  for (auto iterator = problem.postorder.rbegin(); iterator != problem.postorder.rend(); ++iterator) {
    const auto node = *iterator;
    const auto owner = node == 0 || cuts[node] != 0 ? node : component[nodes[node].parent];
    component[node] = owner;
    volumes[owner] = add_bytes(volumes[owner], nodes[node].bytes);
    for (const auto reader : problem.node_classes[node]) {
      readers[owner].push_back(reader);
      result.useful_bytes[reader] = add_bytes(result.useful_bytes[reader], nodes[node].bytes);
    }
  }
  for (std::size_t index = 0; index < nodes.size(); ++index) {
    if (volumes[index] == 0) {
      continue;
    }
    ++result.stores;
    auto& classes = readers[index];
    std::sort(classes.begin(), classes.end());
    classes.erase(std::unique(classes.begin(), classes.end()), classes.end());
    Cost weight = 0;
    for (const auto reader : classes) {
      weight = checked_add(weight, problem.weights[reader]);
      result.read_bytes[reader] = add_bytes(result.read_bytes[reader], volumes[index]);
      ++result.stores_touched[reader];
    }
    const Cost per_read = checked_add(checked_mul(problem.alpha, volumes[index]), problem.beta);
    const Cost store_cost = checked_add(checked_mul(per_read, weight), problem.gamma);
    result.objective = checked_add(result.objective, store_cost);
  }
  for (std::size_t index = 0; index < problem.weights.size(); ++index) {
    if (result.read_bytes[index] < result.useful_bytes[index]) {
      throw std::logic_error("layout formula read bytes are below useful bytes");
    }
    result.waste_bytes[index] = result.read_bytes[index] - result.useful_bytes[index];
  }
  return result;
}

Evaluation evaluate_materialized(const Prepared& problem, const Layout& cuts) {
  validate_layout(problem, cuts);
  const auto& raw = problem.input;
  Evaluation result = empty_evaluation(raw.consumers.size());
  // Deliberately independent: walk raw parent links for each record instead of
  // using the formula evaluator's traversal, incidence lists or component IDs.
  std::vector<std::vector<std::uint32_t>> stores(raw.nodes.size());
  for (std::size_t index = 0; index < raw.nodes.size(); ++index) {
    if (raw.nodes[index].bytes == 0) {
      continue; // Empty topic names do not materialize stores or cause reads.
    }
    auto owner = static_cast<std::uint32_t>(index);
    while (raw.nodes[owner].parent != no_parent && cuts[owner] == 0) {
      owner = raw.nodes[owner].parent;
    }
    stores[owner].push_back(static_cast<std::uint32_t>(index));
  }
  std::vector<std::uint64_t> store_bytes(raw.nodes.size(), 0);
  for (std::size_t index = 0; index < stores.size(); ++index) {
    for (const auto record : stores[index]) {
      store_bytes[index] = add_bytes(store_bytes[index], raw.nodes[record].bytes);
    }
    if (!stores[index].empty()) {
      ++result.stores;
    }
  }
  result.objective = checked_mul(problem.gamma, result.stores);
  for (std::size_t class_index = 0; class_index < raw.consumers.size(); ++class_index) {
    const auto& consumer = raw.consumers[class_index];
    for (std::size_t store = 0; store < stores.size(); ++store) {
      bool touched = false;
      for (const auto record : stores[store]) {
        const std::string_view path = raw.nodes[record].path;
        bool wanted = false;
        for (const auto& term : consumer.terms) {
          if (term.kind == TermKind::Exact) {
            wanted = path.size() == term.path.size() &&
                     std::equal(path.begin(), path.end(), term.path.begin());
          } else {
            // Compare whole segments, independently of matches()'s prefix test.
            std::size_t actual_begin = 0;
            std::size_t expected_begin = 0;
            wanted = true;
            while (expected_begin < term.path.size()) {
              const auto actual_end = path.find('/', actual_begin);
              const auto expected_end = term.path.find('/', expected_begin);
              const auto actual_length = (actual_end == std::string_view::npos ? path.size() : actual_end) - actual_begin;
              const auto expected_length = (expected_end == std::string::npos ? term.path.size() : expected_end) - expected_begin;
              if (path.substr(actual_begin, actual_length) !=
                  std::string_view(term.path).substr(expected_begin, expected_length)) {
                wanted = false;
                break;
              }
              if (expected_end == std::string::npos) {
                break;
              }
              if (actual_end == std::string_view::npos) {
                wanted = false;
                break;
              }
              actual_begin = actual_end + 1;
              expected_begin = expected_end + 1;
            }
          }
          if (wanted) {
            break; // Union semantics: charge each stored record at most once.
          }
        }
        if (wanted) {
          touched = true;
          result.useful_bytes[class_index] = add_bytes(result.useful_bytes[class_index], raw.nodes[record].bytes);
        }
      }
      if (touched) {
        result.read_bytes[class_index] = add_bytes(result.read_bytes[class_index], store_bytes[store]);
        ++result.stores_touched[class_index];
      }
    }
    result.waste_bytes[class_index] = result.read_bytes[class_index] - result.useful_bytes[class_index];
    const Cost read_cost = checked_add(checked_mul(problem.alpha, result.read_bytes[class_index]),
                                       checked_mul(problem.beta, result.stores_touched[class_index]));
    result.objective = checked_add(result.objective, checked_mul(read_cost, problem.weights[class_index]));
  }
  return result;
}

Layout baseline(const Prepared& problem) {
  Layout cuts(problem.input.nodes.size(), 0);
  if (!cuts.empty()) {
    for (const auto child : problem.children[0]) {
      cuts[child] = 1;
    }
  }
  return cuts;
}

Layout threshold(const Prepared& problem, std::uint64_t maximum_bytes) {
  return threshold_layout(problem, maximum_bytes).cuts;
}

HeuristicResult km_min(const Prepared& problem, std::uint32_t budget) {
  HeuristicResult result;
  if (problem.total_bytes != 0 && budget == 0) {
    result.status = "infeasible";
    return result;
  }
  std::uint64_t lower = 0;
  std::uint64_t upper = problem.total_bytes;
  while (lower < upper) {
    const auto middle = lower + (upper - lower) / 2;
    if (threshold_layout(problem, middle).stores <= budget) {
      upper = middle;
    } else {
      lower = middle + 1;
    }
  }
  result.status = "feasible";
  result.threshold_bytes = lower;
  result.cuts = threshold_layout(problem, lower).cuts;
  result.evaluation = evaluate_formula(problem, result.cuts);
  return result;
}

HeuristicResult km_max(const Prepared& problem, std::uint32_t budget) {
  auto result = km_min(problem, budget);
  if (result.status != "feasible") {
    return result;
  }
  const auto attained_count = result.evaluation.stores;
  std::uint64_t lower = result.threshold_bytes;
  std::uint64_t upper = problem.total_bytes;
  while (lower < upper) {
    const auto difference = upper - lower;
    const auto middle = lower + difference / 2 + difference % 2;
    if (threshold_layout(problem, middle).stores == attained_count) {
      lower = middle;
    } else {
      upper = middle - 1;
    }
  }
  result.threshold_bytes = lower;
  result.cuts = threshold_layout(problem, lower).cuts;
  result.evaluation = evaluate_formula(problem, result.cuts);
  return result;
}

} // namespace tiplog::layout
