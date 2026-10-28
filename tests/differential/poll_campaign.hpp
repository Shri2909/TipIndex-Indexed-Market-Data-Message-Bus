#pragma once
#include <cstddef>
#include <cstdint>
#include <span>
namespace tiplog::poll_differential {
struct Counts {
  std::uint64_t inputs{}, operations{}, publications{}, replay_opens{}, tail_opens{}, polls{};
  std::uint64_t finite_polls{}, zero_polls{}, inspection_yields{}, delivered{}, inspections{};
  std::uint64_t errors{}, pad_inspections{}, mode_kernel_mask{};
  std::uint64_t digest{14695981039346656037ULL};
};
void run_input(std::span<const std::uint8_t>, Counts&, std::uint64_t max_operations = 16384);
Counts run(std::uint64_t seed_base, std::uint64_t seeds, std::uint64_t operations);
}  // namespace tiplog::poll_differential
