#include "tiplog/layout/exact.hpp"

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace tiplog::layout;

struct Summary {
  std::uint64_t requested{10000}, seed{0x5047434335000001ULL}, completed{0};
  std::uint64_t counts{0}, at_most_counts{0}, reconstructions{0}, random_layouts{0};
  std::uint64_t nodes{0}, zero_nodes{0}, empty_trees{0}, classes{0}, baskets{0};
  std::uint64_t exact_terms{0}, subtree_terms{0}, above_root_terms{0}, internal_terms{0};
  std::uint64_t rational_instances{0}, zero_coefficient_instances{0};
  std::uint64_t input_hash{14695981039346656037ULL};
  std::uint64_t result_hash{14695981039346656037ULL};
};

void require(bool condition, std::string_view message) {
  if (!condition) throw std::runtime_error(std::string(message));
}

void digest(std::uint64_t& state, std::uint64_t value) {
  for (unsigned byte = 0; byte < 8; ++byte) {
    state ^= value & 255U;
    state *= 1099511628211ULL;
    value >>= 8U;
  }
}

void digest_text(std::uint64_t& state, std::string_view value) {
  digest(state, value.size());
  for (const char character : value) {
    const auto c = static_cast<unsigned char>(character);
    state ^= c;
    state *= 1099511628211ULL;
  }
}

std::vector<std::string> segments(const std::string& path) {
  std::istringstream stream(path);
  std::vector<std::string> result;
  std::string segment;
  while (std::getline(stream, segment, '/')) result.push_back(segment);
  return result;
}

// This oracle splits raw paths into segment vectors and explicitly constructs
// undirected component adjacency. It uses no production matcher, node incidence,
// traversal, owner map, or objective evaluator.
bool raw_match(const std::string& path, const Consumer& consumer) {
  const auto actual = segments(path);
  for (const auto& term : consumer.terms) {
    const auto expected = segments(term.path);
    if (term.kind == TermKind::Exact && actual == expected) return true;
    if (term.kind == TermKind::Subtree && actual.size() >= expected.size() &&
        std::equal(expected.begin(), expected.end(), actual.begin())) return true;
  }
  return false;
}

Evaluation raw_evaluate(const Prepared& p, const Layout& cuts) {
  require(cuts.size() == p.input.nodes.size(), "oracle layout length");
  if (!cuts.empty()) require(cuts.front() == 0, "oracle root cut");
  Evaluation result;
  const auto b = p.input.consumers.size();
  result.read_bytes.assign(b, 0);
  result.useful_bytes.assign(b, 0);
  result.waste_bytes.assign(b, 0);
  result.stores_touched.assign(b, 0);
  std::vector<std::vector<std::size_t>> adjacent(p.input.nodes.size());
  for (std::size_t v = 1; v < p.input.nodes.size(); ++v) {
    if (cuts[v]) continue;
    const auto parent = static_cast<std::size_t>(p.input.nodes[v].parent);
    adjacent[parent].push_back(v);
    adjacent[v].push_back(parent);
  }
  std::vector<bool> visited(p.input.nodes.size(), false);
  for (std::size_t start = 0; start < p.input.nodes.size(); ++start) {
    if (visited[start]) continue;
    std::vector<std::size_t> component{start};
    visited[start] = true;
    std::uint64_t bytes = 0;
    std::vector<bool> reads(b, false);
    for (std::size_t cursor = 0; cursor < component.size(); ++cursor) {
      const auto v = component[cursor];
      const auto& node = p.input.nodes[v];
      bytes += node.bytes;
      for (std::size_t j = 0; j < b; ++j) {
        if (node.bytes != 0 && raw_match(node.path, p.input.consumers[j])) {
          result.useful_bytes[j] += node.bytes;
          reads[j] = true;
        }
      }
      for (const auto other : adjacent[v]) {
        if (!visited[other]) {
          visited[other] = true;
          component.push_back(other);
        }
      }
    }
    if (bytes == 0) continue;
    ++result.stores;
    result.objective = checked_add(result.objective, p.gamma);
    for (std::size_t j = 0; j < b; ++j) {
      if (!reads[j]) continue;
      result.read_bytes[j] += bytes;
      ++result.stores_touched[j];
      const auto read_price = checked_add(checked_mul(p.alpha, bytes), p.beta);
      result.objective = checked_add(result.objective, checked_mul(read_price, p.weights[j]));
    }
  }
  for (std::size_t j = 0; j < b; ++j)
    result.waste_bytes[j] = result.read_bytes[j] - result.useful_bytes[j];
  return result;
}

