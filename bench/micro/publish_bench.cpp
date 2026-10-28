#include "tiplog/engine/engine.hpp"
#include "bench_log.hpp"
#include "../../tools/tiplog_bench/contracts.hpp"
#include "../../tools/file_safety.hpp"
#include <benchmark/benchmark.h>

#include <algorithm>
#include <array>
#include <bit>
#include <charconv>
#include <cmath>
#include <fstream>
#include <iostream>
#include <memory>
#include <numeric>
#include <random>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace {
constexpr std::size_t schedule_size = 65536;
constexpr std::uint64_t publish_batch = 4096;
constexpr std::size_t benchmark_capacity = std::size_t{1} << 30U;
struct Choice { std::uint32_t owner; std::uint16_t length; };
struct Profile {
  std::string payload{"64"};
  std::uint32_t partitions{100};
  std::uint32_t block_entries{1024};
  bool zipf{};
  std::uint64_t seed{20191230};
  [[nodiscard]] std::string name() const {
    return "M2/payload_" + payload + "/P" + std::to_string(partitions) +
        (zipf ? "/zipf1.1/B" : "/uniform/B") + std::to_string(block_entries);
  }
};
struct Inputs {
  std::vector<Choice> choices;
  std::array<std::byte, 256> payload;
  std::uint64_t digest{14695981039346656037ULL};
  std::size_t maximum_payload{};
};
std::uint64_t number(std::string_view text) {
  std::uint64_t value{};
  const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value);
  if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size())
    throw std::invalid_argument("unsigned integer required");
  return value;
}
void hash_word(std::uint64_t& hash, std::uint64_t value) {
  for (unsigned i = 0; i < 8; ++i) {
    hash ^= value & 255U; hash *= 1099511628211ULL; value >>= 8U;
  }
}
std::uint64_t bounded(std::mt19937_64& random, std::uint64_t bound) {
  const auto threshold = (std::uint64_t{0} - bound) % bound;
  for (;;) { const auto value = random(); if (value >= threshold) return value % bound; }
}
std::vector<std::pair<std::uint16_t, std::uint64_t>> read_mix(const std::string& path) {
  std::ifstream stream(path);
  return tiplog::bench::read_payload_mix(stream);
}
Inputs inputs(const Profile& profile,
              const std::vector<std::pair<std::uint16_t, std::uint64_t>>& mix) {
  Inputs result;
  result.choices.reserve(schedule_size);
  for (std::size_t i = 0; i < result.payload.size(); ++i)
    result.payload[i] = static_cast<std::byte>((i * 37U + 11U) % 251U);
  std::mt19937_64 random(profile.seed);
  std::vector<double> cumulative(profile.partitions);
  if (profile.zipf) {
    double sum = 0;
    for (std::uint32_t p = 0; p < profile.partitions; ++p) {
      sum += 1.0 / std::pow(static_cast<double>(p + 1), 1.1); cumulative[p] = sum;
    }
    for (auto& value : cumulative) value /= sum;
    cumulative.back() = 1;
  }
  const auto fixed = profile.payload == "empirical" ? 0 : number(profile.payload);
  for (std::size_t i = 0; i < schedule_size; ++i) {
    std::uint32_t owner{};
    if (profile.zipf) {
      const auto unit = static_cast<double>(random() >> 11U) * 0x1.0p-53;
      owner = static_cast<std::uint32_t>(std::upper_bound(cumulative.begin(), cumulative.end(), unit) - cumulative.begin());
    } else owner = static_cast<std::uint32_t>(bounded(random, profile.partitions));
    const auto length = fixed != 0 ? static_cast<std::uint16_t>(fixed) : [&] {
      const auto draw = bounded(random, mix.back().second);
      return std::upper_bound(mix.begin(), mix.end(), draw,
          [](auto value, const auto& row) { return value < row.second; })->first;
    }();
    result.choices.push_back({owner, length});
    result.maximum_payload = std::max(result.maximum_payload, static_cast<std::size_t>(length));
    hash_word(result.digest, owner); hash_word(result.digest, length);
  }
  return result;
}
tiplog::EngineConfig config(const Profile& profile, bool indexed, std::size_t capacity) {
  tiplog::EngineConfig result;
  result.ring_bytes = capacity;
  result.max_record_bytes = 272;
  result.index_enabled = indexed;
  result.minimum_record_bytes = 32;  // enforced for every accepted workload
  result.index.entries_per_block = profile.block_entries;
  // P counts active message partitions. Registry also interns the unused root.
  result.index.blocks = tiplog::index::Index::sizing_blocks(capacity, 32,
      profile.block_entries, static_cast<std::uint64_t>(profile.partitions) + 1);
  return result;
}
std::vector<tiplog::TopicId> topics(tiplog::Engine& engine, const Profile& profile) {
  std::vector<tiplog::TopicId> result;
  result.reserve(profile.partitions);
  for (std::uint32_t p = 0; p < profile.partitions; ++p)
    result.push_back(engine.intern("m2/p" + std::to_string(p) + "/event"));
  return result;
}
void run(benchmark::State& state, const Profile& profile,
         const Inputs& data, bool indexed) {
  tiplog::benchlog::Invocation invocation(state.name(), profile.seed);
  tiplog::Engine engine(config(profile, indexed, benchmark_capacity));
  const auto ids = topics(engine, profile);
  std::size_t cursor = 0;
  const auto publish = [&]() {
    const auto& choice = data.choices[cursor++ % data.choices.size()];
    return engine.publish(ids[choice.owner], std::span(data.payload).first(choice.length));
  };
  // Prefill through an actual first eviction; all input generation, allocation,
  // topic creation and this warm state construction precede loop timing.
  while (engine.ring().stats().data_evicted == 0) (void)publish();
  const auto before = engine.ring().stats();
  const auto before_index = indexed ? engine.index()->stats() : tiplog::index::Stats{};
  const auto before_state = engine.stats();
  const auto measured_first_seq = before_state.head_seq;
  if (before.pressure_data_evicted != 0) {
    state.SkipWithError("sufficient pool caused pressure during prefill");
    invocation.finish(0, publish_batch, 0, true);
    return;
  }
  std::uint64_t sink = 14695981039346656037ULL;
  for (auto _ : state) {
    (void)_;
    for (std::uint64_t i = 0; i < publish_batch; ++i)
      sink = std::rotl(sink, 7) ^ publish();
    benchmark::DoNotOptimize(sink);
  }
  const auto count = static_cast<std::uint64_t>(state.iterations()) * publish_batch;
  const auto after = engine.ring().stats();
  const auto after_index = indexed ? engine.index()->stats() : tiplog::index::Stats{};
  const bool failed = engine.stats().head_seq - measured_first_seq != count ||
      after.pressure_data_evicted != before.pressure_data_evicted;
  if (failed) state.SkipWithError("publication count or sufficient-pool pressure invariant");
  const auto rate = [count](std::uint64_t total) {
    return count ? static_cast<double>(total) / static_cast<double>(count) : 0;
  };
  state.SetItemsProcessed(static_cast<std::int64_t>(count));
  state.counters["publishes_per_iteration"] = static_cast<double>(publish_batch);
  state.counters["data_evictions_per_publish"] = rate(after.data_evicted - before.data_evicted);
  state.counters["pad_bytes_evicted_per_publish"] = rate(after.pad_bytes_evicted - before.pad_bytes_evicted);
  state.counters["block_allocations_per_publish"] = rate(after_index.counters.allocations - before_index.counters.allocations);
  state.counters["block_frees_per_publish"] = rate(after_index.counters.frees - before_index.counters.frees);
  state.counters["heap_pushes_per_publish"] = rate(after_index.counters.heap_pushes - before_index.counters.heap_pushes);
  state.counters["heap_pops_per_publish"] = rate(after_index.counters.heap_pops - before_index.counters.heap_pops);
  state.counters["sweep_partitions_per_publish"] = rate(after_index.counters.swept_partitions - before_index.counters.swept_partitions);
  state.counters["pool_high_water"] = static_cast<double>(after_index.allocated_high_water);
  state.counters["pool_blocks"] = indexed ? engine.config().index.blocks : 0;
  state.counters["live_entries"] = static_cast<double>(after_index.gauges.live_entries);
  state.counters["expired_allocated_entries"] = static_cast<double>(after_index.gauges.expired_allocated_entries);
  state.counters["open_slack"] = static_cast<double>(after_index.gauges.open_slack);
  state.counters["sealed_partial_slack"] = static_cast<double>(after_index.gauges.sealed_partial_slack);
  state.counters["index_requested_reserved_bytes"] = static_cast<double>(after_index.memory.reserved_bytes);
  state.counters["allocator_overhead_measured_in_this_run"] = 0;
  state.counters["ring_bytes"] = static_cast<double>(benchmark_capacity);
  state.counters["active_partitions"] = profile.partitions;
  state.counters["registered_partitions"] = static_cast<double>(engine.registry().partition_count());
  state.counters["enforced_minimum_record_bytes"] = 32;
  const auto after_state = engine.stats();
  std::ostringstream details;
  details << "{\"prefill_publishes\":" << measured_first_seq - 1
      << ",\"start_head_seq\":" << measured_first_seq
      << ",\"end_head_seq\":" << after_state.head_seq
      << ",\"start_tail_seq\":" << before_state.tail_seq
      << ",\"end_tail_seq\":" << after_state.tail_seq
      << ",\"start_head_pos\":" << before_state.head_pos
      << ",\"end_head_pos\":" << after_state.head_pos
      << ",\"start_tail_pos\":" << before_state.tail_pos
      << ",\"end_tail_pos\":" << after_state.tail_pos
      << ",\"prefill_data_evicted\":" << before.data_evicted
      << ",\"end_data_evicted\":" << after.data_evicted
      << ",\"prefill_pressure_data_evicted\":" << before.pressure_data_evicted
      << ",\"end_pressure_data_evicted\":" << after.pressure_data_evicted
      << ",\"prefill_pad_bytes_evicted\":" << before.pad_bytes_evicted
      << ",\"end_pad_bytes_evicted\":" << after.pad_bytes_evicted
      << ",\"prefill_pad_items_evicted\":" << before.pad_items_evicted
      << ",\"end_pad_items_evicted\":" << after.pad_items_evicted
      << ",\"pool_high_water_before\":" << before_index.allocated_high_water
      << ",\"pool_high_water_after\":" << after_index.allocated_high_water
      << ",\"workload_prefix\":\"identical seeded cyclic schedule; adaptive invocation lengths may differ\"}";
  invocation.finish(static_cast<std::uint64_t>(state.iterations()), publish_batch, sink, failed, details.str());
}
void verify(const Profile& profile, const Inputs& data) {
  constexpr std::size_t capacity = 65536;
  tiplog::Engine off(config(profile, false, capacity)), on(config(profile, true, capacity));
  const auto off_ids = topics(off, profile), on_ids = topics(on, profile);
  std::uint64_t digest = 14695981039346656037ULL;
  for (const auto& choice : data.choices) {
    const auto payload = std::span(data.payload).first(choice.length);
    const auto left = off.publish(off_ids[choice.owner], payload);
    const auto right = on.publish(on_ids[choice.owner], payload);
    if (left != right) throw std::logic_error("M2 verifier sequence mismatch");
    hash_word(digest, left);
  }
  off.check_invariants(); on.check_invariants();
  const auto a = off.stats(), b = on.stats();
  if (a.head_pos != b.head_pos || a.tail_pos != b.tail_pos ||
      a.head_seq != b.head_seq || a.tail_seq != b.tail_seq ||
      on.ring().stats().pressure_data_evicted != 0)
    throw std::logic_error("M2 verifier retained state mismatch");
  for (auto pos = a.tail_pos; pos < a.head_pos;) {
    const auto x = off.ring().at(pos), y = on.ring().at(pos);
    if (x.pad != y.pad || x.seq != y.seq || x.topic != y.topic ||
        !std::ranges::equal(x.payload, y.payload))
      throw std::logic_error("M2 verifier payload mismatch");
    pos += x.size;
  }
  std::cout << "{\"status\":\"passed\",\"profile\":" << tiplog::benchlog::quoted(profile.name())
      << ",\"seed\":" << profile.seed << ",\"functional_capacity\":" << capacity
      << ",\"publishes\":" << data.choices.size() << ",\"input_schedule_fnv_hex\":\""
      << std::hex << data.digest << "\",\"output_digest_hex\":\"" << digest << std::dec
      << "\",\"scope\":\"reduced functional verification, no benchmark result\"}\n";
}
}  // namespace

