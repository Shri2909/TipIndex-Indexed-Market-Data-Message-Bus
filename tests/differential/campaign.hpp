#pragma once
#include "tiplog/types.hpp"
#include <cstdint>
namespace tiplog::differential {
struct Config {
  std::uint64_t seed_base{1};
  std::uint64_t seeds{1000};
  std::uint64_t operations{10000};
  ReplayMode mode{ReplayMode::Scan};
  MergeKernel kernel{MergeKernel::StdPQ};
};
struct Result {
  std::uint64_t seeds{};
  std::uint64_t operations{};
  std::uint64_t publications{};
  std::uint64_t rejected_publications{};
  std::uint64_t opens{};
  std::uint64_t indexed_opens{};
  std::uint64_t scan_opens{};
  std::uint64_t batches{};
  std::uint64_t delivered{};
  std::uint64_t history_expired{};
  std::uint64_t fell_behind{};
  std::uint64_t empty_specs_rejected{};
  std::uint64_t final_digest{14695981039346656037ULL};
};
Result run(const Config &);
} // namespace tiplog::differential