void compare_evaluation(const Evaluation& actual, const Evaluation& expected) {
  require(actual.objective == expected.objective, "objective mismatch");
  require(actual.stores == expected.stores, "materialized count mismatch");
  require(actual.read_bytes == expected.read_bytes, "read bytes mismatch");
  require(actual.useful_bytes == expected.useful_bytes, "useful bytes mismatch");
  require(actual.waste_bytes == expected.waste_bytes, "waste bytes mismatch");
  require(actual.stores_touched == expected.stores_touched, "stores touched mismatch");
}

Rational random_rational(std::mt19937_64& random, bool rational, std::uint64_t maximum) {
  return {random() % (maximum + 1), rational ? 1 + random() % 7 : 1};
}

Problem generate(std::uint64_t seed, std::uint64_t index, Summary& summary) {
  std::mt19937_64 random(seed ^ (0x9e3779b97f4a7c15ULL * (index + 1)));
  const bool rational = index % 2 != 0;
  Problem p;
  p.alpha = random_rational(random, rational, 9);
  p.beta = random_rational(random, rational, 13);
  p.gamma = random_rational(random, rational, 17);
  if (index % 11 == 0) p.alpha.numerator = 0;
  if (index % 13 == 0) p.beta.numerator = 0;
  if (index % 17 == 0) p.gamma.numerator = 0;
  if (rational) ++summary.rational_instances;
  if (p.alpha.numerator == 0 || p.beta.numerator == 0 || p.gamma.numerator == 0)
    ++summary.zero_coefficient_instances;
  const auto n = index % 29 == 0 ? std::size_t{0} :
      1 + static_cast<std::size_t>(random() % 12);
  if (n == 0) ++summary.empty_trees;
  if (n != 0) p.nodes.push_back({"market/symbol", no_parent, random() % 24});
  for (std::size_t v = 1; v < n; ++v) {
    // Alternate chains, stars and arbitrary trees to exercise child stages,
    // open/closed states, and subtree-size caps rather than one topology.
    const auto parent = static_cast<std::uint32_t>(index % 7 == 0 ? v - 1 :
        index % 7 == 1 ? 0 : random() % v);
    p.nodes.push_back({p.nodes[parent].path + "/n" + std::to_string(v),
                       parent, random() % 4 == 0 ? 0 : 1 + random() % 23});
  }
  if (index % 31 == 0)
    for (auto& node : p.nodes) node.bytes = 0;
  summary.nodes += p.nodes.size();
  for (const auto& node : p.nodes)
    if (node.bytes == 0) ++summary.zero_nodes;
  const auto b = static_cast<std::size_t>(random() % 5);
  for (std::size_t j = 0; j < b; ++j) {
    Consumer consumer{"class" + std::to_string(j), random_rational(random, rational, 7), {}};
    const auto chosen_path = [&]() -> std::string {
      return n == 0 ? "market/symbol/absent" : p.nodes[static_cast<std::size_t>(random() % n)].path;
    };
    switch ((index + j) % 6) {
    case 0:
      consumer.terms = {{TermKind::Subtree, "market"}};
      break;
    case 1:
      consumer.terms = {{TermKind::Exact, chosen_path()}};
      break;
    case 2:
      consumer.terms = {{TermKind::Subtree, chosen_path()}};
      break;
    case 3: {
      const auto path = chosen_path();
      consumer.terms = {{TermKind::Exact, path}, {TermKind::Exact, chosen_path()},
                        {TermKind::Subtree, path}, {TermKind::Exact, path}};
      break;
    }
    case 4:
      consumer.terms = {{TermKind::Exact, "market/symbol/absent"},
                        {TermKind::Subtree, "market/symbolx"}};
      break;
    default:
      consumer.terms = {{TermKind::Exact, chosen_path()}, {TermKind::Subtree, "market"}};
      break;
    }
    if (consumer.terms.size() > 1) ++summary.baskets;
    for (const auto& term : consumer.terms) {
      if (term.kind == TermKind::Exact) ++summary.exact_terms;
      else ++summary.subtree_terms;
      if (term.path == "market") ++summary.above_root_terms;
      for (std::size_t v = 0; v < n; ++v) {
        if (p.nodes[v].path != term.path) continue;
        if (std::any_of(p.nodes.begin(), p.nodes.end(), [v](const Node& node) {
              return node.parent == v;
            })) ++summary.internal_terms;
      }
    }
    p.consumers.push_back(std::move(consumer));
  }
  summary.classes += p.consumers.size();
  return p;
}

