#pragma once

#include "tiplog/engine/engine.hpp"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <optional>
#include <vector>

namespace tiplog::fuzz {

// Independently calculated before P4 implementation. See
// results/p3/p4-pressure-fixture-plan.md: these expected tails are not copied
// from the engine or supplied to the capacity-only ScanOracle.
inline void pressure_fixture(MergeKernel kernel = MergeKernel::StdPQ) {
  auto check = [](bool value) { if (!value) std::abort(); };
  EngineConfig config;
  config.ring_bytes = 64;
  config.max_record_bytes = 32;
  config.index_enabled = true;
  config.index.blocks = 1;
  config.index.entries_per_block = 1;
  config.pool_policy = PoolPolicy::ForceEvict;
  Engine engine(config);
  const auto a = engine.intern("pressure/A/event");
  const auto b = engine.intern("pressure/B/event");
  const auto asub = engine.compile({{{Term::Exact, "pressure/A/event"}}});
  const auto bsub = engine.compile({{{Term::Exact, "pressure/B/event"}}});
  constexpr std::array<std::size_t, 5> lengths{10, 4, 8, 0, 8};
  constexpr std::array<LogPos, 5> starts{0, 32, 64, 88, 104};
  constexpr std::array<LogPos, 5> heads{32, 56, 88, 104, 128};
  constexpr std::array<LogPos, 5> tails{0, 32, 56, 88, 104};
  constexpr std::array<std::uint64_t, 5> pressure_bytes{0, 32, 56, 88, 104};
  constexpr std::array<std::uint64_t, 5> evicted_data_bytes{0, 32, 56, 80, 96};
  std::optional<Replay> unfinished, exact_budget, unmatched;
  std::vector<Delivered> out;
  for (std::size_t i = 0; i < lengths.size(); ++i) {
    const auto topic = i % 2 == 0 ? a : b;
    const std::vector<std::byte> payload(lengths[i], std::byte{0x6a});
    check(engine.publish(topic, payload) == i + 1);
    check(engine.stats().head_pos == heads[i]);
    check(engine.stats().tail_pos == tails[i]);
    check(engine.stats().tail_seq == i + 1);
    const auto& stats = engine.ring().stats();
    check(stats.data_evicted == i && stats.pressure_data_evicted == i);
    check(stats.pressure_bytes_evicted == pressure_bytes[i]);
    check(stats.data_bytes_evicted == evicted_data_bytes[i]);
    const auto index_stats = engine.index()->stats();
    check(index_stats.gauges.live_entries == 1);
    check(index_stats.gauges.allocated_blocks == 1);
    check(index_stats.gauges.free_blocks == 0);
    check(index_stats.gauges.open_slack == 0);
    check(index_stats.gauges.sealed_partial_slack == 0);
    check(index_stats.counters.allocations == i + 1);
    check(index_stats.counters.frees == i);
    check(index_stats.allocated_high_water == 1);
    check(engine.index()->metadata()[0].gen == i);
    const auto record = engine.ring().at(starts[i]);
    check(!record.pad && record.seq == i + 1 && record.topic == topic);
    engine.check_invariants();
    // Fresh reads must return the newest golden event after each reuse. Both
    // modes share the expected result; neither mode supplies the other's tail.
    const auto& newest_sub = i % 2 == 0 ? asub : bsub;
    for (const auto mode : {ReplayMode::Scan, ReplayMode::Indexed}) {
      auto newest = engine.open_replay(newest_sub, static_cast<Seq>(i), mode, kernel);
      check(newest.next_batch(2, out) == Status::Done);
      check(out.size() == 1 && out.front().seq == i + 1);
      check(out.front().pos == starts[i] && out.front().topic == topic);
      check(std::ranges::equal(out.front().payload, payload));
      check(newest.checkpoint() == (ResumeCheckpoint{i + 1, heads[i]}));
      check(!newest.error());
    }
    if (i == 0) {
      unfinished.emplace(engine.open_replay(asub, Seq{0}, ReplayMode::Indexed, kernel));
      exact_budget.emplace(engine.open_replay(asub, Seq{0}, ReplayMode::Indexed, kernel));
      unmatched.emplace(engine.open_replay(bsub, Seq{0}, ReplayMode::Indexed, kernel));
      check(exact_budget->next_batch(1, out) == Status::More);
      check(out.size() == 1 && out.front().seq == 1);
      check(exact_budget->checkpoint() == (ResumeCheckpoint{1, 32}));
    } else if (i == 1) {
      const auto cp = unfinished->checkpoint();
      check(unfinished->next_batch(0, out) == Status::More);
      check(unfinished->checkpoint() == cp && out.empty());
      check(unfinished->next_batch(1, out) == Status::Error && out.empty());
      check(unfinished->error() == (ReplayError{ReplayError::FellBehind, 0, 0, 2}));
      check(unmatched->next_batch(1, out) == Status::Error && out.empty());
      check(unmatched->error() == (ReplayError{ReplayError::FellBehind, 0, 0, 2}));
    } else if (i == 2) {
      // Captured upper completion wins even though the tail is now beyond it.
      check(exact_budget->next_batch(1, out) == Status::Done && out.empty());
      check(exact_budget->checkpoint() == (ResumeCheckpoint{1, 32}));
      check(!exact_budget->error());
    }
  }

  config.pool_policy = PoolPolicy::RejectPublish;
  Engine rejected(config);
  const auto ra = rejected.intern("pressure/A/event");
  const auto rb = rejected.intern("pressure/B/event");
  const std::vector<std::byte> first(10, std::byte{0x6a});
  check(rejected.publish(ra, first) == 1);
  const auto before = rejected.stats();
  const auto ring_stats = rejected.ring().stats();
  const auto index_stats = rejected.index()->stats();
  const auto metadata = rejected.index()->metadata();
  const auto postings = rejected.index()->entries();
  const auto storage_span = rejected.ring().storage_bytes();
  const std::vector<std::byte> storage(storage_span.begin(), storage_span.end());
  bool pool_rejected = false;
  try {
    (void)rejected.publish(rb, std::vector<std::byte>(4, std::byte{0x2b}));
  } catch (const PoolExhausted&) {
    pool_rejected = true;
  }
  check(pool_rejected);
  const auto after = rejected.stats();
  check(before.head_pos == after.head_pos && before.tail_pos == after.tail_pos);
  check(before.head_seq == after.head_seq && before.tail_seq == after.tail_seq);
  check(rejected.ring().stats() == ring_stats);
  check(rejected.index()->stats().gauges == index_stats.gauges);
  check(rejected.index()->stats().counters == index_stats.counters);
  check(rejected.index()->metadata() == metadata);
  check(rejected.index()->entries() == postings);
  const auto after_storage = rejected.ring().storage_bytes();
  check(std::equal(storage.begin(), storage.end(), after_storage.begin(), after_storage.end()));
  rejected.check_invariants();
}

}  // namespace tiplog::fuzz
