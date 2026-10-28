#include "../../tools/tiplog_bench/contracts.hpp"
#include "../../tools/file_safety.hpp"
#include "bench_log.hpp"
#include "tiplog/index/index.hpp"
#include "tiplog/topics/registry.hpp"
#include "tiplog/trace/reader.hpp"

#include <benchmark/benchmark.h>

#include <algorithm>
#include <array>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <numeric>
#include <regex>
#include <sstream>
#include <unordered_map>

namespace {
using namespace tiplog;
namespace tb = tiplog::bench;
constexpr std::uint64_t basis = 14695981039346656037ULL;
std::uint64_t fold(std::uint64_t state, std::uint64_t value) {
  return (state ^ value) * 1099511628211ULL;
}
struct Query {
  PartitionId partition;
  LogPos lower, expected;
};
struct Data {
  std::filesystem::path trace_path;
  std::uint64_t trace_file_bytes{}, record_limit{};
  std::vector<std::vector<LogPos>> lists;
  std::vector<std::pair<PartitionId, LogPos>> chronological;
  std::vector<Query> queries;
  std::uint64_t scan_hash{basis}, seek_hash{basis};
  std::uint64_t input_hash{basis}, query_hash{basis};
  std::uint64_t records{};
  std::size_t partition_slots{};
  bool diagnostic{};
  LogPos logical_head{};
};
Data make_data(const std::filesystem::path &path, std::uint64_t limit) {
  trace::Reader reader(path);
  topics::Registry registry;
  std::unordered_map<std::uint32_t, PartitionId> partitions;
  for (const auto &topic : reader.dictionary())
    partitions.emplace(topic.id,
                       registry.get(registry.intern(topic.path)).partition);
  Data data;
  data.trace_path = path;
  data.trace_file_bytes = std::filesystem::file_size(path);
  data.record_limit = limit;
  data.partition_slots = registry.partition_count();
  data.lists.resize(data.partition_slots);
  trace::Reader::Cursor cursor;
  trace::Record record;
  while (data.records < limit && reader.next(cursor, record)) {
    const auto partition = partitions.at(record.topic_id);
    data.lists[partition].push_back(data.logical_head);
    data.chronological.emplace_back(partition, data.logical_head);
    data.input_hash = fold(fold(data.input_hash, partition), data.logical_head);
    data.logical_head += (16 + record.payload.size() + 7) & ~std::uint64_t{7};
    ++data.records;
  }
  if (data.records == 0)
    throw std::invalid_argument("M3 requires nonempty real trace");
  data.diagnostic = data.records != reader.header().record_count;
  std::vector<PartitionId> active;
  for (std::size_t p = 0; p < data.partition_slots; ++p) {
    if (!data.lists[p].empty())
      active.push_back(static_cast<PartitionId>(p));
    for (const auto pos : data.lists[p])
      data.scan_hash = fold(data.scan_hash, pos);
  }
  tb::Random random{20191230};
  for (std::size_t i = 0; i < 4096; ++i) {
    const auto p = active[random.bounded(active.size())];
    const auto lower = (random.bounded(data.logical_head / 8) + 1) * 8;
    const auto found =
        std::lower_bound(data.lists[p].begin(), data.lists[p].end(), lower);
    const auto expected = found == data.lists[p].end()
                              ? std::numeric_limits<LogPos>::max()
                              : *found;
    data.queries.push_back({p, lower, expected});
    data.query_hash = fold(fold(data.query_hash, p), lower);
    data.seek_hash = fold(data.seek_hash, expected);
  }
  return data;
}
std::string metadata(const Data &data, std::string_view profile,
                     std::uint32_t block_entries, bool seeks) {
  std::ostringstream out;
  out << "{\"profile\":" << tb::json(profile)
      << ",\"seed\":20191230,\"block_entries\":" << block_entries
      << ",\"records\":" << data.records
      << ",\"input_records\":" << data.records
      << ",\"diagnostic\":" << (data.diagnostic ? "true" : "false")
      << ",\"partition_slots\":" << data.partition_slots
      << ",\"logical_head\":" << data.logical_head
      << ",\"seek_queries\":" << data.queries.size()
      << ",\"operations_per_iteration\":"
      << (seeks ? data.queries.size() : data.records)
      << ",\"trace_path\":" << tb::json(data.trace_path.string())
      << ",\"trace_file_bytes\":" << data.trace_file_bytes
      << ",\"record_limit\":" << data.record_limit
      << ",\"input_hash_hex\":\"" << std::hex << data.input_hash
      << "\",\"query_hash_hex\":\"" << data.query_hash
      << "\",\"expected_hash_hex\":\""
      << (seeks ? data.seek_hash : data.scan_hash) << std::dec
      << "\",\"hash_algorithm\":\"word-xor-multiply64-v1\""
      << ",\"input_hash_scope\":\"chronological (partition, aligned DATA position) words\""
      << ",\"query_hash_scope\":\"(partition, lower bound) words in query order\""
      << ",\"expected_hash_scope\":"
      << tb::json(seeks ? "lower_bound result positions in query order, UINT64_MAX for end"
                        : "positions in partition-id order then ascending position")
      << '}';
  return out.str();
}
void save_metadata(const std::string &line) {
  const auto *path = std::getenv("TIPLOG_BENCH_INPUTS");
  if (!path || !*path)
    return;
  std::ofstream out(path, std::ios::app);
  out << line << '\n';
  out.flush();
  out.close();
  if (!out)
    throw std::runtime_error("cannot write M3 input manifest");
}
std::unique_ptr<index::Index> make_index(const Data &data,
                                         std::uint32_t block_entries) {
  index::Config config;
  config.entries_per_block = block_entries;
  const auto needed = (data.records + block_entries - 1) / block_entries +
                      2 * data.partition_slots + 1;
  if (needed > UINT32_MAX)
    throw std::length_error("M3 pool bound exceeds u32");
  config.blocks = static_cast<std::uint32_t>(needed);
  auto result = std::make_unique<index::Index>(config);
  std::uint64_t count = 0;
  for (const auto &[partition, pos] : data.chronological) {
    auto prep = result->prepare_append(partition, pos, 0, data.partition_slots);
    if (!std::holds_alternative<index::PreparedAppend>(prep))
      throw std::logic_error("M3 pool pressure");
    result->commit(std::move(std::get<index::PreparedAppend>(prep)), ++count);
  }
  result->check_invariants(0);
  for (const auto &query : data.queries) {
    const auto actual = result->seek(query.partition, query.lower);
    if ((actual.valid() ? actual.pos : std::numeric_limits<LogPos>::max()) !=
        query.expected)
      throw std::logic_error("M3 independent lower_bound disagreement");
  }
  const auto stats = result->stats();
  const auto recount = result->recount(0);
  if (stats.gauges != recount.gauges || stats.memory != recount.memory)
    throw std::logic_error("M3 memory recount mismatch");
  return result;
}
std::uint64_t seek(const index::Index &index, const Data &data) {
  auto digest = basis;
  for (const auto &query : data.queries) {
    const auto cursor = index.seek(query.partition, query.lower);
    digest = fold(digest, cursor.valid() ? cursor.pos
                                         : std::numeric_limits<LogPos>::max());
  }
  return digest;
}
std::uint64_t scan(const index::Index &index, const Data &data) {
  auto digest = basis;
  for (std::size_t p = 0; p < data.partition_slots; ++p) {
    auto cursor = index.seek(static_cast<PartitionId>(p), 0);
    while (cursor.valid()) {
      digest = fold(digest, cursor.pos);
      index.advance(cursor, 0);
    }
  }
  return digest;
}
void run(benchmark::State &state, const Data &data, const index::Index &index,
         bool seeks) {
  const auto stats = index.stats();
  const auto outputs = seeks ? data.queries.size() : data.records;
  tiplog::benchlog::Invocation invocation(state.name(), 20191230);
  const auto description = metadata(data, state.name(),
                                    index.config().entries_per_block, seeks);
  save_metadata(description);
  state.SetLabel(description);
  std::uint64_t digest = basis;
  for (auto _ : state) {
    (void)_;
    digest = seeks ? seek(index, data) : scan(index, data);
    benchmark::DoNotOptimize(digest);
    if (digest != (seeks ? data.seek_hash : data.scan_hash)) {
      state.SkipWithError("M3 independent reference digest mismatch");
      break;
    }
  }
  state.SetItemsProcessed(state.iterations() *
                          static_cast<std::int64_t>(outputs));
  state.counters["operations_per_iteration"] = static_cast<double>(outputs);
  state.counters["block_entries"] = index.config().entries_per_block;
  state.counters["input_records"] = static_cast<double>(data.records);
  state.counters["requested_reserved_bytes"] =
      static_cast<double>(stats.memory.reserved_bytes);
  state.counters["live_entries"] =
      static_cast<double>(stats.gauges.live_entries);
  invocation.finish(static_cast<std::uint64_t>(state.iterations()), outputs,
                    digest, state.error_occurred());
}
} // namespace

