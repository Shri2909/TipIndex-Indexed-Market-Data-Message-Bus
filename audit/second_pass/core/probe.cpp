#include "tiplog/engine/engine.hpp"
#include <cassert>
#include <iostream>
#include <vector>

using namespace tiplog;

static const char* mode_name(ReplayMode m) {
  return m == ReplayMode::Scan ? "Scan" : m == ReplayMode::Indexed ? "Indexed" : "Auto";
}
static void report(const char* scenario, Engine& engine,
                   const subs::CompiledSubscription& sub, Seq after, ReplayMode mode) {
  auto replay = engine.open_replay(sub, after, mode);
  std::vector<Delivered> out;
  const auto status = replay.next_batch(1, out);
  const auto work = replay.work();
  std::cout << scenario << " requested=" << mode_name(mode)
            << " effective=" << mode_name(replay.effective_mode())
            << " output_limit=1 output=" << out.size()
            << " status=" << static_cast<int>(status)
            << " records_fetched=" << work.records_fetched
            << " entries_visited=" << work.entries_visited
            << " bytes_inspected=" << work.bytes_inspected
            << " index_seeks=" << work.index_seeks << '\n';
}
int main() {
  {
    EngineConfig cfg;
    cfg.ring_bytes = 1U << 24;
    cfg.max_record_bytes = 1024;
    Engine engine(cfg);
    const auto hot = engine.intern("r/s/hot");
    const auto sub = engine.compile({{{Term::Exact, "r/s/quiet"}}});
    for (unsigned i = 0; i < 1000000; ++i) engine.publish(hot, {});
    engine.check_invariants();
    for (const auto mode : {ReplayMode::Scan, ReplayMode::Indexed, ReplayMode::Auto})
      report("work_budget", engine, sub, 0, mode);
  }
  {
    EngineConfig cfg;
    cfg.ring_bytes = 1U << 17;
    cfg.max_record_bytes = 1024;
    cfg.index.blocks = 16;
    Engine engine(cfg);
    const auto a = engine.intern("r/a/events");
    const auto b = engine.intern("r/b/events");
    const auto sub = engine.compile({{{Term::Exact, "r/a/events"}}});
    for (unsigned i = 0; i < 1023; ++i) engine.publish(a, {});
    const auto after = engine.stats().head_seq - 1;
    for (unsigned i = 0; i < 4000; ++i) engine.publish(b, {});
    engine.publish(a, {});
    const auto partition = engine.registry().get(a).partition;
    const auto lower = engine.ring().seek_after(after);
    const auto estimate = engine.index()->estimate_count(partition, lower, engine.stats().head_pos);
    std::cout << "auto_boundary estimate=" << estimate << " actual_selected_postings=1"
              << " range_records=" << engine.stats().head_seq - 1 - after << '\n';
    engine.check_invariants();
    for (const auto mode : {ReplayMode::Indexed, ReplayMode::Auto})
      report("auto_boundary", engine, sub, after, mode);
  }
}
