#include "poll_campaign.hpp"
#include "tiplog/engine/engine.hpp"
#include "poll_oracle.hpp"

#include <array>
#include <limits>
#include <stdexcept>

namespace tiplog::poll_differential {
namespace {
void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}
void mix(Counts& c, std::uint64_t value) {
  for (unsigned byte = 0; byte < 8; ++byte) {
    c.digest ^= value & 255U; c.digest *= 1099511628211ULL; value >>= 8U;
  }
}
struct Bytes {
  std::span<const std::uint8_t> bytes;
  std::size_t offset{};
  unsigned take() { return offset < bytes.size() ? bytes[offset++] : 0U; }
};
struct Reader {
  std::optional<Replay> actual;
  std::optional<ref::PollOracleReplay> expected;
};
struct Live {
  std::optional<Tail> actual;
  std::optional<ref::PollOracleTail> expected;
  bool indexed{};
};
PollStop stop(ref::PollReason reason) {
  switch (reason) {
    case ref::PollReason::NoWork: return PollStop::NoWork;
    case ref::PollReason::OutputLimit: return PollStop::OutputLimit;
    case ref::PollReason::InspectionLimit: return PollStop::InspectionLimit;
    case ref::PollReason::SnapshotDone: return PollStop::SnapshotDone;
    case ref::PollReason::CaughtUp: return PollStop::CaughtUp;
    case ref::PollReason::Error: return PollStop::Error;
  }
  throw std::logic_error("oracle reason");
}
template<class Actual, class Expected>
void compare_state(const Actual& actual, const Expected& expected) {
  require(actual.status() == expected.status, "poll status differs");
  require(actual.error() == expected.error, "poll error differs");
  require(actual.checkpoint() == expected.checkpoint, "poll checkpoint differs");
}
void compare(const PollResult& actual, const std::vector<Delivered>& output,
             const ref::PollExpected& expected, const Engine& engine,
             PollLimits limits, Counts& counts) {
  require(actual.status == expected.status, "result status differs");
  require(actual.stop == stop(expected.stop), "stop reason differs");
  require(actual.inspections_used == expected.inspections, "independent inspection count differs");
  require(actual.inspections_used == actual.work_delta.records_fetched + actual.work_delta.pads_inspected,
          "work telemetry differs");
  require(!limits.max_inspections || actual.inspections_used <= *limits.max_inspections, "cap exceeded");
  require(output.size() == expected.output.size(), "output count differs: actual=" + std::to_string(output.size()) +
          " expected=" + std::to_string(expected.output.size()));
  for (std::size_t i = 0; i < output.size(); ++i) {
    const auto& a = output[i]; const auto& e = expected.output[i];
    require(a.seq == e.seq && a.pos == e.pos, "output position differs");
    require(engine.registry().get(a.topic).path == e.path, "output topic differs");
    require(std::ranges::equal(a.payload, e.payload), "output bytes differ");
    mix(counts, a.seq); mix(counts, a.pos);
    for (const auto byte : a.payload) mix(counts, std::to_integer<unsigned>(byte));
  }
  ++counts.polls;
  counts.finite_polls += limits.max_inspections.has_value();
  counts.zero_polls += limits.max_outputs == 0 || limits.max_inspections == 0;
  counts.inspection_yields += actual.stop == PollStop::InspectionLimit;
  counts.errors += actual.stop == PollStop::Error;
  counts.inspections += actual.inspections_used;
  counts.pad_inspections += actual.work_delta.pads_inspected;
  counts.delivered += output.size();
  mix(counts, static_cast<unsigned>(actual.stop)); mix(counts, actual.inspections_used);
}
void register_path(Engine& engine, std::set<std::string>& registered, const std::string& path) {
  engine.intern(path);
  for (std::size_t end = path.find('/');; end = path.find('/', end + 1)) {
    registered.insert(path.substr(0, end));
    if (end == path.npos) break;
  }
}
}

