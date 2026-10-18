#include "bench_log.hpp"
#include "tiplog/merge/kernels.hpp"

#include <benchmark/benchmark.h>

#include <array>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <optional>
#include <random>
#include <sstream>
#include <string>
#include <string_view>
#include <type_traits>

namespace {
using tiplog::merge::Key;
constexpr std::uint64_t initial_hash = 14695981039346656037ULL;
constexpr std::size_t full_outputs = std::size_t{1} << 22U;
constexpr std::size_t full_touch_bytes = std::size_t{1} << 30U;
std::uint64_t fold(std::uint64_t hash, std::uint64_t word) noexcept {
  return (hash ^ word) * 1099511628211ULL;
}
std::uint64_t touch_value(std::uint64_t index) noexcept {
  auto value = index + 0x9e3779b97f4a7c15ULL;
  value = (value ^ (value >> 30U)) * 0xbf58476d1ce4e5b9ULL;
  value = (value ^ (value >> 27U)) * 0x94d049bb133111ebULL;
  return value ^ (value >> 31U);
}
std::uint64_t bounded(std::mt19937_64 &rng, std::uint64_t bound) {
  const auto threshold = (std::uint64_t{0} - bound) % bound;
  for (;;) {
    const auto value = rng();
    if (value >= threshold)
      return value % bound;
  }
}
std::string hex(std::uint64_t value) {
  std::ostringstream out;
  out << std::hex << value;
  return out.str();
}
enum class Pattern { Uniform, Geometric, Zipf };
struct Profile {
  bool touch{};
  std::uint32_t k{64};
  Pattern pattern{Pattern::Uniform};
  std::uint32_t mean{64};
  double zipf{1.1};
  std::size_t outputs{full_outputs};
  std::size_t touch_bytes{full_touch_bytes};
  std::uint64_t seed{20191230};
  std::uint32_t padding{3};
  bool diagnostic{};
};
std::string profile_name(const Profile &p) {
  std::ostringstream out;
  out << (p.touch ? "M1-touch" : "M1") << "/k" << p.k << '/';
  if (p.pattern == Pattern::Uniform)
    out << "uniform";
  else if (p.pattern == Pattern::Geometric)
    out << "geometric" << p.mean;
  else
    out << "zipf" << p.zipf;
  out << "/N" << p.outputs;
  if (p.diagnostic)
    out << "/diagnostic";
  return out.str();
}
struct Input {
  std::vector<std::vector<Key>> lists;
  std::vector<Key> heads;
  std::unique_ptr<std::uint64_t[]> touch;
  std::uint64_t input_hash{initial_hash};
  std::uint64_t expected_hash{initial_hash};
  std::uint64_t initialization_hash{initial_hash};
  std::uint64_t runs{};
  std::size_t active{};
};
Input make_input(const Profile &p) {
  if (p.k == 0 || p.k > tiplog::merge::max_cursors || p.outputs == 0)
    throw std::invalid_argument(
        "benchmark needs 1..65535 cursors and positive outputs");
  if (!p.diagnostic &&
      (p.outputs != full_outputs || p.touch_bytes != full_touch_bytes))
    throw std::invalid_argument("reduced cases require explicit --diagnostic");
  if (p.outputs > (tiplog::merge::position_limit - 1) / 256 ||
      (p.touch && (p.touch_bytes % 8 != 0 || p.outputs > p.touch_bytes / 256)))
    throw std::invalid_argument("touch/output position range invalid");
  Input result;
  result.lists.resize(p.k);
  result.heads.assign(p.k, tiplog::merge::sentinel);
  if (p.touch) {
    const auto words = p.touch_bytes / sizeof(std::uint64_t);
    result.touch.reset(new std::uint64_t[words]);
    for (std::size_t i = 0; i < words; ++i) {
      result.touch[i] = touch_value(i);
      result.initialization_hash =
          fold(result.initialization_hash, result.touch[i]);
    }
  }
  std::vector<double> cdf;
  if (p.pattern == Pattern::Zipf) {
    cdf.resize(p.k);
    double total = 0;
    for (std::uint32_t i = 0; i < p.k; ++i) {
      total += 1.0 / std::pow(static_cast<double>(i) + 1.0, p.zipf);
      cdf[i] = total;
    }
    for (auto &value : cdf)
      value /= total;
    cdf.back() = 1.0;
  }
  std::mt19937_64 rng(p.seed);
  auto owner = static_cast<std::uint32_t>(bounded(rng, p.k));
  std::uint32_t previous_owner = p.k;
  for (std::size_t i = 0; i < p.outputs; ++i) {
    if (p.pattern == Pattern::Uniform)
      owner = static_cast<std::uint32_t>(bounded(rng, p.k));
    else if (p.pattern == Pattern::Zipf) {
      const auto u = static_cast<double>(rng() >> 11U) * 0x1.0p-53;
      owner = static_cast<std::uint32_t>(
          std::upper_bound(cdf.begin(), cdf.end(), u) - cdf.begin());
    }
    if (owner != previous_owner)
      ++result.runs;
    previous_owner = owner;
    const auto pos = static_cast<tiplog::LogPos>(i) * (p.touch ? 256U : 8U);
    result.lists[owner].push_back(tiplog::merge::pack(pos, owner, p.k));
    if (p.pattern == Pattern::Geometric && p.k > 1 &&
        bounded(rng, p.mean) == 0) {
      auto next = static_cast<std::uint32_t>(bounded(rng, p.k - 1));
      if (next >= owner)
        ++next;
      owner = next;
    }
  }
  std::vector<Key> sorted_union;
  sorted_union.reserve(p.outputs);
  for (std::uint32_t i = 0; i < p.k; ++i) {
    const auto &list = result.lists[i];
    result.input_hash = fold(fold(result.input_hash, i), list.size());
    if (!list.empty()) {
      result.heads[i] = list[0];
      ++result.active;
    }
    for (const auto key : list) {
      result.input_hash = fold(result.input_hash, key);
      sorted_union.push_back(key);
    }
  }
  // Independent sorted union: no tested priority/heap/tournament helper used.
  std::sort(sorted_union.begin(), sorted_union.end());
  for (const auto key : sorted_union) {
    result.expected_hash = fold(result.expected_hash, key);
    if (p.touch)
      result.expected_hash =
          fold(result.expected_hash,
               result.touch[((key >> 16U) << 3U) / sizeof(std::uint64_t)]);
  }
  return result;
}
std::string metadata(const Profile &p, const Input &input,
                     std::string_view kernel) {
  const auto span = p.touch ? (p.outputs - 1) * 256 + 8 : 0;
  std::ostringstream out;
  out << "{\"profile\":" << tiplog::benchlog::quoted(profile_name(p))
      << ",\"kernel\":" << tiplog::benchlog::quoted(kernel)
      << ",\"seed\":" << p.seed << ",\"requested_k\":" << p.k
      << ",\"active_k\":" << input.active << ",\"outputs\":" << p.outputs
      << ",\"input_hash_hex\":\"" << hex(input.input_hash)
      << "\",\"expected_hash_hex\":\"" << hex(input.expected_hash)
      << "\",\"hash_algorithm\":\"word-xor-multiply64-v1\""
      << ",\"observed_owner_runs\":" << input.runs << ",\"observed_run_mean\":"
      << static_cast<double>(p.outputs) / static_cast<double>(input.runs)
      << ",\"nominal_geometric_mean\":"
      << (p.pattern == Pattern::Geometric ? p.mean : 0)
      << ",\"k1_degenerate\":" << (p.k == 1 ? "true" : "false")
      << ",\"touch_initialized_bytes\":" << (p.touch ? p.touch_bytes : 0)
      << ",\"touch_initialization\":\"splitmix64-index-v1\""
      << ",\"touch_initialization_hash_hex\":\""
      << hex(input.initialization_hash)
      << "\",\"touch_address_span_bytes\":" << span
      << ",\"touch_distinct_64B_line_bytes\":" << (p.touch ? p.outputs * 64 : 0)
      << ",\"touch_loaded_bytes\":" << (p.touch ? p.outputs * 8 : 0)
      << ",\"quad_padding_words\":" << p.padding
      << ",\"diagnostic\":" << (p.diagnostic ? "true" : "false") << '}';
  return out.str();
}
void save_metadata(const std::string &line) {
  const auto *path = std::getenv("TIPLOG_BENCH_INPUTS");
  if (!path || !*path)
    return;
  std::ofstream out(path, std::ios::app);
  out << line << '\n';
  if (!out)
    throw std::runtime_error("cannot write benchmark input manifest");
}
template <class Kernel>
void emplace(std::optional<Kernel> &kernel, const Input &input,
             const Profile &profile) {
  if constexpr (std::is_same_v<Kernel, tiplog::merge::Quad>)
    kernel.emplace(input.heads, profile.padding);
  else
    kernel.emplace(input.heads);
}
template <bool Touch, class Kernel>
std::uint64_t merge_once(Kernel &kernel, const Input &input,
                         std::vector<std::size_t> &offsets,
                         std::size_t &outputs) {
  auto hash = initial_hash;
  while (!kernel.empty()) {
    const auto key = kernel.top();
    const auto id = static_cast<std::uint32_t>(key & 0xffffU);
    hash = fold(hash, key);
    if constexpr (Touch)
      hash =
          fold(hash, input.touch[((key >> 16U) << 3U) / sizeof(std::uint64_t)]);
    ++outputs;
    ++offsets[id];
    if (offsets[id] == input.lists[id].size())
      kernel.pop();
    else
      kernel.replace_top(input.lists[id][offsets[id]]);
  }
  return hash;
}
template <class Kernel>
void run(benchmark::State &state, Profile profile, std::string kernel_name) {
  tiplog::benchlog::Invocation invocation(
      profile_name(profile) + "/" + kernel_name, profile.seed);
  const auto input = make_input(profile);
  const auto description = metadata(profile, input, kernel_name);
  save_metadata(description);
  state.SetLabel(description);
  std::vector<std::size_t> offsets(profile.k);
  std::optional<Kernel> kernel;
  auto hash = initial_hash;
  bool failed = false;
  for (auto iteration : state) {
    (void)iteration;
    state.PauseTiming();
    std::fill(offsets.begin(), offsets.end(), 0);
    emplace(kernel, input, profile);
    std::size_t outputs = 0;
    state.ResumeTiming();
    hash = profile.touch ? merge_once<true>(*kernel, input, offsets, outputs)
                         : merge_once<false>(*kernel, input, offsets, outputs);
    benchmark::DoNotOptimize(hash);
    benchmark::ClobberMemory();
    state.PauseTiming();
    kernel.reset();
    if (outputs != profile.outputs || hash != input.expected_hash) {
      failed = true;
      state.SkipWithError(
          "merge count/hash differs from independent sorted union");
      // SkipWithError stops timing and marks State skipped. ResumeTiming
      // rejects a skipped state, so leave through the supported error path.
      break;
    }
    state.ResumeTiming();
  }
  state.SetItemsProcessed(state.iterations() *
                          static_cast<std::int64_t>(profile.outputs));
  state.counters["requested_k"] = profile.k;
  state.counters["active_k"] = static_cast<double>(input.active);
  state.counters["outputs_per_iteration"] =
      static_cast<double>(profile.outputs);
  invocation.finish(static_cast<std::uint64_t>(state.iterations()),
                    profile.outputs, hash, failed);
}
template <class Kernel>
void verify(const Profile &profile, std::string_view name) {
  const auto input = make_input(profile);
  std::vector<std::size_t> offsets(profile.k);
  std::optional<Kernel> kernel;
  emplace(kernel, input, profile);
  std::size_t outputs = 0;
  const auto hash = profile.touch
                        ? merge_once<true>(*kernel, input, offsets, outputs)
                        : merge_once<false>(*kernel, input, offsets, outputs);
  if (hash != input.expected_hash || outputs != profile.outputs)
    throw std::runtime_error("functional merge verification failed");
  std::cout << "{\"status\":\"passed\",\"actual_hash_hex\":\"" << hex(hash)
            << "\",\"input\":" << metadata(profile, input, name) << "}\n";
}
void add_profile(const Profile &profile, bool verification, bool quad_plain) {
  const auto name = profile_name(profile);
#define TIPLOG_ADD(KERNEL, NAME)                                               \
  if (verification)                                                            \
    verify<tiplog::merge::KERNEL>(profile, NAME);                              \
  else                                                                         \
    benchmark::RegisterBenchmark((name + "/" NAME).c_str(),                    \
                                 [profile](benchmark::State &state) {          \
                                   run<tiplog::merge::KERNEL>(state, profile,  \
                                                              NAME);           \
                                 })                                            \
        ->Unit(benchmark::kNanosecond)
  TIPLOG_ADD(StdPQ, "StdPQ");
  TIPLOG_ADD(BinHeap, "BinHeap");
  TIPLOG_ADD(Quad, "Quad-pad3");
  TIPLOG_ADD(Loser, "Loser");
#undef TIPLOG_ADD
  if (quad_plain) {
    auto plain = profile;
    plain.padding = 0;
    if (verification)
      verify<tiplog::merge::Quad>(plain, "Quad-pad0");
    else
      benchmark::RegisterBenchmark((name + "/Quad-pad0").c_str(),
                                   [plain](benchmark::State &state) {
                                     run<tiplog::merge::Quad>(state, plain,
                                                              "Quad-pad0");
                                   })
          ->Unit(benchmark::kNanosecond);
  }
}
std::string value(std::string_view arg, std::string_view prefix) {
  return std::string(arg.substr(prefix.size()));
}
} // namespace
int main(int argc, char **argv) {
  try {
    Profile base;
    bool verification = false;
    bool quad_plain = false;
    std::string selection = "pilot";
    std::vector<char *> benchmark_args{argv[0]};
    for (int i = 1; i < argc; ++i) {
      const std::string_view arg(argv[i]);
      if (arg == "--verify-only")
        verification = true;
      else if (arg == "--diagnostic") {
        base.diagnostic = true;
        verification = true;
      } else if (arg == "--quad-padding-both")
        quad_plain = true;
      else if (arg.starts_with("--profile="))
        selection = value(arg, "--profile=");
      else if (arg.starts_with("--outputs="))
        base.outputs = std::stoull(value(arg, "--outputs="));
      else if (arg.starts_with("--touch-bytes="))
        base.touch_bytes = std::stoull(value(arg, "--touch-bytes="));
      else if (arg.starts_with("--seed="))
        base.seed = std::stoull(value(arg, "--seed="));
      else if (arg == "--tiplog-help") {
        std::cout
            << "merge_bench --profile=pilot|full|uniform64|geometric64|touch64 "
               "[--verify-only] [--quad-padding-both] [--seed=N] "
               "[--diagnostic --outputs=N --touch-bytes=N] [Google Benchmark "
               "flags]\n"
               "Full cases use N=4194304, touch=1073741824 bytes; --diagnostic "
               "is "
               "functional/simulated-tool work, never a full pilot.\n";
        return 0;
      } else
        benchmark_args.push_back(argv[i]);
    }
    if (!verification) {
      auto count = static_cast<int>(benchmark_args.size());
      benchmark_args.push_back(nullptr);
      benchmark::Initialize(&count, benchmark_args.data());
      if (benchmark::ReportUnrecognizedArguments(count, benchmark_args.data()))
        return 2;
      benchmark::AddCustomContext("tiplog_hash_algorithm",
                                  "word-xor-multiply64-v1");
      benchmark::AddCustomContext(
          "tiplog_interleave_seed",
          "unexposed random_device entropy in pinned1.9.5");
      benchmark::AddCustomContext("tiplog_input_seed",
                                  std::to_string(base.seed));
      benchmark::AddCustomContext("tiplog_timing_boundary",
                                  "merge loop and common hash only; "
                                  "generation/reset/kernel init excluded");
      benchmark::AddCustomContext(
          "tiplog_cache_treatment",
          "repeated warm traversal; touch array fully written outside timing");
    }
    auto add = [&](Profile p) { add_profile(p, verification, quad_plain); };
    if (selection == "full") {
      constexpr std::array counts{1U,  2U,   4U,    8U,    16U,
                                  64U, 256U, 1024U, 4096U, 16384U};
      for (const bool touch : {false, true})
        for (const auto k : counts) {
          auto p = base;
          p.touch = touch;
          p.k = k;
          p.pattern = Pattern::Uniform;
          add(p);
          for (const auto mean : {1U, 4U, 16U, 64U, 256U}) {
            p.pattern = Pattern::Geometric;
            p.mean = mean;
            add(p);
          }
          for (const auto skew : {0.0, 0.8, 1.1}) {
            p.pattern = Pattern::Zipf;
            p.zipf = skew;
            add(p);
          }
        }
    } else if (selection == "pilot" || selection == "uniform64" ||
               selection == "geometric64" || selection == "touch64") {
      if (selection == "pilot" || selection == "uniform64")
        add(base);
      if (selection == "pilot" || selection == "geometric64") {
        auto p = base;
        p.pattern = Pattern::Geometric;
        p.mean = 64;
        add(p);
      }
      if (selection == "pilot" || selection == "touch64") {
        auto p = base;
        p.touch = true;
        add(p);
      }
    } else
      throw std::invalid_argument("unknown merge profile");
    if (!verification) {
      benchmark::RunSpecifiedBenchmarks();
      benchmark::Shutdown();
    }
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "merge_bench: " << e.what() << '\n';
    return 1;
  }
}
