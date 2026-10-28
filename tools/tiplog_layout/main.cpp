#include "tiplog/layout/exact.hpp"
#include "tiplog/layout/global.hpp"
#include "tiplog/layout/model.hpp"
#include "input_budget.hpp"
#include "../file_safety.hpp"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
namespace layout = tiplog::layout;
using layout::Cost;

std::uint64_t number(std::string_view text) {
  if (text.empty() || std::any_of(text.begin(), text.end(), [](char c) { return c < '0' || c > '9'; }))
    throw std::invalid_argument("expected a nonnegative decimal uint64 integer");
  std::uint64_t value = 0;
  const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value);
  if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size())
    throw std::invalid_argument("integer exceeds uint64 representation");
  return value;
}

std::uint32_t number32(std::string_view text) {
  const auto value = number(text);
  if (value > std::numeric_limits<std::uint32_t>::max())
    throw std::invalid_argument("integer exceeds uint32 representation");
  return static_cast<std::uint32_t>(value);
}

layout::Rational rational(std::string_view text) {
  const auto slash = text.find('/');
  layout::Rational value;
  value.numerator = number(text.substr(0, slash));
  value.denominator = slash == std::string_view::npos ? 1 : number(text.substr(slash + 1));
  if (value.denominator == 0) throw std::invalid_argument("rational denominator must be positive");
  const auto divisor = std::gcd(value.numerator, value.denominator);
  return {value.numerator / divisor, value.denominator / divisor};
}

std::string rational_string(layout::Rational value) {
  return std::to_string(value.numerator) + "/" + std::to_string(value.denominator);
}

std::vector<std::string> split(std::string_view text, char delimiter) {
  std::vector<std::string> values;
  std::size_t begin = 0;
  while (true) {
    const auto end = text.find(delimiter, begin);
    values.emplace_back(text.substr(begin, end == std::string_view::npos ? end : end - begin));
    if (end == std::string_view::npos) return values;
    begin = end + 1;
  }
}

void quoted(std::ostream& out, std::string_view text) {
  constexpr char hex[] = "0123456789abcdef";
  out << '"';
  for (const char character : text) {
    const auto byte = static_cast<unsigned char>(character);
    if (character == '"' || character == '\\') out << '\\' << character;
    else if (byte < 32) out << "\\u00" << hex[byte >> 4U] << hex[byte & 15U];
    else out << character;
  }
  out << '"';
}

class Json {
 public:
  explicit Json(std::ostream& stream) : out(stream) { out << '{'; }
  void key(std::string_view name) {
    if (!first) out << ',';
    first = false;
    quoted(out, name);
    out << ':';
  }
  void text(std::string_view name, std::string_view value) { key(name); quoted(out, value); }
  void integer(std::string_view name, std::uint64_t value) { key(name); out << value; }
  void boolean(std::string_view name, bool value) { key(name); out << (value ? "true" : "false"); }
  void cost(std::string_view name, Cost value) { text(name, layout::cost_string(value)); }
  void null(std::string_view name) { key(name); out << "null"; }
  void real(std::string_view name, double value) { key(name); out << std::setprecision(17) << value; }
  template<class T> void numbers(std::string_view name, const std::vector<T>& values) {
    key(name);
    out << '[';
    bool initial = true;
    for (const auto value : values) {
      if (!initial) out << ',';
      initial = false;
      out << static_cast<std::uint64_t>(value);
    }
    out << ']';
  }
  void strings(std::string_view name, const std::vector<std::string>& values) {
    key(name);
    out << '[';
    bool initial = true;
    for (const auto& value : values) {
      if (!initial) out << ',';
      initial = false;
      quoted(out, value);
    }
    out << ']';
  }
  void curve(const layout::ExactResult& result) {
    key("curve");
    out << '[';
    for (std::size_t count = 0; count < result.curve.size(); ++count) {
      if (count != 0) out << ',';
      if (result.curve[count].feasible) quoted(out, layout::cost_string(result.curve[count].objective));
      else out << "null";
    }
    out << ']';
  }
  void end() { out << "}\n"; }
 private:
  std::ostream& out;
  bool first{true};
};

struct Options {
  std::string input, output{"-"}, global_curves;
  std::vector<std::string> methods{"base", "km-min", "km-max", "enum", "dp"};
  std::vector<layout::Rational> multipliers{{0, 1}};
  std::vector<std::uint64_t> budgets;
  layout::Limits limits;
  layout::cli::InputLimits input_limits;
  bool full_curves{false}, help{false};
};