int main(int argc, char **argv) {
  try {
    std::filesystem::path trace;
    std::uint64_t records = UINT64_MAX;
    bool verify = false;
    std::vector<char *> benchmark_args{argv[0]};
    for (int i = 1; i < argc; ++i) {
      const std::string_view arg = argv[i];
      if (arg == "--verify-only")
        verify = true;
      else if (arg == "--trace" && i + 1 < argc)
        trace = argv[++i];
      else if (arg == "--records" && i + 1 < argc)
        records = tb::number(argv[++i]);
      else
        benchmark_args.push_back(argv[i]);
    }
    if (trace.empty())
      throw std::invalid_argument("M3 requires --trace PATH");
    if (verify && benchmark_args.size() != 1)
      throw std::invalid_argument("unrecognized argument in verification mode: " +
                                  std::string(benchmark_args[1]));
    if (!verify)
      tiplog::cli::check_benchmark_outputs(static_cast<int>(benchmark_args.size()),
                                          benchmark_args.data(), {trace});
    // Initialize first: a selected B arm must not construct the other pools.
    if (!verify) {
      auto count = static_cast<int>(benchmark_args.size());
      benchmark_args.push_back(nullptr);
      benchmark::Initialize(&count, benchmark_args.data());
      if (benchmark::ReportUnrecognizedArguments(count, benchmark_args.data()))
        return 1;
    }
    auto filter = verify ? std::string(".") : benchmark::GetBenchmarkFilter();
    const bool negative = !filter.empty() && filter.front() == '-';
    if (negative) filter.erase(0, 1);
    // Match the pinned Google Benchmark extended-regex filter contract,
    // including its leading '-' exclusion form.
    const std::regex expression(filter, std::regex_constants::extended);
    auto selected = [&](std::string_view name) {
      return std::regex_search(name.begin(), name.end(), expression) != negative;
    };
    std::vector<std::uint32_t> block_sizes;
    for (const auto block_entries : std::array<std::uint32_t, 4>{64, 256, 1024, 4096}) {
      const auto suffix = std::to_string(block_entries);
      if (selected("M3-seek/B" + suffix) || selected("M3-scan/B" + suffix))
        block_sizes.push_back(block_entries);
    }
    if (block_sizes.empty()) {
      benchmark::RunSpecifiedBenchmarks();
      benchmark::Shutdown();
      return 0;
    }
    auto data = make_data(trace, records);
    std::vector<std::unique_ptr<index::Index>> indexes;
    for (const auto block_entries : block_sizes) {
      indexes.push_back(make_index(data, block_entries));
      if (seek(*indexes.back(), data) != data.seek_hash ||
          scan(*indexes.back(), data) != data.scan_hash)
        throw std::logic_error("M3 preflight digest mismatch");
    }
    // Only partition count, query vectors and verified reference hashes are
    // used during timing. Return build-only postings to the allocator first.
    decltype(data.lists){}.swap(data.lists);
    decltype(data.chronological){}.swap(data.chronological);
    if (verify) {
      std::cout
          << "{\"status\":\"ok\",\"records\":" << data.records
          << ",\"partition_slots\":" << data.partition_slots
          << ",\"seek_queries\":" << data.queries.size()
          << ",\"block_sizes\":[64,256,1024,4096],\"independent_references\":"
             "\"per-partition positions plus lower_bound\",\"inputs\":[";
      bool first = true;
      for (const auto &index : indexes)
        for (const bool seeks : {true, false}) {
          if (!first)
            std::cout << ',';
          first = false;
          const auto name = std::string(seeks ? "M3-seek/B" : "M3-scan/B") +
                            std::to_string(index->config().entries_per_block);
          std::cout << metadata(data, name, index->config().entries_per_block, seeks);
        }
      std::cout << "]}\n" << std::flush;
      if (!std::cout) throw std::runtime_error("failed writing M3 verification");
      return 0;
    }
    for (const auto &index : indexes)
      for (const bool seeks : {true, false}) {
        const auto name = std::string(seeks ? "M3-seek/B" : "M3-scan/B") +
                          std::to_string(index->config().entries_per_block);
        benchmark::RegisterBenchmark(
            name.c_str(),
            [&data, index = index.get(), seeks](benchmark::State &state) {
              run(state, data, *index, seeks);
            });
      }
    benchmark::RunSpecifiedBenchmarks();
    benchmark::Shutdown();
    std::cout.flush();
    if (!std::cout) throw std::runtime_error("failed writing stdout result");
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "index_bench: " << error.what() << '\n';
    return 1;
  }
}
