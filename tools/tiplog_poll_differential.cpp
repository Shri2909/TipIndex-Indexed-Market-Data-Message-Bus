#include "differential/poll_campaign.hpp"
#include <charconv>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string_view>

int main(int argc, char** argv) {
  try {
    std::uint64_t seed_base = 1, seeds = 100, operations = 1000;
    for (int i = 1; i < argc; ++i) {
      const std::string_view option(argv[i]);
      if (option == "--help") {
        std::cout << "tiplog_poll_differential [--seed-base N] [--seeds N] [--operations N]\n";
        return std::cout ? 0 : 1;
      }
      if (i + 1 == argc) throw std::invalid_argument("missing option value");
      const std::string_view value(argv[++i]);
      std::uint64_t number{};
      const auto parsed = std::from_chars(value.data(), value.data() + value.size(), number);
      if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size())
        throw std::invalid_argument("invalid unsigned integer");
      if (option == "--seed-base") seed_base = number;
      else if (option == "--seeds") seeds = number;
      else if (option == "--operations") operations = number;
      else throw std::invalid_argument("unknown option");
    }
    if (seeds == 0 || seeds > 1000000 || operations == 0 || operations > 100000 ||
        operations > 100000000 / seeds || seed_base > std::numeric_limits<std::uint64_t>::max() - seeds)
      throw std::invalid_argument("positive campaign bounded to 100M operations is required");
    const auto r = tiplog::poll_differential::run(seed_base, seeds, operations);
    std::cout << "{\"status\":\"passed\",\"seed_base\":" << seed_base
              << ",\"seeds\":" << r.inputs << ",\"operations_per_seed\":" << operations
              << ",\"operations\":" << r.operations << ",\"publications\":" << r.publications
              << ",\"replay_opens\":" << r.replay_opens << ",\"tail_opens\":" << r.tail_opens
              << ",\"polls\":" << r.polls << ",\"finite_polls\":" << r.finite_polls
              << ",\"zero_polls\":" << r.zero_polls << ",\"inspection_yields\":" << r.inspection_yields
              << ",\"delivered\":" << r.delivered << ",\"inspections\":" << r.inspections
              << ",\"errors\":" << r.errors << ",\"pad_inspections\":" << r.pad_inspections
              << ",\"mode_kernel_mask\":" << r.mode_kernel_mask << ",\"digest_fnv1a64\":" << r.digest << "}\n";
    std::cout.flush();
    if (!std::cout) throw std::runtime_error("failed writing stdout result");
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "tiplog_poll_differential: " << error.what() << '\n';
    return 1;
  }
}
