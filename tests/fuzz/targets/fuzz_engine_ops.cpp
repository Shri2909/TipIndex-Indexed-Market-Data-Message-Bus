#include "tiplog/engine/engine.hpp"
#include "scan_oracle.hpp"
#include "oracle_tail.hpp"
#include "../pressure_fixture.hpp"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace tiplog;

void require(bool value) {
  if (!value) std::abort();
}

struct Bytes {
  const std::uint8_t* data;
  std::size_t size;
  std::size_t offset{};
  unsigned take() { return offset < size ? data[offset++] : 0U; }
};

struct ReaderPair {
  std::optional<Replay> actual;
  std::optional<ref::OracleReplay> expected;
};
struct TailPair {
  std::optional<Tail> actual;
  std::optional<ref::OracleTail> expected;
};

void compare_state(const Engine& engine, const ref::ScanOracle& oracle) {
  const auto stats = engine.stats();
  require(stats.head_pos == oracle.head_pos());
  require(stats.tail_pos == oracle.tail_pos());
  require(stats.head_seq == oracle.head_seq());
  require(stats.tail_seq == oracle.tail_seq());
  engine.check_invariants();
}

void compare_reader(const ReaderPair& pair) {
  require(pair.actual.has_value() == pair.expected.has_value());
  if (!pair.actual) return;
  require(pair.actual->status() == pair.expected->status());
  require(pair.actual->error() == pair.expected->error());
  require(pair.actual->checkpoint() == pair.expected->checkpoint());
  require(pair.actual->upper_seq() == pair.expected->upper_seq());
  require(pair.actual->upper_pos() == pair.expected->upper_pos());
}

void batch(ReaderPair& pair, const Engine& engine, std::size_t budget) {
  if (!pair.actual) return;
  std::vector<Delivered> actual;
  std::vector<ref::OracleRecord> expected;
  require(pair.actual->next_batch(budget, actual) ==
          pair.expected->next_batch(budget, expected));
  require(actual.size() == expected.size());
  for (std::size_t i = 0; i < actual.size(); ++i) {
    require(actual[i].seq == expected[i].seq && actual[i].pos == expected[i].pos);
    require(engine.registry().get(actual[i].topic).path == expected[i].path);
    require(std::ranges::equal(actual[i].payload, expected[i].payload));
    if (i != 0) require(actual[i - 1].seq < actual[i].seq);
  }
  compare_reader(pair);
}
void tail_batch(TailPair& pair, const Engine& engine, std::size_t budget) {
  require(pair.actual.has_value() == pair.expected.has_value());
  if (!pair.actual) return;
  std::vector<Delivered> actual;
  std::vector<ref::OracleRecord> expected;
  require(pair.actual->poll(budget, actual) == pair.expected->poll(budget, expected));
  require(actual.size() == expected.size());
  for (std::size_t i = 0; i < actual.size(); ++i) {
    require(actual[i].seq == expected[i].seq && actual[i].pos == expected[i].pos);
    require(engine.registry().get(actual[i].topic).path == expected[i].path);
    require(std::ranges::equal(actual[i].payload, expected[i].payload));
    if (i != 0) require(actual[i-1].seq < actual[i].seq);
  }
  require(pair.actual->status() == pair.expected->status());
  require(pair.actual->error() == pair.expected->error());
  require(pair.actual->checkpoint() == pair.expected->checkpoint());
  require(pair.actual->upper_seq() == pair.expected->upper_seq());
  require(pair.actual->upper_pos() == pair.expected->upper_pos());
}

}  // namespace

