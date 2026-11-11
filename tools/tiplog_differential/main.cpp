#include "../cli_number.hpp"
#include "differential/campaign.hpp"
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <string_view>

using tiplog::cli::parse_u64;

int main(int argc, char **argv) {
  try {
    tiplog::differential::Config config;
    std::string_view mode = "scan", kernel = "stdpq";
    for (int i = 1; i < argc; ++i) {
      const std::string_view arg(argv[i]);
      if (arg == "--help") {
        std::cout
            << "tiplog_differential [--seeds N] [--operations N] [--seed-base "
               "N] [--mode scan|indexed|auto] [--kernel stdpq|binheap|quad|loser]\n";
        return 0;
      }
      if (i + 1 >= argc)
        throw std::invalid_argument("missing option value");
      const std::string_view value(argv[++i]);
      if (arg == "--seeds")
        config.seeds = parse_u64(value);
      else if (arg == "--operations")
        config.operations = parse_u64(value);
      else if (arg == "--seed-base")
        config.seed_base = parse_u64(value);
      else if (arg == "--mode")
        mode = value;
      else if (arg == "--kernel")
        kernel = value;
      else
        throw std::invalid_argument("unknown option");
    }
    if (mode == "scan")
      config.mode = tiplog::ReplayMode::Scan;
    else if (mode == "indexed")
      config.mode = tiplog::ReplayMode::Indexed;
    else if (mode == "auto")
      config.mode = tiplog::ReplayMode::Auto;
    else
      throw std::invalid_argument("invalid mode");
    if (kernel == "stdpq")
      config.kernel = tiplog::MergeKernel::StdPQ;
    else if (kernel == "binheap")
      config.kernel = tiplog::MergeKernel::BinHeap;
    else if (kernel == "quad")
      config.kernel = tiplog::MergeKernel::Quad;
    else if (kernel == "loser")
      config.kernel = tiplog::MergeKernel::Loser;
    else
      throw std::invalid_argument("invalid kernel");
    const auto start = std::chrono::steady_clock::now();
    const auto r = tiplog::differential::run(config);
    const auto seconds =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - start)
            .count();
    std::cout << "{\"status\":\"passed\",\"mode\":\"" << mode
              << "\",\"kernel\":\"" << kernel
              << "\",\"seed_base\":" << config.seed_base
              << ",\"seeds\":" << r.seeds
              << ",\"operations_per_seed\":" << config.operations
              << ",\"operations\":" << r.operations
              << ",\"publications\":" << r.publications
              << ",\"rejected_publications\":" << r.rejected_publications
              << ",\"opens\":" << r.opens
              << ",\"effective_indexed_opens\":" << r.indexed_opens
              << ",\"effective_scan_opens\":" << r.scan_opens
              << ",\"multicursor_opens\":" << r.multicursor_opens
              << ",\"indexed_execution_batches\":" << r.indexed_execution_batches
              << ",\"scan_execution_batches\":" << r.scan_execution_batches
              << ",\"batches\":" << r.batches
              << ",\"nonuniform_payload_publications\":" << r.nonuniform_publications
              << ",\"delivered\":" << r.delivered
              << ",\"history_expired_opens\":" << r.history_expired
              << ",\"fell_behind_batches\":" << r.fell_behind
              << ",\"empty_specs_rejected\":" << r.empty_specs_rejected
              << ",\"digest_fnv1a64\":" << r.final_digest
              << ",\"elapsed_monotonic_seconds\":" << seconds << "}\n";
    std::cout.flush();
    if (!std::cout) throw std::runtime_error("failed writing stdout result");
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "tiplog_differential: " << error.what() << '\n';
    return 1;
  }
}