void hash_problem(const Problem& p, std::uint64_t& hash) {
  const auto rational = [&](Rational value) {
    digest(hash, value.numerator); digest(hash, value.denominator);
  };
  rational(p.alpha); rational(p.beta); rational(p.gamma);
  digest(hash, p.nodes.size());
  for (const auto& node : p.nodes) {
    digest_text(hash, node.path); digest(hash, node.parent); digest(hash, node.bytes);
  }
  digest(hash, p.consumers.size());
  for (const auto& consumer : p.consumers) {
    digest_text(hash, consumer.name); rational(consumer.weight);
    digest(hash, consumer.terms.size());
    for (const auto& term : consumer.terms) {
      digest(hash, term.kind == TermKind::Exact ? 0 : 1); digest_text(hash, term.path);
    }
  }
}

void check_layout(const Prepared& p, const Layout& cuts, Summary& summary) {
  const auto raw = raw_evaluate(p, cuts);
  compare_evaluation(evaluate_formula(p, cuts), raw);
  compare_evaluation(evaluate_materialized(p, cuts), raw);
  digest(summary.result_hash, raw.stores);
  digest_text(summary.result_hash, cost_string(raw.objective));
  for (const auto cut : cuts) digest(summary.result_hash, cut);
}

void check_one(Summary& summary, std::uint64_t index) {
  const auto raw = generate(summary.seed, index, summary);
  hash_problem(raw, summary.input_hash);
  const auto p = prepare(raw);
  Limits limits;
  limits.enum_max_edges = 22;
  limits.dp_max_classes = 16;
  limits.max_states = 10000000;
  limits.max_work = 100000000;
  limits.time_limit_ms = 60000;
  const auto enumeration = enumerate(p, p.positive_nodes, limits);
  const auto dp = mask_dp(p, p.positive_nodes, limits);
  require(enumeration.status == "solved", "ENUM did not solve entire requested domain");
  require(dp.status == "solved", "MASK-DP did not solve entire requested domain");
  require(enumeration.complete_domain && dp.complete_domain, "incomplete domain");
  require(enumeration.curve.size() == dp.curve.size(), "curve size mismatch");
  require(enumeration.curve.size() == static_cast<std::size_t>(p.positive_nodes) + 1,
          "curve excludes a materialized count");
  for (std::size_t k = 0; k < enumeration.curve.size(); ++k) {
    const auto& expected = enumeration.curve[k];
    const auto& actual = dp.curve[k];
    require(actual.feasible == expected.feasible, "exact-count feasibility mismatch");
    digest(summary.result_hash, k); digest(summary.result_hash, actual.feasible ? 1 : 0);
    ++summary.counts;
    if (actual.feasible) {
      require(actual.objective == expected.objective, "exact-count optimum mismatch");
      for (const auto* point : {&expected, &actual}) {
        const auto evaluated = raw_evaluate(p, point->cuts);
        require(evaluated.stores == k, "reconstructed exact count mismatch");
        require(evaluated.objective == point->objective, "reconstructed objective mismatch");
        check_layout(p, point->cuts, summary);
        ++summary.reconstructions;
      }
    }
    const auto a = at_most(enumeration, static_cast<std::uint32_t>(k));
    const auto b = at_most(dp, static_cast<std::uint32_t>(k));
    require(a.feasible == b.feasible, "at-most feasibility mismatch");
    if (a.feasible) require(a.objective == b.objective, "at-most optimum mismatch");
    ++summary.at_most_counts;
  }
  // Evaluator agreement also includes layouts unrelated to an optimum, where
  // duplicate basket terms and zero-weight consumer reads still matter.
  std::mt19937_64 random(summary.seed ^ (index * 0xd1b54a32d192ed03ULL));
  for (unsigned sample = 0; sample < 2; ++sample) {
    Layout cuts(raw.nodes.size(), 0);
    for (std::size_t v = 1; v < cuts.size(); ++v)
      cuts[v] = static_cast<std::uint8_t>(random() & 1U);
    check_layout(p, cuts, summary);
    ++summary.random_layouts;
  }
  ++summary.completed;
}

std::string escape_json(std::string_view value) {
  std::ostringstream output;
  for (const char character : value) {
    const auto c = static_cast<unsigned char>(character);
    switch (c) {
    case '"': output << "\\\""; break;
    case '\\': output << "\\\\"; break;
    case '\n': output << "\\n"; break;
    case '\r': output << "\\r"; break;
    case '\t': output << "\\t"; break;
    default:
      if (c < 32) output << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c);
      else output << static_cast<char>(c);
    }
  }
  return output.str();
}