Options options(int argc, char** argv) {
  Options result;
  bool explicit_multipliers = false, explicit_budgets = false;
  std::set<std::string> seen;
  for (int index = 1; index < argc; ++index) {
    const std::string arg = argv[index];
    if (!seen.insert(arg).second) throw std::invalid_argument("duplicate option: " + arg);
    if (arg == "--help") { result.help = true; continue; }
    if (arg == "--full-curves") { result.full_curves = true; continue; }
    if (index + 1 >= argc) throw std::invalid_argument("missing value for " + arg);
    const std::string value = argv[++index];
    if (arg == "--input") result.input = value;
    else if (arg == "--output") result.output = value;
    else if (arg == "--global-curves") result.global_curves = value;
    else if (arg == "--methods") result.methods = split(value, ',');
    else if (arg == "--enum-max-edges") result.limits.enum_max_edges = number32(value);
    else if (arg == "--dp-max-classes") result.limits.dp_max_classes = number32(value);
    else if (arg == "--max-states") result.limits.max_states = number(value);
    else if (arg == "--max-work") result.limits.max_work = number(value);
    else if (arg == "--max-input-bytes") result.input_limits.max_bytes = number(value);
    else if (arg == "--max-curve-entries") result.input_limits.max_curve_entries = number(value);
    else if (arg == "--max-prepare-work") result.input_limits.preparation.max_work = number(value);
    else if (arg == "--max-prepared-entries") result.input_limits.preparation.max_memberships = number(value);
    else if (arg == "--time-limit-ms") result.limits.time_limit_ms = number(value);
    else if (arg == "--multipliers") {
      explicit_multipliers = true;
      result.multipliers.clear();
      for (const auto& item : split(value, ',')) result.multipliers.push_back(rational(item));
    } else if (arg == "--budgets") {
      explicit_budgets = true;
      for (const auto& item : split(value, ',')) result.budgets.push_back(number(item));
    } else throw std::invalid_argument("unknown option: " + arg);
  }
  if (result.help) return result;
  if (result.input.empty() == result.global_curves.empty())
    throw std::invalid_argument("provide exactly one of --input and --global-curves");
  if ((!result.global_curves.empty() && result.full_curves) ||
      (result.global_curves.empty() && (explicit_multipliers || explicit_budgets)))
    throw std::invalid_argument("--full-curves is a case option; multipliers/budgets are global options");
  const std::set<std::string> valid{"base", "km-min", "km-max", "enum", "dp"};
  std::set<std::string> unique;
  for (const auto& method : result.methods) {
    if (!valid.contains(method) || !unique.insert(method).second)
      throw std::invalid_argument("unknown or duplicate method: " + method);
  }
  const auto& source = result.input.empty() ? result.global_curves : result.input;
  if (source != "-" && result.output != "-")
    tiplog::cli::require_distinct_files(source, result.output);
  return result;
}

void fields(const std::vector<std::string>& row, std::size_t expected) {
  if (row.size() != expected) throw std::invalid_argument("wrong TSV field count for " + row.front());
}

layout::Evaluation verified(const layout::Prepared& problem, const layout::Layout& cuts) {
  auto formula = layout::evaluate_formula(problem, cuts);
  const auto materialized = layout::evaluate_materialized(problem, cuts);
  if (formula.objective != materialized.objective || formula.stores != materialized.stores ||
      formula.read_bytes != materialized.read_bytes || formula.useful_bytes != materialized.useful_bytes ||
      formula.waste_bytes != materialized.waste_bytes || formula.stores_touched != materialized.stores_touched)
    throw std::logic_error("formula and independent materialization disagree");
  return formula;
}

Cost gcd_cost(Cost a, Cost b) {
  while (b != 0) { const auto remainder = a % b; a = b; b = remainder; }
  return a;
}

std::pair<Cost, Cost> active_weight(const layout::Prepared& problem) {
  Cost denominator = 1;
  for (const auto& consumer : problem.input.consumers) {
    const auto divisor = std::gcd(consumer.weight.numerator, consumer.weight.denominator);
    const Cost current = consumer.weight.denominator / divisor;
    denominator = layout::checked_mul(denominator / gcd_cost(denominator, current), current);
  }
  std::vector<bool> active(problem.weights.size(), false);
  for (const auto& classes : problem.node_classes)
    for (const auto index : classes) active[index] = true;
  Cost total = 0;
  for (std::size_t index = 0; index < active.size(); ++index)
    if (active[index]) total = layout::checked_add(total, problem.weights[index]);
  return {total, denominator};
}

