#include "tiplog/engine/engine.hpp"
#include <array>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>

using namespace tiplog;
static double cpu_seconds() {
  timespec value{};
  clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &value);
  return double(value.tv_sec) + double(value.tv_nsec) / 1e9;
}
int main(int argc, char **argv) {
  if (argc != 2) return 2;
  const std::string scenario = argv[1];
  const bool reject = scenario == "scan_reject" || scenario == "indexed_reject";
  const bool indexed = scenario == "indexed_reject" || scenario == "indexed_one";
  const bool terminal = scenario == "terminal";
  EngineConfig config;
  config.ring_bytes = 1u << 25;
  config.max_record_bytes = 128;
  config.index.entries_per_block = 32;
  config.index.blocks = 40000;
  Engine engine(config);
  const auto topic = engine.intern("a/b/miss");
  SubscriptionSpec spec;
  spec.terms.push_back({reject ? Term::Exact : Term::Subtree,
                        reject ? "a/b/hit" : "a/b"});
  const auto sub = engine.compile(spec);
  const std::size_t records = reject ? 500000 : terminal ? 0 : 16;
  for (std::size_t i = 0; i < records; ++i) engine.publish(topic, {});
  std::vector<Delivered> out;
  out.reserve(32);
  const auto mode = indexed ? ReplayMode::Indexed : ReplayMode::Scan;
  std::uint64_t digest = 0;
  const auto started = cpu_seconds();
  if (terminal) {
    auto replay = engine.open_replay(sub, 0, mode);
    for (std::size_t i = 0; i < 3000000; ++i)
      digest += static_cast<unsigned>(replay.next_batch(1, out));
  } else {
    const std::size_t repetitions = reject ? 80 : 100000;
    for (std::size_t i = 0; i < repetitions; ++i) {
      auto replay = engine.open_replay(sub, 0, mode);
      do {
        digest += static_cast<unsigned>(replay.next_batch(reject ? std::numeric_limits<std::size_t>::max() : 1, out));
        for (const auto &item : out) digest += item.seq;
      } while (replay.status() == Status::More);
    }
  }
  const auto elapsed = cpu_seconds() - started;
  std::cout << std::setprecision(12) << "{\"scenario\":\"" << scenario
            << "\",\"cpu_seconds\":" << elapsed << ",\"digest\":" << digest << "}\n";
}