// Synthetic operation grammar: configuration byte, then variable op fields.
// Oracle matching and retention share no production implementation helpers.
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
  if (size == 0) return 0;
  Bytes input{data, size};
  const auto configuration = input.take();
  const char* mode_name = std::getenv("TIPLOG_FUZZ_MODE");
  const bool indexed = mode_name != nullptr && std::string_view(mode_name) == "indexed";
  const bool integrated = mode_name != nullptr && std::string_view(mode_name) == "all";
  const auto mode = indexed ? ReplayMode::Indexed : ReplayMode::Scan;
  if (indexed && (configuration & 128U) != 0) tiplog::fuzz::pressure_fixture();
  if (integrated && (configuration & 128U) != 0)
    for (const auto kernel : {MergeKernel::StdPQ, MergeKernel::BinHeap,
                             MergeKernel::Quad, MergeKernel::Loser})
      tiplog::fuzz::pressure_fixture(kernel);
  const std::size_t capacity = std::size_t{1} << (6U + configuration % 8U);
  EngineConfig config;
  config.ring_bytes = capacity;
  config.max_record_bytes = std::min(capacity / 2, std::size_t{256});
  config.ckpt_log2 = 2;
  // Independently sufficient for these registered partitions, including B=1.
  // The separate fixture exercises true pressure; this random branch keeps the
  // oracle's independent capacity-retention model unchanged.
  config.index.entries_per_block = 1U << ((configuration >> 3U) % 3U);
  config.index.blocks = static_cast<std::uint32_t>(capacity / 16 + 64);
  config.index.sweep_evictions = 7;
  config.auto_max_partitions = (configuration & 32U) != 0 ? 0 : 64;
  config.auto_max_index_fraction = (configuration & 64U) != 0 ? 1 : 0.25;
  Engine engine(config);
  ref::ScanOracle oracle({capacity, config.max_record_bytes});
  const std::vector<std::string> paths{
      "md/A/add", "md/A/delete", "md/A", "md/B/add", "md/B/delete",
      "md/future/sub/one", "root", "other/z", "md/C/deep/event"};
  std::vector<TopicId> topics;
  for (const auto& path : paths) topics.push_back(engine.intern(path));
  const std::vector<SubscriptionSpec> specs{
      {{{Term::Subtree, "md/A"}}},
      {{{Term::Exact, "md/A/add"}}},
      {{{Term::Subtree, "md"}}},
      {{{Term::Subtree, "md/A"}, {Term::Exact, "md/A/add"},
        {Term::Exact, "md/B/delete"}}},
      {{{Term::Exact, "md/missing"}}},
      {{{Term::Subtree, "md/future/sub"}}},
      {{{Term::Exact, "root"}}},
      {{{Term::Subtree, "other"}, {Term::Subtree, "md/C"}}}};
  std::vector<subs::CompiledSubscription> compiled;
  for (const auto& spec : specs) compiled.push_back(engine.compile(spec));
  std::array<ReaderPair, 4> readers;
  std::array<TailPair, 4> tails;
  for (std::size_t operations = 0; input.offset < input.size && operations < 16384;
       ++operations) {
    const auto opcode = input.take() % (integrated ? 12U : 8U);
    const auto slot = input.take() % readers.size();
    auto& pair = readers[slot];
    if (opcode == 0U || opcode == 4U) {
      auto path = paths[input.take() % paths.size()];
      TopicId topic{};
      if (opcode == 4U) {
        path = "md/future/sub/new" + std::to_string(input.take() % 64U);
        topic = engine.intern(path);
      } else {
        const auto found = engine.registry().find(path);
        require(found.has_value());
        topic = *found;
      }
      const auto length = input.take() % (config.max_record_bytes - 16 + 1);
      const auto value = static_cast<std::byte>(input.take());
      const std::vector<std::byte> payload(length, value);
      require(engine.publish(topic, payload) == oracle.publish(path, payload));
    } else if (opcode == 1U) {
      const auto choice = input.take();
      constexpr std::array<std::size_t, 5> single_partition{0, 1, 4, 5, 6};
      const auto subscription = indexed ? single_partition[choice % single_partition.size()]
                                        : choice % specs.size();
      const auto selection = input.take() % 8U;
      Seq after{};
      if (selection == 1U && pair.expected && pair.expected->checkpoint())
        after = pair.expected->checkpoint()->after_seq;
      else if (selection == 2U) after = oracle.tail_seq() - 1;
      else if (selection == 3U) after = oracle.head_seq() - 1;
      else if (selection == 4U) after = oracle.head_seq() + 3;
      else if (selection == 5U) after = std::numeric_limits<Seq>::max();
      else if (selection == 6U) after = input.take() % oracle.head_seq();
      else if (selection == 7U) after = oracle.tail_seq() > 1 ? oracle.tail_seq() - 2 : 0;
      const auto selected_mode = integrated ? static_cast<ReplayMode>(input.take() % 3U) : mode;
      const auto kernel = integrated ? static_cast<MergeKernel>(input.take() % 4U) : MergeKernel::StdPQ;
      pair.actual.emplace(engine.open_replay(compiled[subscription], after, selected_mode, kernel));
      pair.expected.emplace(oracle.open_replay(specs[subscription], after));
      compare_reader(pair);
    } else if (opcode == 2U) {
      batch(pair, engine, input.take() % 9U);
    } else if (opcode == 3U) {
      pair.actual.reset();
      pair.expected.reset();
    } else if (opcode == 5U) {
      for (unsigned count = 0; count < 16U && pair.actual &&
           pair.actual->status() == Status::More; ++count)
        batch(pair, engine, 16);
    } else if (opcode == 6U) {
      const auto before = engine.stats();
      const auto path_index = input.take() % paths.size();
      const std::vector<std::byte> oversized(config.max_record_bytes, std::byte{1});
      bool actual_rejected = false;
      bool expected_rejected = false;
      try { (void)engine.publish(topics[path_index], oversized); }
      catch (const std::length_error&) { actual_rejected = true; }
      try { (void)oracle.publish(paths[path_index], oversized); }
      catch (const std::length_error&) { expected_rejected = true; }
      require(actual_rejected && expected_rejected);
      const auto after = engine.stats();
      require(before.head_pos == after.head_pos && before.tail_pos == after.tail_pos &&
              before.head_seq == after.head_seq && before.tail_seq == after.tail_seq);
    } else if (opcode == 7U) {
      // Zero-budget calls must preserve progress even if retention has advanced.
      for (auto& reader : readers) batch(reader, engine, 0);
      for (auto& tail : tails) tail_batch(tail, engine, 0);
    } else if (opcode == 8U) {
      auto& tail = tails[slot];
      const auto subscription = input.take() % specs.size();
      const auto selection = input.take() % 8U;
      Seq after = 0;
      if (selection == 1U && tail.expected && tail.expected->checkpoint()) after = tail.expected->checkpoint()->after_seq;
      else if (selection == 2U) after = oracle.tail_seq() - 1;
      else if (selection == 3U) after = oracle.head_seq() - 1;
      else if (selection == 4U) after = oracle.head_seq() + 3;
      else if (selection == 5U) after = std::numeric_limits<Seq>::max();
      else if (selection == 6U) after = input.take() % oracle.head_seq();
      else if (selection == 7U) after = oracle.tail_seq() > 1 ? oracle.tail_seq() - 2 : 0;
      const auto selected_mode = static_cast<ReplayMode>(input.take() % 3U);
      const auto kernel = static_cast<MergeKernel>(input.take() % 4U);
      bool actual_rejected = false, expected_rejected = false;
      try { tail.actual.emplace(engine.open_tail(compiled[subscription], after, selected_mode, kernel)); }
      catch (const InvalidRange&) { actual_rejected = true; }
      try { tail.expected.emplace(ref::OracleTail(oracle, specs[subscription], after)); }
      catch (const std::invalid_argument&) { expected_rejected = true; }
      require(actual_rejected == expected_rejected);
      tail_batch(tail, engine, 0);
    } else if (opcode == 9U) {
      tail_batch(tails[slot], engine, input.take() % 9U);
    } else if (opcode == 10U) {
      tails[slot].actual.reset(); tails[slot].expected.reset();
    } else {
      for (auto& tail : tails) tail_batch(tail, engine, 8);
    }
    compare_state(engine, oracle);
  }
  for (auto& pair : readers) {
    for (unsigned count = 0; count < 1024U && pair.actual &&
         pair.actual->status() == Status::More; ++count)
      batch(pair, engine, 32);
  }
  for (auto& tail : tails) tail_batch(tail, engine, 32);
  return 0;
}