void metrics(Json& row, const layout::Evaluation& evaluation, const layout::Layout& cuts) {
  row.cost("objective", evaluation.objective);
  row.integer("stores", evaluation.stores);
  row.numbers("read_bytes", evaluation.read_bytes);
  row.numbers("useful_bytes", evaluation.useful_bytes);
  row.numbers("waste_bytes", evaluation.waste_bytes);
  row.numbers("stores_touched", evaluation.stores_touched);
  std::vector<std::uint32_t> ids;
  for (std::size_t index = 1; index < cuts.size(); ++index)
    if (cuts[index] != 0) ids.push_back(static_cast<std::uint32_t>(index));
  row.numbers("cuts", ids);
}

void no_metrics(Json& row) {
  for (const auto name : {"objective", "stores", "read_bytes", "useful_bytes", "waste_bytes", "stores_touched", "cuts"})
    row.null(name);
}

void run_case(std::ostream& out, const std::string& id, std::uint32_t budget,
              const layout::Problem& input, const Options& config) {
  const auto problem = layout::prepare(input, config.input_limits.preparation);
  const auto [weight, weight_scale] = active_weight(problem);
  for (const auto& method : config.methods) {
    const auto start = std::chrono::steady_clock::now();
    std::optional<layout::ExactResult> exact;
    std::optional<layout::Layout> chosen;
    std::string status, solver_status;
    std::optional<std::uint64_t> threshold;
    if (method == "base") {
      chosen = layout::baseline(problem);
      status = "feasible";
      solver_status = "constructed";
    } else if (method == "km-min" || method == "km-max") {
      const auto heuristic = method == "km-min" ? layout::km_min(problem, budget) : layout::km_max(problem, budget);
      status = heuristic.status;
      solver_status = heuristic.status;
      if (heuristic.status == "feasible") { chosen = heuristic.cuts; threshold = heuristic.threshold_bytes; }
    } else {
      const auto maximum = config.full_curves ? problem.positive_nodes : budget;
      exact = method == "enum" ? layout::enumerate(problem, maximum, config.limits)
                                : layout::mask_dp(problem, maximum, config.limits);
      solver_status = exact->status;
      status = exact->status;
      if (exact->status == "solved") {
        const auto best = layout::at_most(*exact, budget);
        status = best.feasible ? "feasible" : "infeasible";
        if (best.feasible) chosen = best.cuts;
      }
    }
    const auto solver_elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    std::optional<layout::Evaluation> evaluation;
    if (chosen) {
      evaluation = verified(problem, *chosen);
      if (evaluation->stores > budget) status = "infeasible_budget";
    }
    const auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    Json row(out);
    row.text("type", "layout");
    row.text("id", id);
    row.integer("budget", budget);
    row.text("method", method);
    row.text("status", status);
    row.text("solver_status", solver_status);
    row.boolean("exact", exact && exact->status == "solved" && chosen.has_value() && status == "feasible");
    row.cost("scale", problem.scale);
    row.integer("nodes", problem.input.nodes.size());
    row.integer("classes", problem.weights.size());
    row.integer("positive_nodes", problem.positive_nodes);
    row.integer("total_bytes", problem.total_bytes);
    row.cost("active_class_weight", weight);
    row.cost("class_weight_scale", weight_scale);
    row.text("alpha", rational_string(input.alpha));
    row.text("beta", rational_string(input.beta));
    row.text("gamma", rational_string(input.gamma));
    if (threshold) row.integer("threshold", *threshold); else row.null("threshold");
    row.integer("work", exact ? exact->work : 0);
    row.integer("states", exact ? exact->states : 0);
    row.real("seconds", exact ? exact->seconds : solver_elapsed);
    row.real("verified_seconds", elapsed);
    if (evaluation) metrics(row, *evaluation, *chosen); else no_metrics(row);
    if (exact) {
      row.curve(*exact);
      row.boolean("complete_domain", exact->complete_domain);
    }
    row.end();
  }
  out.flush();
  if (!out) throw std::runtime_error("failed writing output");
}

struct Context { std::uint64_t line{0}; std::string id; };

