#include "tiplog/driver/trace_driver.hpp"
#include "scan_oracle.hpp"

#include <gtest/gtest.h>

#include <limits>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {
using namespace tiplog;

void u64(std::vector<std::byte>& bytes, std::size_t offset, std::uint64_t value, unsigned width) {
  for (unsigned i = 0; i < width; ++i) {
    bytes.at(offset + i) = static_cast<std::byte>(value & 255U);
    value >>= 8;
  }
}
void append_number(std::vector<std::byte>& bytes, std::uint64_t value, unsigned width) {
  const auto offset = bytes.size();
  bytes.resize(offset + width);
  u64(bytes, offset, value, width);
}
std::vector<std::byte> synthetic_trace(std::size_t count = 7) {
  // Independently hand-encoded trace-v1 bytes. Sparse dictionary IDs ensure
  // the driver resolves actual IDs, rather than indexing by dictionary order.
  std::vector<std::byte> bytes(64);
  const std::string_view magic("TPLTRC\0\1", 8);
  for (std::size_t i = 0; i < magic.size(); ++i) bytes[i] = static_cast<std::byte>(magic[i]);
  u64(bytes, 8, 1, 4);
  u64(bytes, 16, count, 8);
  for (std::size_t i = 0; i < count; ++i) {
    const auto start = bytes.size();
    bytes.resize(start + 24);
    u64(bytes, start, i % 2 == 0 ? 7 : 900001, 4);
    u64(bytes, start + 4, 1, 2);
    u64(bytes, start + 8, 100 + i, 8);
    bytes[start + 16] = std::byte{42};
  }
  const auto dict_offset = bytes.size();
  append_number(bytes, 2, 4);
  for (unsigned i = 0; i < 2; ++i) {
    const std::string_view path = i == 0 ? "itch/A/add" : "itch/B/add";
    append_number(bytes, i == 0 ? 7 : 900001, 4);
    append_number(bytes, path.size(), 2);
    for (const char value : path) bytes.push_back(static_cast<std::byte>(value));
  }
  u64(bytes, 24, dict_offset, 8);
  u64(bytes, 32, bytes.size() - dict_offset, 8);
  return bytes;
}

TEST(TraceDriver, SparseIdsMapPathsAndOpaquePayloadsInGlobalOrder) {
  const auto bytes = synthetic_trace();
  const trace::Reader reader{std::span<const std::byte>(bytes)};
  ref::ScanOracle oracle({512, 256});
  std::vector<driver::Tick> ticks;
  const auto result = driver::drive_trace(reader, {},
      [&oracle](auto path, auto payload) { return oracle.publish(path, payload); },
      [&ticks](const auto& tick) { ticks.push_back(tick); });
  EXPECT_EQ(result.published, 7);
  EXPECT_EQ(result.payload_bytes, 7);
  EXPECT_EQ(result.first_seq, 1);
  EXPECT_EQ(result.last_seq, 7);
  ASSERT_EQ(oracle.full_records().size(), 7);
  EXPECT_EQ(oracle.full_records()[0].path, "itch/A/add");
  EXPECT_EQ(oracle.full_records()[1].path, "itch/B/add");
  EXPECT_EQ(oracle.full_records()[0].payload, (std::vector<std::byte>{std::byte{42}}));
  ASSERT_EQ(ticks.size(), 7);
  EXPECT_EQ(ticks.front(), (driver::Tick{1, 1, 64, false}));
  EXPECT_EQ(ticks.back(), (driver::Tick{7, 7, 64, false}));
}

TEST(TraceDriver, ScriptedPausesCadenceAndMaxRecordsAreDeterministic) {
  const auto bytes = synthetic_trace();
  const trace::Reader reader{std::span<const std::byte>(bytes)};
  driver::Config config;
  config.seed = 456;
  config.max_records = 6;
  config.consume_every = 2;
  config.batch_budget = 3;
  config.pauses = {{2, 3}};
  auto run = [&] {
    Seq seq = 0;
    std::vector<driver::Tick> ticks;
    const auto result = driver::drive_trace(reader, config,
        [&seq](auto, auto) { return ++seq; }, [&ticks](const auto& tick) { ticks.push_back(tick); });
    return std::pair{result, ticks};
  };
  const auto [first, ticks] = run();
  const auto [second, repeated] = run();
  EXPECT_EQ(first, second);
  EXPECT_EQ(ticks, repeated);
  EXPECT_EQ(first.published, 6);
  ASSERT_EQ(ticks.size(), 6);
  EXPECT_EQ(ticks[0].budget, 0);
  EXPECT_TRUE(ticks[1].paused);
  EXPECT_EQ(ticks[1].budget, 0);
  EXPECT_TRUE(ticks[3].paused);
  EXPECT_FALSE(ticks[4].paused);
  EXPECT_EQ(ticks[5].budget, 3);
}

