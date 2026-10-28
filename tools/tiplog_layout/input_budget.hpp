#pragma once

#include "tiplog/layout/model.hpp"

#include <cstdint>
#include <istream>
#include <stdexcept>
#include <string>

namespace tiplog::layout::cli {
struct InputLimits {
  std::uint64_t max_bytes{128ULL << 20};
  std::uint64_t max_curve_entries{2000000};
  PreparationLimits preparation{200000000, 2000000};
};

// These are whole-run frontend budgets, separate from exact-method limits.
// Check every charge before growing input/curve storage or starting preparation.
class InputBudget {
public:
  explicit InputBudget(const InputLimits& limits) : limits_(limits) {}
  bool getline(std::istream& input, std::string& line) {
    line.clear();
    char character{};
    while (input.get(character)) {
      charge(bytes_, 1, limits_.max_bytes, "layout input exceeds --max-input-bytes");
      if (character == '\n') return true;
      line += character;
    }
    if (input.bad()) throw std::runtime_error("failed reading layout input");
    return !line.empty();
  }
  void curve(std::uint64_t entries) {
    charge(entries_, entries, limits_.max_curve_entries,
           "aggregate CURVE entries exceed --max-curve-entries");
  }
  void prepare(const Problem& problem) {
    charge(work_, preparation_work_bound(problem), limits_.preparation.max_work,
           "aggregate preparation work exceeds --max-prepare-work");
  }
private:
  static void charge(std::uint64_t& used, std::uint64_t amount,
                     std::uint64_t maximum, const char* message) {
    if (used > maximum || amount > maximum - used) throw std::length_error(message);
    used += amount;
  }
  const InputLimits& limits_;
  std::uint64_t bytes_{}, entries_{}, work_{};
};
} // namespace tiplog::layout::cli