void cases(std::istream& in, std::ostream& out, const Options& config, Context& context) {
  std::set<std::string> ids;
  layout::Problem current;
  std::uint32_t budget = 0;
  bool open = false, cost_seen = false;
  std::string line;
  layout::cli::InputBudget input_budget(config.input_limits);
  while (input_budget.getline(in, line)) {
    ++context.line;
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.empty() || line.front() == '#') continue;
    const auto row = split(line, '\t');
    if (row[0] == "CASE") {
      fields(row, 3);
      if (open) throw std::invalid_argument("CASE encountered before END");
      if (row[1].empty() || !ids.insert(row[1]).second) throw std::invalid_argument("empty or duplicate CASE id");
      context.id = row[1];
      budget = number32(row[2]);
      current = {};
      open = true;
      cost_seen = false;
      continue;
    }
    if (!open) throw std::invalid_argument("record outside CASE");
    if (row[0] == "COST") {
      fields(row, 4);
      if (cost_seen) throw std::invalid_argument("duplicate COST");
      current.alpha = rational(row[1]); current.beta = rational(row[2]); current.gamma = rational(row[3]);
      cost_seen = true;
    } else if (row[0] == "NODE") {
      fields(row, 4);
      current.nodes.push_back({row[3], row[1] == "-" ? layout::no_parent : number32(row[1]), number(row[2])});
    } else if (row[0] == "CLASS") {
      fields(row, 3);
      current.consumers.push_back({row[1], rational(row[2]), {}});
    } else if (row[0] == "TERM") {
      fields(row, 3);
      if (current.consumers.empty()) throw std::invalid_argument("TERM requires a preceding CLASS");
      if (row[1] != "E" && row[1] != "S") throw std::invalid_argument("TERM kind must be E or S");
      current.consumers.back().terms.push_back({row[1] == "E" ? layout::TermKind::Exact : layout::TermKind::Subtree, row[2]});
    } else if (row[0] == "END") {
      fields(row, 1);
      if (!cost_seen) throw std::invalid_argument("CASE requires an explicit COST");
      input_budget.prepare(current);
      run_case(out, context.id, budget, current, config);
      open = false;
      context.id.clear();
    } else throw std::invalid_argument("unknown CASE directive: " + row[0]);
  }
  if (in.bad()) throw std::runtime_error("failed reading input");
  if (open) throw std::invalid_argument("unterminated CASE at end of input");
}

struct GlobalInput { std::vector<layout::CostCurve> curves; std::vector<std::string> ids; };

GlobalInput read_curves(std::istream& in, const Options& config, Context& context) {
  GlobalInput result;
  std::set<std::string> ids;
  std::set<std::uint32_t> points;
  std::optional<layout::CostCurve> current;
  std::string line;
  layout::cli::InputBudget input_budget(config.input_limits);
  while (input_budget.getline(in, line)) {
    ++context.line;
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.empty() || line.front() == '#') continue;
    const auto row = split(line, '\t');
    if (row[0] == "CURVE") {
      fields(row, 5);
      if (current) throw std::invalid_argument("CURVE encountered before END");
      if (row[1].empty() || !ids.insert(row[1]).second) throw std::invalid_argument("empty or duplicate CURVE id");
      context.id = row[1];
      current.emplace();
      current->scale = layout::parse_cost(row[2]);
      if (current->scale == 0) throw std::invalid_argument("CURVE scale must be positive");
      current->maximum_count = number32(row[3]);
      if (row[4] != "0" && row[4] != "1") throw std::invalid_argument("CURVE certified flag must be 0 or 1");
      current->certified_complete = row[4] == "1";
      const auto entries = static_cast<std::uint64_t>(current->maximum_count) + 1;
      if (entries > config.limits.max_states || entries > current->values.max_size())
        throw std::invalid_argument("CURVE entries exceed --max-states or representation");
      input_budget.curve(entries);
      current->values.assign(static_cast<std::size_t>(entries), layout::infinity);
      points.clear();
    } else if (row[0] == "POINT") {
      fields(row, 3);
      if (!current) throw std::invalid_argument("POINT outside CURVE");
      const auto count = number32(row[1]);
      if (count > current->maximum_count || !points.insert(count).second)
        throw std::invalid_argument("POINT count outside domain or duplicated");
      // A missing/null point in a certified full domain denotes proven
      // infeasibility; in an incomplete curve it denotes an unknown value.
      if (row[2] != "null") current->values[count] = layout::parse_cost(row[2]);
    } else if (row[0] == "END") {
      fields(row, 1);
      if (!current) throw std::invalid_argument("END outside CURVE");
      result.ids.push_back(context.id);
      result.curves.push_back(std::move(*current));
      current.reset();
      context.id.clear();
    } else throw std::invalid_argument("unknown global directive: " + row[0]);
  }
  if (in.bad()) throw std::runtime_error("failed reading global input");
  if (current) throw std::invalid_argument("unterminated CURVE at end of input");
  return result;
}

