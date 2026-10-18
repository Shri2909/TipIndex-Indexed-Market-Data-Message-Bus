#pragma once

#include "tiplog/trace/reader.hpp"
#include "tiplog/types.hpp"

#include <cstddef>
#include <cstdint>
#include <functional>
#include <limits>
#include <span>
#include <string_view>
#include <vector>

namespace tiplog::driver {

struct Pause {
  std::uint64_t first_tick{1};
  std::uint64_t ticks{};
};

struct Config {
  std::uint64_t seed{1};
  std::uint64_t max_records{std::numeric_limits<std::uint64_t>::max()};
  std::uint64_t consume_every{1};
  std::size_t batch_budget{64};
  // Uses raw mt19937_64 output modulo batch_budget, avoiding implementation-
  // dependent uniform_int_distribution mapping. This is a schedule, not a
  // claim of statistically uniform workload sampling.
  bool jitter_budget{};
  std::vector<Pause> pauses;
};

struct Tick {
  std::uint64_t tick{};
  Seq published_seq{};
  std::size_t budget{};
  bool paused{};
  bool operator==(const Tick&) const = default;
};

struct Result {
  std::uint64_t seed{};
  std::uint64_t published{};
  Seq first_seq{};
  Seq last_seq{};
  std::uint64_t payload_bytes{};
  // FNV-1a diagnostic digests over canonical little-endian fields; these are
  // reproducibility checks, not cryptographic identity/checksum substitutes.
  std::uint64_t publication_digest{14695981039346656037ULL};
  std::uint64_t schedule_digest{14695981039346656037ULL};
  bool operator==(const Result&) const = default;
};

using Publish = std::function<Seq(std::string_view, std::span<const std::byte>)>;
using Consume = std::function<void(const Tick&)>;

// Engine neutral: owns no engine and links no test reference implementation.
// Each record is published in trace order, then exactly one tick is reported.
// Payload spans borrow the immutable Reader, under the Reader's lifetime rules.
Result drive_trace(const trace::Reader& reader, const Config& config,
                   const Publish& publish, const Consume& consume = {});

}  // namespace tiplog::driver