int main(int argc, char** argv) {
  try {
    Profile selected;
    std::string mix_file = "configs/m2_payload_mix.csv";
    bool matrix = false, verify_only = false;
    std::vector<char*> remaining{argv[0]};
    for (int i = 1; i < argc; ++i) {
      const std::string_view option(argv[i]);
      if (option == "--matrix") { matrix = true; continue; }
      if (option == "--verify-only") { verify_only = true; continue; }
      if (option == "--payload" || option == "--partitions" || option == "--block-entries" ||
          option == "--distribution" || option == "--seed" || option == "--mix-file") {
        if (++i == argc) throw std::invalid_argument("option requires value");
        const std::string_view value(argv[i]);
        if (option == "--payload") selected.payload = value;
        else if (option == "--partitions") {
          const auto count = number(value); if (count != 1 && count != 100 && count != 10000)
            throw std::invalid_argument("P must be 1,100,10000");
          selected.partitions = static_cast<std::uint32_t>(count);
        } else if (option == "--block-entries") {
          const auto count = number(value); if (count != 256 && count != 1024)
            throw std::invalid_argument("B must be 256 or1024");
          selected.block_entries = static_cast<std::uint32_t>(count);
        } else if (option == "--seed") selected.seed = number(value);
        else if (option == "--mix-file") mix_file = value;
        else {
          if (value != "uniform" && value != "zipf") throw std::invalid_argument("uniform or zipf required");
          selected.zipf = value == "zipf";
        }
      } else remaining.push_back(argv[i]);
    }
    if (selected.payload != "12" && selected.payload != "32" && selected.payload != "64" &&
        selected.payload != "256" && selected.payload != "empirical")
      throw std::invalid_argument("payload must be12,32,64,256,empirical");
    if (verify_only && remaining.size() != 1)
      throw std::invalid_argument("unrecognized argument in verification mode: " +
                                  std::string(remaining[1]));
    if (!verify_only)
      tiplog::cli::check_benchmark_outputs(static_cast<int>(remaining.size()), remaining.data(),
                                          {mix_file}, false);
    const auto mix = read_mix(mix_file);
    std::vector<Profile> profiles;
    if (matrix) {
      for (const auto* payload : {"12", "32", "64", "256", "empirical"})
        for (const auto partitions : {1U, 100U, 10000U})
          for (const bool zipf : {false, true})
            for (const auto entries : {256U, 1024U})
              profiles.push_back({payload, partitions, entries, zipf, selected.seed});
    } else profiles.push_back(selected);
    int benchmark_argc = static_cast<int>(remaining.size());
    remaining.push_back(nullptr);
    if (!verify_only) {
      benchmark::Initialize(&benchmark_argc, remaining.data());
      if (benchmark::ReportUnrecognizedArguments(benchmark_argc, remaining.data())) return 2;
      benchmark::AddCustomContext("tiplog_scope", "P5 microbenchmark harness; full campaigns belong to P6");
      benchmark::AddCustomContext("cache_treatment", "repeat steady-state stream; no deliberate cache flush or residency guarantee");
      benchmark::AddCustomContext("timing_boundary", "batched Engine.publish plus common precomputed schedule lookup and sequence sink; setup/prefill/counter reads excluded");
      benchmark::AddCustomContext("input_seed", std::to_string(selected.seed));
      benchmark::AddCustomContext("mix_file", mix_file);
      benchmark::AddCustomContext("internal_interleaving_seed", "not exposed by pinned Benchmark1.9.5; invocation order saved separately");
    }
    for (const auto& profile : profiles) {
      auto data = std::make_shared<Inputs>(inputs(profile, mix));
      if (verify_only) { verify(profile, *data); continue; }
      std::ostringstream hash; hash << std::hex << data->digest;
      benchmark::AddCustomContext(profile.name() + "/input_schedule_fnv_hex", hash.str());
      for (const bool indexed : {false, true}) {
        const auto name = profile.name() + (indexed ? "/index_on" : "/index_off");
        benchmark::RegisterBenchmark(name.c_str(), [profile, data, indexed](benchmark::State& state) {
          run(state, profile, *data, indexed);
        });
      }
    }
    if (!verify_only) { benchmark::RunSpecifiedBenchmarks(); benchmark::Shutdown(); }
    std::cout.flush();
    if (!std::cout) throw std::runtime_error("failed writing stdout result");
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "publish_bench: " << error.what() << '\n'; return 1;
  }
}