bool proven_infeasible(const GlobalInput& input) {
  return std::any_of(input.curves.begin(), input.curves.end(), [](const auto& curve) {
    return curve.certified_complete && std::none_of(curve.values.begin(), curve.values.end(),
           [](Cost value) { return value != layout::infinity; });
  });
}

void global(std::istream& in, std::ostream& out, const Options& config, Context& context) {
  const auto input = read_curves(in, config, context);
  for (const auto lambda : config.multipliers) {
    const auto point = layout::penalized(input.curves, lambda);
    auto status = point.status;
    const bool feasible = status == "feasible" || status == "feasible_uncertified";
    if (status == "infeasible" && !proven_infeasible(input)) status = "no_feasible_incumbent";
    Json row(out);
    row.text("type", "global_point");
    row.text("method", "global");
    row.text("lambda", rational_string(lambda));
    row.text("status", status);
    row.boolean("exact", point.certified);
    row.boolean("certified", point.certified);
    row.cost("scale", point.scale);
    row.strings("partitions", input.ids);
    if (feasible) {
      row.cost("objective", point.objective);
      row.cost("penalized", point.penalized);
      row.integer("stores", point.stores);
      row.numbers("counts", point.counts);
    } else {
      row.null("objective"); row.null("penalized"); row.null("stores"); row.null("counts");
    }
    row.end();
    for (const auto budget : config.budgets) {
      const auto bound = layout::budget_bound(input.curves, lambda, budget);
      Json bound_row(out);
      bound_row.text("type", "global_budget_bound");
      bound_row.text("method", "global");
      bound_row.text("lambda", rational_string(lambda));
      bound_row.integer("budget", budget);
      bound_row.text("status", bound.available ? "certified_lower_bound" : "unavailable");
      bound_row.boolean("available", bound.available);
      bound_row.boolean("certified", bound.available);
      bound_row.cost("scale", bound.scale);
      if (bound.available) {
        const auto magnitude = layout::cost_string(bound.magnitude);
        bound_row.text("bound", bound.negative ? "-" + magnitude : magnitude);
      } else bound_row.null("bound");
      bound_row.end();
    }
    out.flush();
    if (!out) throw std::runtime_error("failed writing global output");
  }
}

void error_row(std::ostream& out, const Context& context, const std::exception& error) {
  Json row(out);
  row.text("type", "error"); row.text("status", "error"); row.text("id", context.id);
  row.integer("line", context.line); row.text("message", error.what()); row.end(); out.flush();
}
} // namespace

int main(int argc, char** argv) {
  Context context;
  std::ofstream output_file;
  std::ostream* output = &std::cout;
  try {
    const auto config = options(argc, argv);
    if (config.help) {
      std::cout << "tiplog_layout --input cases.tsv --output rows.jsonl [--methods base,km-min,km-max,enum,dp] "
                   "[--full-curves] [--enum-max-edges N] [--dp-max-classes N] [--max-states N] "
                   "[--max-work N] [--time-limit-ms N]\n"
                   "Frontend budgets: [--max-input-bytes N (134217728)] [--max-curve-entries N (2000000)] "
                   "[--max-prepare-work N (200000000)] [--max-prepared-entries N (2000000)]\n"
                   "tiplog_layout --global-curves curves.tsv --multipliers 0,1/2,4 --budgets 2,4 "
                   "--output global.jsonl\n"
                   "Use - for standard input/output. All costs are exact nonnegative integers or num/den rationals.\n";
      return 0;
    }
    if (config.output != "-") {
      output_file.open(config.output, std::ios::out | std::ios::trunc);
      if (!output_file) throw std::runtime_error("cannot open output: " + config.output);
      output = &output_file;
    }
    const auto& source = config.input.empty() ? config.global_curves : config.input;
    std::ifstream input_file;
    std::istream* input = &std::cin;
    if (source != "-") {
      input_file.open(source);
      if (!input_file) throw std::runtime_error("cannot open input: " + source);
      input = &input_file;
    }
    if (config.global_curves.empty()) cases(*input, *output, config, context);
    else global(*input, *output, config, context);
    output->flush();
    if (!*output) throw std::runtime_error("failed writing final output");
    if (output_file.is_open()) {
      output_file.close();
      if (!output_file) throw std::runtime_error("failed closing output");
    }
    return 0;
  } catch (const std::exception& error) {
    error_row(*output, context, error);
    std::cerr << "tiplog_layout: " << error.what() << '\n';
    return 1;
  }
}
