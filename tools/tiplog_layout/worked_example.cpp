#include "tiplog/layout/exact.hpp"

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using namespace tiplog::layout;

void require(bool condition, std::string_view message) {
  if (!condition) throw std::runtime_error(std::string(message));
}

Problem exact_reads(std::vector<Node> nodes) {
  Problem result;
  result.nodes = std::move(nodes);
  for (const auto& node : result.nodes)
    if (node.bytes != 0)
      result.consumers.push_back({node.path, {1, 1}, {{TermKind::Exact, node.path}}});
  return result;
}

Evaluation checked(const Prepared& problem, const Layout& cuts) {
  const auto a = evaluate_formula(problem, cuts);
  const auto b = evaluate_materialized(problem, cuts);
  require(a.objective == b.objective && a.stores == b.stores &&
          a.read_bytes == b.read_bytes && a.useful_bytes == b.useful_bytes &&
          a.waste_bytes == b.waste_bytes && a.stores_touched == b.stores_touched,
          "worked-example evaluators disagree");
  return a;
}

std::uint64_t sum(const std::vector<std::uint64_t>& values) {
  std::uint64_t result = 0;
  for (const auto value : values) {
    require(value <= std::numeric_limits<std::uint64_t>::max() - result, "worked byte sum overflow");
    result += value;
  }
  return result;
}

struct Pair {
  Cost objective{infinity};
  std::uint32_t stores{0};
  Layout left, right;
};

std::optional<Pair> joint(const ExactResult& left, const ExactResult& right, std::uint32_t budget) {
  require(left.status == "solved" && right.status == "solved", "worked exact solver did not finish");
  std::optional<Pair> best;
  for (std::size_t l = 0; l < left.curve.size(); ++l) {
    if (!left.curve[l].feasible) continue;
    for (std::size_t r = 0; r < right.curve.size(); ++r) {
      if (!right.curve[r].feasible || l + r > budget) continue;
      const auto objective = checked_add(left.curve[l].objective, right.curve[r].objective);
      const auto stores = static_cast<std::uint32_t>(l + r);
      if (!best || objective < best->objective || (objective == best->objective && stores < best->stores))
        best = Pair{objective, stores, left.curve[l].cuts, right.curve[r].cuts};
    }
  }
  return best;
}

void compare_curves(const Prepared& problem, const ExactResult& enumeration, const ExactResult& dp) {
  require(enumeration.status == "solved" && dp.status == "solved", "worked solver incomplete");
  require(enumeration.complete_domain && dp.complete_domain, "worked curve domain incomplete");
  require(enumeration.curve.size() == dp.curve.size(), "worked curve sizes disagree");
  for (std::size_t k = 0; k < enumeration.curve.size(); ++k) {
    const auto& a = enumeration.curve[k];
    const auto& b = dp.curve[k];
    require(a.feasible == b.feasible, "worked curve feasibility disagreement");
    if (!a.feasible) continue;
    require(a.objective == b.objective, "worked curve cost disagreement");
    for (const auto* point : {&a, &b}) {
      const auto evaluation = checked(problem, point->cuts);
      require(evaluation.objective == point->objective && evaluation.stores == k,
              "worked exact reconstruction disagreement");
    }
  }
}

struct Row {
  std::string method;
  Layout left, right;
  std::optional<std::uint64_t> threshold;
  Evaluation l, r;
  std::uint64_t waste{0}, read{0}, useful{0};
};

Row row(std::string method, const Prepared& left, const Prepared& right,
        Layout l, Layout r, std::optional<std::uint64_t> threshold = {}) {
  Row result{std::move(method), std::move(l), std::move(r), threshold, {}, {}, 0, 0, 0};
  result.l = checked(left, result.left);
  result.r = checked(right, result.right);
  result.waste = sum(result.l.waste_bytes) + sum(result.r.waste_bytes);
  result.read = sum(result.l.read_bytes) + sum(result.r.read_bytes);
  result.useful = sum(result.l.useful_bytes) + sum(result.r.useful_bytes);
  require(result.read >= result.useful && result.read - result.useful == result.waste,
          "worked read/useful/waste arithmetic disagreement");
  return result;
}

