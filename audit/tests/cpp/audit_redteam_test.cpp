// Audit red-team demonstrations. These are non-destructive, local, synthetic
// measurements. They PASS when the demonstration ran; the numbers they print
// are the evidence. Failing acceptance contracts live in audit_red_spec_test.
#include "tiplog/engine/engine.hpp"
#include "tiplog/trace/reader.hpp"

#include <gtest/gtest.h>
#include <malloc.h>

#include <chrono>
#include <random>
#include <string>
#include <vector>

namespace tiplog {
namespace {
using Clock = std::chrono::steady_clock;
double seconds_since(Clock::time_point t) {
  return std::chrono::duration<double>(Clock::now() - t).count();
}
std::size_t heap_in_use() { return mallinfo2().uordblks + mallinfo2().hblkhd; }

std::string deep_path(std::size_t depth) {
  std::string path = "a";
  for (std::size_t i = 1; i < depth; ++i) path += "/a";
  return path;
}

// RT-1: one deep topic path. Registry::intern stores every ancestor's full
// path (sum of prefix lengths ~ depth^2 bytes) and subscription matching
// hashes every prefix of every topic (~depth^3 byte-hash work in compile()).
TEST(AuditRedTeam, DeepTopicPathCostGrowth) {
  for (const std::size_t depth : {250U, 500U, 1000U, 2000U}) {
    Engine engine;
    const auto before = heap_in_use();
    auto t = Clock::now();
    const auto id = engine.intern(deep_path(depth));
    const double intern_s = seconds_since(t);
    const auto heap = heap_in_use() - before;
    t = Clock::now();
    const auto sub = engine.compile({{{Term::Subtree, "zz/q"}}});  // unrelated subscription
    const double compile_s = seconds_since(t);
    std::printf("[audit] depth=%zu path_bytes=%zu topics=%zu heap_delta=%zu intern_s=%.4f compile_s=%.4f\n",
                depth, 2 * depth - 1, engine.registry().topic_count(), heap, intern_s, compile_s);
    EXPECT_NE(id, 0U);
    (void)sub;
  }
}

// RT-2: subtree-hook fan-out. Each new topic under a hooked root deduplicates
// affected observers with a linear search, so per-intern cost grows with the
// square of the number of live subscriptions sharing that root.
TEST(AuditRedTeam, SubscriptionFanoutInternCost) {
  for (const std::size_t subscriptions : {500U, 2000U, 8000U}) {
    Engine engine;
    std::vector<subs::CompiledSubscription> keep;
    keep.reserve(subscriptions);
    for (std::size_t i = 0; i < subscriptions; ++i)
      keep.push_back(engine.compile({{{Term::Subtree, "s/X"}}}));
    const auto t = Clock::now();
    for (int i = 0; i < 20; ++i) (void)engine.intern("s/X/t" + std::to_string(i));
    std::printf("[audit] subscriptions=%zu per_new_topic_ms=%.3f\n", subscriptions,
                seconds_since(t) * 1000.0 / 20.0);
  }
}

// RT-3 (hypothesis check, expected NOT a defect): ForceEvict pressure walks
// is_boundary() from the tail only to the oldest block's end, i.e. the items
// it evicts anyway. Compare steady-state publish cost, sized vs undersized.
TEST(AuditRedTeam, PressurePublishCostIsProportionalToEviction) {
  auto measure = [](std::uint32_t blocks) {
    EngineConfig config;
    config.ring_bytes = std::size_t{1} << 26;  // 64 MiB, ~2M 32-byte records
    config.max_record_bytes = 256;
    config.index.entries_per_block = 1024;
    config.index.blocks = blocks;
    Engine engine(config);
    std::vector<TopicId> topics;
    for (int p = 0; p < 16; ++p) topics.push_back(engine.intern("p/" + std::to_string(p) + "/e"));
    const std::vector<std::byte> payload(16, std::byte{1});
    std::mt19937_64 random(1);
    for (int i = 0; i < 3'000'000; ++i) engine.publish(topics[random() % topics.size()], payload);
    const auto t = Clock::now();
    for (int i = 0; i < 1'000'000; ++i) engine.publish(topics[random() % topics.size()], payload);
    return std::make_pair(seconds_since(t) * 1e3, engine.ring().stats().pressure_data_evicted);
  };
  const auto sized = measure(index::Index::sizing_blocks(std::size_t{1} << 26, 16, 1024, 32));
  const auto pressured = measure(400);
  std::printf("[audit] 1M publishes: sized_ms=%.1f (pressure_evicted=%lu) undersized_ms=%.1f (pressure_evicted=%lu) ratio=%.2f\n",
              sized.first, static_cast<unsigned long>(sized.second), pressured.first,
              static_cast<unsigned long>(pressured.second), pressured.first / sized.first);
  EXPECT_EQ(sized.second, 0U);
  EXPECT_GT(pressured.second, 0U);
}

// RT-4: trace dictionary memory amplification. Reader::validate keeps a vector,
// an id map and a path set for every 7+ byte dictionary entry.
TEST(AuditRedTeam, TraceDictionaryMemoryAmplification) {
  const std::size_t entries = 200000;
  std::vector<std::byte> bytes(64);
  auto put = [&](std::uint64_t v, int n) {
    for (int i = 0; i < n; ++i) bytes.push_back(static_cast<std::byte>((v >> (8 * i)) & 0xff));
  };
  const auto dict_offset = bytes.size();
  put(entries, 4);
  for (std::size_t i = 1; i <= entries; ++i) {
    char path[16];
    const int n = std::snprintf(path, sizeof path, "%07zu", i);
    put(i, 4);
    put(static_cast<std::uint64_t>(n), 2);
    for (int c = 0; c < n; ++c) bytes.push_back(static_cast<std::byte>(path[c]));
  }
  const char magic[8] = {'T', 'P', 'L', 'T', 'R', 'C', 0, 1};
  for (int i = 0; i < 8; ++i) bytes[i] = static_cast<std::byte>(magic[i]);
  auto set = [&](std::size_t at, std::uint64_t v, int n) {
    for (int i = 0; i < n; ++i) bytes[at + i] = static_cast<std::byte>((v >> (8 * i)) & 0xff);
  };
  set(8, 1, 4);
  set(24, dict_offset, 8);
  set(32, bytes.size() - dict_offset, 8);
  const auto before = heap_in_use();
  const trace::Reader reader{std::span<const std::byte>(bytes)};
  const auto delta = heap_in_use() - before;
  std::printf("[audit] trace_bytes=%zu dictionary_entries=%zu reader_heap_bytes=%zu amplification=%.1fx\n",
              bytes.size(), reader.dictionary().size(), delta,
              static_cast<double>(delta) / static_cast<double>(bytes.size()));
  EXPECT_EQ(reader.dictionary().size(), entries);
}

// RT-5: Ring::at() on a retained, 8-aligned, non-boundary position decodes
// payload bytes as a header and returns a fabricated item instead of throwing.
TEST(AuditRedTeam, RingAtInteriorPositionFabricatesItem) {
  Engine engine({1024, 256});
  const auto topic = engine.intern("a/b/c");
  std::vector<std::byte> payload(40, std::byte{0});
  payload[0] = std::byte{24};    // word0: DATA, size 24, fill 0
  payload[4] = std::byte{1};     // topic 1
  payload[8] = std::byte{0x39};  // seq 0x39 = 57, never published
  engine.publish(topic, payload);
  bool threw = false;
  ring::Item item{};
  try {
    item = engine.ring().at(16);  // inside the first record's payload
  } catch (const std::exception&) {
    threw = true;
  }
  std::printf("[audit] ring.at(16) threw=%d pad=%d seq=%lu size=%zu\n", threw, item.pad,
              static_cast<unsigned long>(item.seq), item.size);
  EXPECT_FALSE(threw) << "demonstration expects the fabricated-item behavior";
  EXPECT_EQ(item.seq, 57U);
}

}  // namespace
}  // namespace tiplog
