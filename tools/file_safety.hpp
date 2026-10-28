#pragma once

#include <cstdlib>
#include <filesystem>
#include <initializer_list>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace tiplog::cli {
// Protect the inputs of a single local invocation, including hard-link aliases.
// Paths must remain stable during the invocation; this is not a concurrent
// hostile-pathname protocol. Call before any output is opened for writing.
inline void require_distinct_files(const std::filesystem::path& input,
                                   const std::filesystem::path& output) {
  if (input.empty() || output.empty()) return;
  if (std::filesystem::weakly_canonical(input) ==
          std::filesystem::weakly_canonical(output) ||
      (std::filesystem::exists(input) && std::filesystem::exists(output) &&
       std::filesystem::equivalent(input, output)))
    throw std::invalid_argument("input and output paths must differ: " + input.string());
}

// Google Benchmark and our diagnostics each own an output. Check these before
// library initialization can open a requested result file.
inline void check_benchmark_outputs(
    int argc, char** argv,
    std::initializer_list<std::filesystem::path> inputs = {},
    bool writes_input_manifest = true) {
  std::vector<std::filesystem::path> outputs;
  for (const char* variable : {"TIPLOG_BENCH_INPUTS", "TIPLOG_BENCH_INVOCATIONS"})
    if ((writes_input_manifest || std::string_view(variable) != "TIPLOG_BENCH_INPUTS"))
      if (const auto* path = std::getenv(variable); path && *path) outputs.emplace_back(path);
  std::filesystem::path benchmark_output;
  if (const auto* path = std::getenv("BENCHMARK_OUT")) benchmark_output = path;
  constexpr std::string_view prefix = "--benchmark_out=";
  for (int index = 1; index < argc; ++index) {
    const std::string_view arg(argv[index]);
    if (arg.starts_with(prefix)) benchmark_output = arg.substr(prefix.size());
  }
  // Pinned Google Benchmark reads BENCHMARK_OUT, then lets the last command-line
  // --benchmark_out= value override it (including an explicitly empty value).
  if (!benchmark_output.empty()) outputs.push_back(std::move(benchmark_output));
  for (std::size_t index = 0; index < outputs.size(); ++index) {
    for (const auto& input : inputs) require_distinct_files(input, outputs[index]);
    for (std::size_t previous = 0; previous < index; ++previous)
      require_distinct_files(outputs[previous], outputs[index]);
  }
}
} // namespace tiplog::cli