void quote(std::ostream& out, std::string_view value) {
  constexpr char hex[] = "0123456789abcdef";
  out << '"';
  for (const char c : value) {
    const auto byte = static_cast<unsigned char>(c);
    if (c == '"' || c == '\\') out << '\\' << c;
    else if (byte < 32) out << "\\u00" << hex[byte >> 4U] << hex[byte & 15U];
    else out << c;
  }
  out << '"';
}

void cuts(std::ostream& out, const Layout& layout) {
  out << '[';
  bool first = true;
  for (std::size_t node = 1; node < layout.size(); ++node) {
    if (layout[node] == 0) continue;
    if (!first) out << ',';
    first = false;
    out << node;
  }
  out << ']';
}

void nodes(std::ostream& out, const Prepared& problem) {
  out << '[';
  for (std::size_t index = 0; index < problem.input.nodes.size(); ++index) {
    if (index != 0) out << ',';
    const auto& node = problem.input.nodes[index];
    out << "{\"id\":" << index << ",\"parent\":";
    if (node.parent == no_parent) out << "null"; else out << node.parent;
    out << ",\"bytes\":" << node.bytes << ",\"path\":";
    quote(out, node.path);
    out << '}';
  }
  out << ']';
}

void emit(std::ostream& out) {
  const auto left = prepare(exact_reads({{"L", no_parent, 0}, {"L/A", 0, 28500000},
      {"L/A/a1", 1, 10000000}, {"L/A/a2", 1, 2720000000}, {"L/b", 0, 148000}}));
  const auto right = prepare(exact_reads({{"R", no_parent, 0}, {"R/R1", 0, 0},
      {"R/R1/c1", 1, 197}, {"R/R1/c2", 1, 29300}, {"R/R2", 0, 0},
      {"R/R2/d1", 4, 10000}, {"R/R2/d2", 4, 421000}}));
  require(left.total_bytes + right.total_bytes == 2759108497ULL, "worked volume changed");
  Limits limits;
  limits.max_states = 10000000;
  limits.max_work = 100000000;
  limits.time_limit_ms = 60000;
  const auto le = enumerate(left, left.positive_nodes, limits);
  const auto re = enumerate(right, right.positive_nodes, limits);
  const auto ld = mask_dp(left, left.positive_nodes, limits);
  const auto rd = mask_dp(right, right.positive_nodes, limits);
  compare_curves(left, le, ld);
  compare_curves(right, re, rd);
  std::vector<std::optional<Pair>> enum_joint(9), dp_joint(9);
  for (std::uint32_t budget = 1; budget <= 8; ++budget) {
    enum_joint[budget] = joint(le, re, budget);
    dp_joint[budget] = joint(ld, rd, budget);
    require(enum_joint[budget].has_value() == dp_joint[budget].has_value(), "joint feasibility mismatch");
    if (!enum_joint[budget]) continue;
    require(enum_joint[budget]->objective == dp_joint[budget]->objective &&
            enum_joint[budget]->stores == dp_joint[budget]->stores, "joint budget mismatch");
    for (const auto* point : {&*enum_joint[budget], &*dp_joint[budget]}) {
      const auto l = checked(left, point->left), r = checked(right, point->right);
      require(checked_add(l.objective, r.objective) == point->objective &&
              l.stores + r.stores == point->stores, "joint reconstruction mismatch");
    }
  }
  require(!enum_joint[1] && enum_joint[4].has_value(), "joint budget domain mismatch");
  const auto count_at = [&](std::uint64_t threshold_bytes) {
    return checked(left, threshold(left, threshold_bytes)).stores +
           checked(right, threshold(right, threshold_bytes)).stores;
  };
  const auto total = left.total_bytes + right.total_bytes;
  std::uint64_t low = 0, high = total;
  while (low < high) {
    const auto middle = low + (high - low) / 2;
    if (count_at(middle) <= 4) high = middle; else low = middle + 1;
  }
  const auto minimum = low;
  const auto attained = count_at(minimum);
  high = total;
  while (low < high) {
    const auto distance = high - low;
    const auto middle = low + distance / 2 + distance % 2;
    if (count_at(middle) == attained) low = middle; else high = middle - 1;
  }
  const auto maximum = low;
  require(minimum == 28648000 && maximum == 38647999 && attained == 4,
          "worked threshold endpoints changed");
  require(count_at(minimum - 1) == 5 && count_at(maximum + 1) == 3, "worked plateau boundary mismatch");
  std::vector<Row> rows;
  rows.push_back(row("base", left, right, baseline(left), baseline(right)));
  rows.push_back(row("figure", left, right, {0, 1, 0, 1, 1}, Layout(7, 0)));
  rows.push_back(row("km-min", left, right, threshold(left, minimum), threshold(right, minimum), minimum));
  rows.push_back(row("km-max", left, right, threshold(left, maximum), threshold(right, maximum), maximum));
  rows.push_back(row("enum", left, right, enum_joint[4]->left, enum_joint[4]->right));
  rows.push_back(row("dp", left, right, dp_joint[4]->left, dp_joint[4]->right));
  rows.push_back(row("threshold-30000000", left, right, threshold(left, 30000000), threshold(right, 30000000), 30000000));
  rows.push_back(row("threshold-38600000", left, right, threshold(left, 38600000), threshold(right, 38600000), 38600000));
  require(rows[0].waste == 5517460497ULL && rows[0].l.stores == 2 && rows[0].r.stores == 2,
          "worked baseline mismatch");
  for (const auto index : {1U, 3U, 7U}) require(rows[index].waste == 39881491, "worked figure mismatch");
  for (const auto index : {2U, 4U, 5U, 6U}) require(rows[index].waste == 30029491, "worked optimum mismatch");
  require(rows[4].l.stores == 3 && rows[4].r.stores == 1, "joint optimum allocation mismatch");

  out << "{\"status\":\"passed\",\"model\":\"M-store\",\"budget\":4,\"alpha\":\"1/1\","
         "\"beta\":\"0/1\",\"gamma\":\"0/1\",\"scale\":\"1\","
         "\"byte_basis\":\"article decimal labels\",\"left_nodes\":";
  nodes(out, left);
  out << ",\"right_nodes\":";
  nodes(out, right);
  out << ",\"threshold_min\":" << minimum << ",\"threshold_max\":" << maximum << ",\"joint_curves\":[";
  for (std::uint32_t budget = 1; budget <= 8; ++budget) {
    if (budget != 1) out << ',';
    out << "{\"budget\":" << budget << ",\"enum\":";
    if (enum_joint[budget]) quote(out, cost_string(enum_joint[budget]->objective)); else out << "null";
    out << ",\"dp\":";
    if (dp_joint[budget]) quote(out, cost_string(dp_joint[budget]->objective)); else out << "null";
    out << '}';
  }
  out << "],\"rows\":[";
  for (std::size_t index = 0; index < rows.size(); ++index) {
    if (index != 0) out << ',';
    const auto& value = rows[index];
    out << "{\"method\":";
    quote(out, value.method);
    out << ",\"waste\":" << value.waste << ",\"totalread\":" << value.read << ",\"useful\":" << value.useful
        << ",\"stores\":" << value.l.stores + value.r.stores
        << ",\"counts\":[" << value.l.stores << ',' << value.r.stores << "],\"threshold\":";
    if (value.threshold) out << *value.threshold; else out << "null";
    out << ",\"cutsL\":"; cuts(out, value.left);
    out << ",\"cutsR\":"; cuts(out, value.right);
    out << '}';
  }
  out << "]}\n";
  out.flush();
  require(static_cast<bool>(out), "worked-example output failed");
}
} // namespace

int main(int argc, char** argv) {
  try {
    std::string output;
    if (argc == 3 && std::string_view(argv[1]) == "--output") output = argv[2];
    else if (argc != 1) throw std::invalid_argument("usage: tiplog_layout_example [--output PATH]");
    if (output.empty() || output == "-") emit(std::cout);
    else {
      std::ofstream file(output);
      require(static_cast<bool>(file), "cannot open worked-example output");
      emit(file);
      file.close();
      require(static_cast<bool>(file), "worked-example output close failed");
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "tiplog_layout_example: " << error.what() << '\n';
    return 1;
  }
}