std::string hexadecimal(std::uint64_t value) {
  std::ostringstream output;
  output << std::hex << std::setw(16) << std::setfill('0') << value;
  return output.str();
}

std::string report(const Summary& s, std::string_view error) {
  std::ostringstream out;
  out << "{\n  \"schema\": \"tiplog-layout-cc5-v1\",\n"
      << "  \"status\": \"" << (error.empty() ? "passed" : "failed") << "\",\n"
      << "  \"seed\": " << s.seed << ",\n"
      << "  \"rng\": \"mt19937_64; per-instance seed xor golden-ratio*(index+1)\",\n"
      << "  \"requested_instances\": " << s.requested << ",\n"
      << "  \"completed_instances\": " << s.completed << ",\n"
      << "  \"maximum_nodes\": 12,\n  \"maximum_classes\": 4,\n"
      << "  \"exact_count_comparisons\": " << s.counts << ",\n"
      << "  \"at_most_comparisons\": " << s.at_most_counts << ",\n"
      << "  \"reconstructed_layouts_checked\": " << s.reconstructions << ",\n"
      << "  \"random_layouts_checked\": " << s.random_layouts << ",\n"
      << "  \"nodes\": " << s.nodes << ",\n  \"zero_volume_nodes\": " << s.zero_nodes << ",\n"
      << "  \"empty_trees\": " << s.empty_trees << ",\n  \"consumer_classes\": " << s.classes << ",\n"
      << "  \"basket_classes\": " << s.baskets << ",\n  \"exact_terms\": " << s.exact_terms << ",\n"
      << "  \"subtree_terms\": " << s.subtree_terms << ",\n"
      << "  \"above_root_terms\": " << s.above_root_terms << ",\n"
      << "  \"internal_node_terms\": " << s.internal_terms << ",\n"
      << "  \"rational_instances\": " << s.rational_instances << ",\n"
      << "  \"zero_coefficient_instances\": " << s.zero_coefficient_instances << ",\n"
      << "  \"mismatches\": " << (error.empty() ? 0 : 1) << ",\n"
      << "  \"input_fnv1a64\": \"" << hexadecimal(s.input_hash) << "\",\n"
      << "  \"result_fnv1a64\": \"" << hexadecimal(s.result_hash) << "\",\n"
      << "  \"limits\": {\"enum_max_edges\":22,\"dp_max_classes\":16,"
         "\"max_states\":10000000,\"max_work\":100000000,\"time_limit_ms\":60000},\n"
      << "  \"failure_instance_index\": ";
  if (error.empty()) out << "null"; else out << s.completed;
  out << ",\n  \"error\": \"" << escape_json(error) << "\"\n}\n";
  return out.str();
}

std::uint64_t number(const std::string& value) {
  require(!value.empty() && value.front() != '-', "expected unsigned number");
  std::size_t consumed = 0;
  const auto parsed = std::stoull(value, &consumed, 0);
  require(consumed == value.size(), "invalid unsigned number");
  return parsed;
}
} // namespace

int main(int argc, char** argv) {
  Summary summary;
  std::string output_path;
  try {
    for (int argument = 1; argument < argc; ++argument) {
      const std::string option = argv[argument];
      if (option == "--help") {
        std::cout << "usage: tiplog_layout_cc5 [--instances N] [--seed N] [--output path]\n";
        return 0;
      }
      require(argument + 1 < argc, "option requires value");
      const std::string value = argv[++argument];
      if (option == "--instances") summary.requested = number(value);
      else if (option == "--seed") summary.seed = number(value);
      else if (option == "--output") output_path = value;
      else throw std::runtime_error("unknown option: " + option);
    }
    require(summary.requested != 0, "instances must be positive");
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 2;
  }
  std::string failure;
  try {
    for (std::uint64_t index = 0; index < summary.requested; ++index) check_one(summary, index);
  } catch (const std::exception& error) {
    failure = error.what();
  }
  const auto json = report(summary, failure);
  if (!output_path.empty()) {
    std::ofstream output(output_path);
    output << json;
    output.flush();
    output.close();
    if (!output) {
      std::cerr << "cannot write CC5 summary: " << output_path << '\n';
      return 2;
    }
  }
  std::cout << json << std::flush;
  if (!std::cout) {
    std::cerr << "cannot write CC5 stdout summary\n";
    return 2;
  }
  return failure.empty() ? 0 : 1;
}