void run_input(std::span<const std::uint8_t> data, Counts& counts, std::uint64_t max_operations) {
  if (data.empty()) return;
  ++counts.inputs;
  Bytes input{data};
  const auto configuration = input.take();
  EngineConfig config;
  config.ring_bytes = std::size_t{1} << (7U + configuration % 7U);
  config.max_record_bytes = std::min(config.ring_bytes / 2, std::size_t{256});
  config.ckpt_log2 = 2;
  config.index.entries_per_block = 1U << ((configuration >> 3U) % 4U);
  config.index.blocks = static_cast<std::uint32_t>(config.ring_bytes / 16 + 128);
  config.index.sweep_evictions = 3;
  config.auto_max_partitions = (configuration & 64U) ? 0 : 64;
  config.auto_max_index_fraction = (configuration & 128U) ? 1 : 0.25;
  Engine engine(config);
  ref::ScanOracle oracle({config.ring_bytes, config.max_record_bytes});
  const std::array<std::string, 9> paths{"md/A/add", "md/A/delete", "md/B/add", "md/B/delete",
      "md/A", "md", "other/x", "other/x/deep/event", "root"};
  std::set<std::string> registered;
  for (const auto& path : paths) register_path(engine, registered, path);
  const std::array<SubscriptionSpec, 8> specs{{
      {{{Term::Exact, "md/A/add"}}}, {{{Term::Subtree, "md"}}},
      {{{Term::Subtree, "md/A"}, {Term::Exact, "md/B/add"}}},
      {{{Term::Exact, "missing/z"}}}, {{{Term::Subtree, "other/x"}}},
      {{{Term::Exact, "md/A"}}}, {{{Term::Subtree, "future/p"}}},
      {{{Term::Exact, "md/A/add"}, {Term::Exact, "other/x/deep/event"}}}}};
  std::array<Reader, 4> readers;
  std::array<Live, 4> tails;
  const auto choose_after = [&]() -> Seq {
    switch (input.take() % 7U) {
      case 0: return 0;
      case 1: return oracle.tail_seq() - 1;
      case 2: return oracle.head_seq() - 1;
      case 3: return oracle.head_seq() + 3;
      case 4: return std::numeric_limits<Seq>::max();
      case 5: return input.take() % oracle.head_seq();
      default: return oracle.tail_seq() > 1 ? oracle.tail_seq() - 2 : 0;
    }
  };
  const auto choose_limits = [&]() {
    constexpr std::array<std::uint64_t, 7> caps{0, 1, 2, 3, 7, 31, 128};
    const auto outputs = static_cast<std::size_t>(input.take() % 10U);
    const auto choice = input.take() % 8U;
    return PollLimits{outputs, choice == 7 ? std::nullopt : std::optional(caps[choice])};
  };
  const auto poll_reader = [&](Reader& pair, PollLimits limits) {
    if (!pair.actual) return;
    std::vector<Delivered> output;
    const auto expected = pair.expected->poll(limits.max_outputs, limits.max_inspections);
    const auto actual = pair.actual->next_batch(limits, output);
    try { compare(actual, output, expected, engine, limits, counts); }
    catch (const std::exception& error) {
      throw std::runtime_error("replay at operation " + std::to_string(counts.operations) + ": " + error.what());
    }
    compare_state(*pair.actual, *pair.expected);
    require(pair.actual->upper_seq() == pair.expected->upper_seq &&
            pair.actual->upper_pos() == pair.expected->upper_pos, "replay snapshot differs");
  };
  const auto poll_tail = [&](Live& pair, PollLimits limits) {
    if (!pair.actual) return;
    std::vector<Delivered> output;
    const auto expected = pair.expected->poll(limits.max_outputs, limits.max_inspections,
                                               pair.indexed, registered);
    const auto actual = pair.actual->poll(limits, output);
    try { compare(actual, output, expected, engine, limits, counts); }
    catch (const std::exception& error) {
      throw std::runtime_error("tail at operation " + std::to_string(counts.operations) + ": " + error.what());
    }
    compare_state(*pair.actual, *pair.expected);
    require(pair.actual->upper_seq() == pair.expected->replay.upper_seq &&
            pair.actual->upper_pos() == pair.expected->replay.upper_pos, "tail snapshot differs");
  };
  for (std::uint64_t operation = 0; input.offset < data.size() && operation < max_operations; ++operation) {
    ++counts.operations;
    const auto opcode = input.take() % 12U;
    const auto slot = input.take() % readers.size();
    if (opcode < 4) {
      auto path = paths[input.take() % paths.size()];
      if (opcode == 3) {
        path = "future/p/new" + std::to_string(input.take() % 16U);
        register_path(engine, registered, path);
      }
      const auto length = input.take() % (config.max_record_bytes - 15);
      const auto salt = input.take();
      std::vector<std::byte> payload(length);
      for (std::size_t i = 0; i < length; ++i) payload[i] = static_cast<std::byte>((salt + i * 37U) & 255U);
      require(engine.publish(*engine.registry().find(path), payload) == oracle.publish(path, payload),
              "publication sequence differs");
      ++counts.publications;
    } else if (opcode == 4) {
      const auto& spec = specs[input.take() % specs.size()];
      const auto after = choose_after();
      const auto mode = static_cast<ReplayMode>(input.take() % 3U);
      const auto kernel = static_cast<MergeKernel>(input.take() % 4U);
      auto& pair = readers[slot];
      pair.actual.emplace(engine.open_replay(engine.compile(spec), after, mode, kernel));
      pair.expected.emplace(oracle, spec, after, pair.actual->effective_mode() == ReplayMode::Indexed, registered);
      compare_state(*pair.actual, *pair.expected);
      counts.mode_kernel_mask |= std::uint64_t{1} << (static_cast<unsigned>(mode) * 4U + static_cast<unsigned>(kernel));
      ++counts.replay_opens;
    } else if (opcode == 5 || opcode == 9) {
      auto* chosen = &readers[slot];
      if (opcode == 9 && (!chosen->actual || chosen->actual->status() != Status::More))
        for (auto& candidate : readers)
          if (candidate.actual && candidate.actual->status() == Status::More) { chosen = &candidate; break; }
      poll_reader(*chosen, choose_limits());
    } else if (opcode == 6) {
      const auto& spec = specs[input.take() % specs.size()];
      const auto after = std::min(choose_after(), oracle.head_seq() - 1);
      auto& pair = tails[slot];
      pair.indexed = input.take() % 2U != 0;
      const auto mode = pair.indexed ? ReplayMode::Indexed : ReplayMode::Scan;
      const auto kernel = static_cast<MergeKernel>(input.take() % 4U);
      pair.actual.emplace(engine.open_tail(engine.compile(spec), after, mode, kernel));
      pair.indexed = pair.actual->effective_mode() == ReplayMode::Indexed;
      pair.expected.emplace(oracle, spec, after, pair.indexed, registered);
      compare_state(*pair.actual, *pair.expected);
      ++counts.tail_opens;
    } else if (opcode == 7 || opcode == 10) {
      auto* chosen = &tails[slot];
      if (opcode == 10 && (!chosen->actual || chosen->actual->status() == Status::Error))
        for (auto& candidate : tails)
          if (candidate.actual && candidate.actual->status() != Status::Error) { chosen = &candidate; break; }
      poll_tail(*chosen, choose_limits());
    } else if (opcode == 8) {
      readers[slot].actual.reset(); readers[slot].expected.reset();
      tails[slot].actual.reset(); tails[slot].expected.reset();
    } else {
      for (auto& pair : readers) poll_reader(pair, {8, 1});
      for (auto& pair : tails) poll_tail(pair, {8, 1});
    }
    const auto state = engine.stats();
    require(state.head_pos == oracle.head_pos() && state.tail_pos == oracle.tail_pos() &&
            state.head_seq == oracle.head_seq() && state.tail_seq == oracle.tail_seq(), "retention differs");
    if (counts.operations % 32 == 0) engine.check_invariants();
  }
  for (auto& pair : readers) {
    for (unsigned n = 0; pair.actual && pair.actual->status() == Status::More && n < 8192; ++n)
      poll_reader(pair, {8, 1});
    require(!pair.actual || pair.actual->status() != Status::More, "replay drain failed to make progress");
  }
  for (auto& pair : tails) {
    for (unsigned n = 0; pair.actual && pair.actual->status() != Status::Error && n < 8192; ++n) {
      poll_tail(pair, {8, 1});
      if (pair.actual->status() == Status::Done) break;
    }
    require(!pair.actual || pair.actual->status() != Status::More, "tail drain failed to make progress");
  }
  engine.check_invariants();
}

Counts run(std::uint64_t seed_base, std::uint64_t seeds, std::uint64_t operations) {
  Counts counts;
  for (std::uint64_t seed = seed_base; seed - seed_base < seeds; ++seed) {
    // SplitMix64 produces bytes only. The operation interpreter and independent
    // logical oracle are shared with the new fuzz target, not production code.
    std::uint64_t state = seed;
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(operations) * 8 + 1);
    for (auto& byte : bytes) {
      auto z = (state += 0x9e3779b97f4a7c15ULL);
      z = (z ^ (z >> 30U)) * 0xbf58476d1ce4e5b9ULL;
      z = (z ^ (z >> 27U)) * 0x94d049bb133111ebULL;
      byte = static_cast<std::uint8_t>((z ^ (z >> 31U)) & 255U);
    }
    try { run_input(bytes, counts, operations); }
    catch (const std::exception& error) {
      throw std::runtime_error("seed " + std::to_string(seed) + ": " + error.what());
    }
  }
  return counts;
}
}  // namespace tiplog::poll_differential
