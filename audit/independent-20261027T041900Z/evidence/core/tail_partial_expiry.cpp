#include "tiplog/engine/engine.hpp"

#include <cstdlib>
#include <iostream>
#include <new>

namespace { bool fail_second_output = false; }
[[gnu::noinline]] void* operator new(std::size_t bytes) {
  if (fail_second_output && bytes == 2 * sizeof(tiplog::Delivered)) {
    fail_second_output = false;
    throw std::bad_alloc();
  }
  if (auto* p = std::malloc(bytes == 0 ? 1 : bytes)) return p;
  throw std::bad_alloc();
}
[[gnu::noinline]] void operator delete(void* p) noexcept { std::free(p); }
[[gnu::noinline]] void operator delete(void* p, std::size_t) noexcept { std::free(p); }

int main() {
  using namespace tiplog;
  for (auto mode : {ReplayMode::Scan, ReplayMode::Indexed, ReplayMode::Auto}) {
    EngineConfig config;
    config.ring_bytes = 128;
    config.max_record_bytes = 64;
    config.index.blocks = 16;
    config.index.entries_per_block = 8;
    config.auto_max_index_fraction = 1;
    Engine engine(config);
    auto topic = engine.intern("r/s/match");
    auto tail = [&] {
      engine.publish(topic, {});
      engine.publish(topic, {});
      return engine.open_tail(engine.compile({{{Term::Exact, "r/s/match"}}}), 0, mode);
    }();
    std::vector<Delivered> out;
    out.reserve(1);
    fail_second_output = true;
    bool failed = false;
    try { (void)tail.poll(PollLimits{8, 8}, out); }
    catch (const std::bad_alloc&) { failed = true; }
    fail_second_output = false;
    if (!failed || out.size() != 1 || out.back().seq != 1) return 2;
    auto delivered_prefix = out.back().seq;
    for (unsigned i = 0; i < 16; ++i) engine.publish(topic, {});
    auto result = tail.poll(PollLimits{8, 8}, out);
    if (result.status != Status::Error || !tail.error()) return 3;
    std::cout << "mode=" << static_cast<unsigned>(mode)
              << " delivered_prefix=" << delivered_prefix
              << " error.last_delivered=" << tail.error()->last_delivered
              << " oldest_retained=" << tail.error()->oldest_retained << '\n';
  }
}