TEST(TraceDriver, SeededBudgetsRepeatAndZeroBudgetDoesNotAdvanceReplay) {
  const auto bytes = synthetic_trace();
  const trace::Reader reader{std::span<const std::byte>(bytes)};
  driver::Config config;
  config.seed = 81234;
  config.jitter_budget = true;
  config.batch_budget = 1000000;
  auto run = [&](std::uint64_t seed) {
    auto changed = config;
    changed.seed = seed;
    Seq seq = 0;
    std::vector<driver::Tick> ticks;
    auto result = driver::drive_trace(reader, changed, [&seq](auto, auto) { return ++seq; },
        [&ticks](const auto& tick) { ticks.push_back(tick); });
    return std::pair{result, ticks};
  };
  const auto same = run(config.seed);
  EXPECT_EQ(same, run(config.seed));
  const auto changed = run(config.seed + 1);
  EXPECT_EQ(same.first.publication_digest, changed.first.publication_digest);
  EXPECT_NE(same.first.schedule_digest, changed.first.schedule_digest);
  for (const auto& tick : same.second) EXPECT_GE(tick.budget, 1);
  config.batch_budget = 0;
  ref::ScanOracle oracle({512, 256});
  const SubscriptionSpec spec{{{Term::Subtree, "itch"}}};
  std::vector<ref::OracleRecord> out;
  driver::drive_trace(reader, config,
      [&oracle](auto path, auto payload) { return oracle.publish(path, payload); },
      [&](const auto& tick) {
        auto replay = oracle.open_replay(spec, 0);
        const auto before = replay.checkpoint();
        EXPECT_EQ(tick.budget, 0);
        EXPECT_EQ(replay.next_batch(tick.budget, out), Status::More);
        EXPECT_EQ(before, replay.checkpoint());
      });
}

TEST(TraceDriver, InvalidConfigurationsAndPublisherFailuresRemainExplicit) {
  const auto bytes = synthetic_trace();
  const trace::Reader reader{std::span<const std::byte>(bytes)};
  driver::Config config;
  EXPECT_THROW(driver::drive_trace(reader, config, {}), std::invalid_argument);
  config.consume_every = 0;
  EXPECT_THROW(driver::drive_trace(reader, config, [](auto, auto) { return Seq{1}; }), std::invalid_argument);
  config.consume_every = 1;
  config.pauses = {{0, 2}};
  EXPECT_THROW(driver::drive_trace(reader, config, [](auto, auto) { return Seq{1}; }), std::invalid_argument);
  config.pauses = {{std::numeric_limits<std::uint64_t>::max(), 2}};
  EXPECT_THROW(driver::drive_trace(reader, config, [](auto, auto) { return Seq{1}; }), std::invalid_argument);
  config.pauses.clear();
  EXPECT_THROW(driver::drive_trace(reader, config, [](auto, auto) { return Seq{0}; }), std::logic_error);
  EXPECT_THROW(driver::drive_trace(reader, config, [](auto, auto) { return Seq{1}; }), std::logic_error);
  EXPECT_THROW(driver::drive_trace(reader, config, [](auto, auto) -> Seq { throw std::runtime_error("publish rejection"); }), std::runtime_error);
}

TEST(TraceDriver, EmptyLimitAndEmptyTraceReportNoPublications) {
  const auto bytes = synthetic_trace();
  const trace::Reader reader{std::span<const std::byte>(bytes)};
  driver::Config config;
  config.max_records = 0;
  unsigned calls = 0;
  const auto result = driver::drive_trace(reader, config, [&calls](auto, auto) { ++calls; return Seq{1}; });
  EXPECT_EQ(calls, 0);
  EXPECT_EQ(result.published, 0);
  EXPECT_EQ(result.first_seq, 0);
  EXPECT_EQ(result.last_seq, 0);
  const auto empty_bytes = synthetic_trace(0);
  const trace::Reader empty{std::span<const std::byte>(empty_bytes)};
  EXPECT_EQ(driver::drive_trace(empty, {}, [](auto, auto) { return Seq{1}; }).published, 0);
}
}  // namespace
