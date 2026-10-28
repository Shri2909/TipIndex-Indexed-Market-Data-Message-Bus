#include "contracts.hpp"
#include "../file_safety.hpp"
#include "tiplog/engine/engine.hpp"
#include "tiplog/trace/reader.hpp"

#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <sched.h>
#include <set>
#include <sstream>
#include <sys/resource.h>
#include <time.h>
#include <unordered_map>
#if defined(__GLIBC__)
#include <gnu/libc-version.h>
#include <malloc.h>
#endif

namespace {
using namespace tiplog;
namespace tb = tiplog::bench;
std::uint64_t nanos(clockid_t clock) {
  timespec now{};
  if (::clock_gettime(clock, &now) != 0)
    throw std::runtime_error("clock_gettime failed");
  return static_cast<std::uint64_t>(now.tv_sec) * 1000000000ULL +
         static_cast<std::uint64_t>(now.tv_nsec);
}
std::uint64_t frequency() {
  std::ifstream input("/sys/devices/system/cpu/cpu2/cpufreq/scaling_cur_freq");
  std::uint64_t value{};
  input >> value;
  return value;
}
std::uint64_t usage_ns(const timeval &value) {
  return static_cast<std::uint64_t>(value.tv_sec) * 1000000000ULL +
         static_cast<std::uint64_t>(value.tv_usec) * 1000ULL;
}
double fraction(std::string_view text) {
  double value{};
  const auto parsed =
      std::from_chars(text.data(), text.data() + text.size(), value);
  if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size() ||
      !std::isfinite(value))
    throw std::invalid_argument("expected finite decimal fraction");
  return value;
}
struct Options {
  std::filesystem::path trace, requests, term_dictionary, output,
      mix{"configs/m2_payload_mix.csv"};
  std::uint64_t records{std::numeric_limits<std::uint64_t>::max()};
  std::uint64_t anchor{36000000000000ULL}, seed{20191230}, partitions{1000},
      run_length{16};
  double zipf{};
  EngineConfig config;
  bool synthetic{}, memory{}, allocator{};
  Options() {
    config.ring_bytes = std::size_t{1} << 30;
    config.max_record_bytes = 1024;
    config.minimum_record_bytes = 32;
  }
};
Options options(int argc, char **argv) {
  Options out;
  for (int i = 1; i < argc; ++i) {
    const std::string_view arg = argv[i];
    if (arg == "--synthetic") {
      out.synthetic = true;
      continue;
    }
    if (arg == "--memory") {
      out.memory = true;
      continue;
    }
    if (arg == "--allocator-replay") {
      out.allocator = true;
      continue;
    }
    if (arg == "--measure-prefill") {
      // Compatibility alias: prefill diagnostics are always emitted.
      continue;
    }
    if (arg == "--help") {
      std::cout
          << "tiplog_bench --trace PATH|--synthetic --requests TSV --output "
             "JSONL "
             "[--term-dictionary PATH] "
             "[--records N --anchor-ts N --ring-bytes N --block-entries B "
             "--index-enabled 0|1] "
             "[--seed N --partitions P --zipf S --run-length L --mix CSV] "
             "[--memory --allocator-replay --measure-prefill] "
             "[--auto-max-partitions K --auto-max-fraction F]\n"
             "Prefill is always measured; --measure-prefill is a compatibility alias.\n";
      std::exit(0);
    }
    if (i + 1 >= argc)
      throw std::invalid_argument("option requires value");
    const std::string_view value = argv[++i];
    if (arg == "--trace")
      out.trace = value;
    else if (arg == "--requests")
      out.requests = value;
    else if (arg == "--term-dictionary")
      out.term_dictionary = value;
    else if (arg == "--output")
      out.output = value;
    else if (arg == "--mix")
      out.mix = value;
    else if (arg == "--records")
      out.records = tb::number(value);
    else if (arg == "--anchor-ts")
      out.anchor = tb::number(value);
    else if (arg == "--ring-bytes")
      out.config.ring_bytes = tb::number(value);
    else if (arg == "--block-entries") {
      const auto n = tb::number(value);
      if (n > UINT32_MAX)
        throw std::invalid_argument("B exceeds u32");
      out.config.index.entries_per_block = static_cast<std::uint32_t>(n);
    } else if (arg == "--seed")
      out.seed = tb::number(value);
    else if (arg == "--partitions")
      out.partitions = tb::number(value);
    else if (arg == "--zipf")
      out.zipf = fraction(value);
    else if (arg == "--run-length")
      out.run_length = tb::number(value);
    else if (arg == "--index-enabled") {
      if (value != "0" && value != "1")
        throw std::invalid_argument("index flag");
      out.config.index_enabled = value == "1";
    } else if (arg == "--auto-max-partitions") {
      const auto n = tb::number(value);
      if (n > UINT32_MAX)
        throw std::invalid_argument("Auto K exceeds u32");
      out.config.auto_max_partitions = static_cast<std::uint32_t>(n);
    } else if (arg == "--auto-max-fraction")
      out.config.auto_max_index_fraction = fraction(value);
    else
      throw std::invalid_argument("unknown option: " + std::string(arg));
  }
  if (out.synthetic == !out.trace.empty())
    throw std::invalid_argument("choose exactly one trace or synthetic");
  if (out.synthetic && out.records == std::numeric_limits<std::uint64_t>::max())
    out.records = 1ULL << 20;
  if (out.partitions == 0 || out.partitions > 1000000 || out.run_length == 0 ||
      out.zipf < 0)
    throw std::invalid_argument("synthetic parameter range");
  if (out.config.ring_bytes < 2048 ||
      !std::has_single_bit(out.config.ring_bytes) ||
      out.config.ring_bytes > (1ULL << 31))
    throw std::invalid_argument("ring range is powers of two [2048,2GiB]");
  if (out.output.empty())
    throw std::invalid_argument("--output required");
  return out;
}
struct Request {
  std::string id, experiment, terms, mode, kernel, cache;
  std::uint64_t after{}, batch{4096}, readers{1};
};
using TermDictionary = std::map<std::string, std::string>;
TermDictionary term_dictionary(const std::filesystem::path &path) {
  TermDictionary result;
  if (path.empty())
    return result;
  std::ifstream input(path);
  if (!input)
    throw std::invalid_argument("cannot open term dictionary");
  std::string line;
  while (std::getline(input, line)) {
    const auto tab = line.find('\t');
    if (tab != 64 || line.find('\t', tab + 1) != std::string::npos ||
        !std::all_of(line.begin(), line.begin() + 64, [](char c) {
          return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
        }))
      throw std::invalid_argument("malformed term dictionary line: SHA256-id TAB terms required");
    auto id = line.substr(0, tab);
    auto terms = line.substr(tab + 1);
    tb::Sha256 hash;
    hash.update(std::as_bytes(std::span(terms)));
    if (hash.hex() != id)
      throw std::invalid_argument("term dictionary id does not match term string SHA256");
    if (!result.emplace(std::move(id), std::move(terms)).second)
      throw std::invalid_argument("duplicate term dictionary id");
  }
  if (!input.eof())
    throw std::runtime_error("cannot read term dictionary");
  return result;
}
std::vector<Request> requests(const std::filesystem::path &path,
                              const TermDictionary &dictionary) {
  if (path.empty())
    return {};
  std::ifstream input(path);
  if (!input)
    throw std::runtime_error("cannot open requests");
  std::vector<Request> result;
  std::string line;
  while (std::getline(input, line)) {
    if (line.empty() || line[0] == '#')
      continue;
    if (line == "id\texperiment\tafter_seq\tterms\tmode\tkernel\tcache\tbatch\treaders")
      continue;
    auto fields = tb::split(line, '\t');
    if (fields.size() != 9)
      throw std::invalid_argument("request TSV requires9columns");
    if (fields[3].starts_with('@')) {
      const auto found = dictionary.find(fields[3].substr(1));
      if (found != dictionary.end())
        fields[3] = found->second;
    }
    result.push_back({fields[0], fields[1], fields[3], fields[4], fields[5],
                      fields[6], tb::number(fields[2]), tb::number(fields[7]),
                      tb::number(fields[8])});
  }
  if (input.bad() || !input.eof())
    throw std::runtime_error("cannot read requests");
  return result;
}
SubscriptionSpec specification(std::string_view text) {
  SubscriptionSpec result;
  for (const auto &term : tb::split(text, ';')) {
    const auto colon = term.find(':');
    if (colon == std::string::npos)
      throw std::invalid_argument("term requires exact: or subtree:");
    const auto kind = term.substr(0, colon);
    if (kind != "exact" && kind != "subtree")
      throw std::invalid_argument("term kind");
    result.terms.push_back({kind == "exact" ? Term::Exact : Term::Subtree,
                            term.substr(colon + 1)});
  }
  return result;
}
ReplayMode replay_mode(std::string_view name) {
  if (name == "scan")
    return ReplayMode::Scan;
  if (name == "indexed")
    return ReplayMode::Indexed;
  if (name == "auto")
    return ReplayMode::Auto;
  throw std::invalid_argument("mode name");
}
MergeKernel merge_kernel(std::string_view name) {
  if (name == "stdpq")
    return MergeKernel::StdPQ;
  if (name == "binheap")
    return MergeKernel::BinHeap;
  if (name == "quad")
    return MergeKernel::Quad;
  if (name == "loser")
    return MergeKernel::Loser;
  throw std::invalid_argument("kernel name");
}
struct ScheduleItem {
  PartitionId partition;
  LogPos pos, tail;
  std::uint64_t evictions, retained;
};
struct Loaded {
  std::unique_ptr<trace::Reader> trace;
  std::unique_ptr<Engine> engine;
  std::vector<ScheduleItem> schedule;
  std::uint64_t publications{}, publish_wall{}, publish_cpu{},
      sink{tb::fnv_basis};
  std::vector<std::uint64_t> owner_counts;
  std::array<std::uint64_t, 3> event_counts{};
  std::uint64_t owner_runs{};
  int publish_cpu_start{}, publish_cpu_end{};
  std::uint64_t publish_freq_start{}, publish_freq_end{};
  std::uint64_t publish_user_ns{}, publish_system_ns{};
};
Loaded load(Options &o) {
  Loaded out;
  tb::PayloadMix sizes;
  if (o.synthetic) {
    std::ifstream input(o.mix);
    sizes = tb::read_payload_mix(input, o.config.max_record_bytes - 16);
  }
  std::vector<std::pair<std::uint32_t, std::string>> paths;
  std::set<std::string> partition_paths;
  if (o.synthetic) {
    for (std::uint64_t owner = 0; owner < o.partitions; ++owner)
      for (unsigned event = 0; event < 3; ++event)
        paths.emplace_back(static_cast<std::uint32_t>(owner * 3 + event),
                           "synth/p" + std::to_string(owner) + "/e" +
                               std::to_string(event));
  } else {
    out.trace = std::make_unique<trace::Reader>(o.trace);
    for (const auto &topic : out.trace->dictionary())
      paths.emplace_back(topic.id, topic.path);
  }
  for (const auto &[id, path] : paths) {
    (void)id;
    const auto slash = path.find('/');
    partition_paths.insert(path.substr(0, slash));
    if (slash != std::string::npos)
      partition_paths.insert(path.substr(0, path.find('/', slash + 1)));
  }
  o.config.index.blocks = index::Index::sizing_blocks(
      o.config.ring_bytes, 32, o.config.index.entries_per_block,
      partition_paths.size());
  out.engine = std::make_unique<Engine>(o.config);
  std::unordered_map<std::uint32_t, TopicId> ids;
  for (const auto &[id, path] : paths)
    ids.emplace(id, out.engine->intern(path));
  if (o.allocator)
    out.schedule.reserve(static_cast<std::size_t>(
        std::min<std::uint64_t>(o.records, 1ULL << 26)));
  auto publish = [&](TopicId topic, std::span<const std::byte> payload) {
    const auto before = out.engine->ring().stats();
    const auto seq = out.engine->publish(topic, payload);
    tb::sink_delivery(out.sink, Delivered{seq, 0, topic, payload});
    ++out.publications;
    if (o.allocator) {
      const auto &ring = out.engine->ring();
      out.schedule.push_back({out.engine->registry().get(topic).partition,
                              ring.seek_after(seq - 1), ring.tail_pos(),
                              ring.stats().data_evicted - before.data_evicted,
                              ring.head_seq() - ring.tail_seq()});
    }
  };
  // Trace validation/dictionary allocation are excluded. The publish-window
  // diagnostic includes input traversal and the identical payload sink in both
  // index-on/off arms; it is separate from replay timings.
  out.publish_cpu_start = ::sched_getcpu();
  out.publish_freq_start = frequency();
  rusage usage_before{};
  if (::getrusage(RUSAGE_SELF, &usage_before) != 0)
    throw std::runtime_error("getrusage before prefill failed");
  const auto wall = nanos(CLOCK_MONOTONIC),
             cpu = nanos(CLOCK_PROCESS_CPUTIME_ID);
  if (out.trace) {
    trace::Reader::Cursor cursor;
    trace::Record record;
    while (out.publications < o.records && out.trace->next(cursor, record)) {
      if (record.ts_ns >= o.anchor)
        break;
      publish(ids.at(record.topic_id), record.payload);
    }
  } else {
    if (o.partitions < 2)
      throw std::invalid_argument(
          "same-owner geometric runs require at least2 partitions");
    tb::Random random{o.seed};
    std::vector<double> cumulative;
    double total = 0;
    double maximum_interval = 0;
    if (o.zipf != 0) {
      for (std::uint64_t i = 0; i < o.partitions; ++i) {
        total += std::pow(static_cast<double>(i + 1), -o.zipf);
        cumulative.push_back(total);
      }
      for (auto &value : cumulative)
        value /= total;
      cumulative.back() = 1;
      double previous = 0;
      for (const auto value : cumulative) {
        maximum_interval = std::max(maximum_interval, value - previous);
        previous = value;
      }
      if (maximum_interval >= 0.5)
        throw std::invalid_argument(
            "no-self Zipf coupling requires maximum probability below0.5");
    }
    out.owner_counts.resize(static_cast<std::size_t>(o.partitions));
    std::vector<std::byte> payload(1024);
    std::uint64_t owner = 0;
    for (std::uint64_t seq = 1; seq <= o.records; ++seq) {
      const auto unit = [&random]() {
        return static_cast<double>(random.next() >> 11) * 0x1.0p-53;
      };
      if (seq == 1) {
        owner = o.zipf == 0 ? random.bounded(o.partitions)
                            : static_cast<std::uint64_t>(
                                  std::upper_bound(cumulative.begin(),
                                                   cumulative.end(), unit()) -
                                  cumulative.begin());
        ++out.owner_runs;
      } else if (random.bounded(o.run_length) == 0) {
        const auto old = owner;
        if (o.zipf == 0) {
          owner = random.bounded(o.partitions - 1);
          if (owner >= old)
            ++owner;
        } else {
          const auto left =
              old == 0 ? 0 : cumulative[static_cast<std::size_t>(old - 1)];
          const auto right = cumulative[static_cast<std::size_t>(old)];
          const auto point = std::min(std::nextafter(right, left),
                                      left + unit() * (right - left));
          const auto shift =
              maximum_interval + unit() * (1 - 2 * maximum_interval);
          auto rotated = point + shift;
          if (rotated >= 1)
            rotated -= 1;
          owner = static_cast<std::uint64_t>(
              std::upper_bound(cumulative.begin(), cumulative.end(), rotated) -
              cumulative.begin());
        }
        if (owner == old || owner >= o.partitions)
          throw std::logic_error("no-self owner coupling endpoint violation");
        ++out.owner_runs;
      }
      const auto event_draw = random.bounded(100);
      const auto event = event_draw < 1 ? 0ULL : event_draw < 10 ? 1ULL : 2ULL;
      ++out.owner_counts[static_cast<std::size_t>(owner)];
      ++out.event_counts[static_cast<std::size_t>(event)];
      const auto length_draw = random.bounded(sizes.back().second);
      const auto chosen = static_cast<std::size_t>(
          std::upper_bound(sizes.begin(), sizes.end(), length_draw,
                           [](auto draw, const auto &row) { return draw < row.second; }) -
          sizes.begin());
      const auto length = sizes[chosen].first;
      if (length > payload.size())
        throw std::length_error("synthetic payload size");
      for (std::size_t i = 0; i < length; ++i)
        payload[i] = static_cast<std::byte>((o.seed + seq * 17 + i * 31) & 255);
      publish(ids.at(static_cast<std::uint32_t>(owner * 3 + event)),
              std::span(payload).first(length));
    }
  }
  out.publish_cpu = nanos(CLOCK_PROCESS_CPUTIME_ID) - cpu;
  out.publish_wall = nanos(CLOCK_MONOTONIC) - wall;
  rusage usage_after{};
  if (::getrusage(RUSAGE_SELF, &usage_after) != 0)
    throw std::runtime_error("getrusage after prefill failed");
  out.publish_user_ns =
      usage_ns(usage_after.ru_utime) - usage_ns(usage_before.ru_utime);
  out.publish_system_ns =
      usage_ns(usage_after.ru_stime) - usage_ns(usage_before.ru_stime);
  out.publish_cpu_end = ::sched_getcpu();
  out.publish_freq_end = frequency();
  return out;
}
struct Result {
  std::uint64_t sink{tb::fnv_basis}, count{}, bytes{}, upper_seq{}, upper_pos{};
  ReplayWork work{};
  Status status{Status::Done};
  ReplayMode effective{ReplayMode::Scan};
  std::optional<ResumeCheckpoint> checkpoint;
  std::optional<ReplayError> error;
  std::string seq_hash, payload_hash;
  std::uint64_t wall_ns{}, cpu_ns{};
  std::uint64_t user_ns{}, system_ns{};
  std::uint64_t selected_partitions{}, estimated_entries{}, range_records{};
  bool wide{};
};
void add(ReplayWork &a, const ReplayWork &b) {
  a.bytes_inspected += b.bytes_inspected;
  a.entries_visited += b.entries_visited;
  a.records_fetched += b.records_fetched;
  a.delivered += b.delivered;
  a.pads_inspected += b.pads_inspected;
  a.seek_data_examined += b.seek_data_examined;
  a.seek_pads_examined += b.seek_pads_examined;
  a.index_seeks += b.index_seeks;
}
Result drain(Engine &engine, const subs::CompiledSubscription &sub,
             const Request &request, bool sha,
             std::vector<Delivered> &records) {
  Result result;
  tb::Sha256 sequences, payloads;
  const auto mode = replay_mode(request.mode);
  const auto kernel = merge_kernel(request.kernel);
  for (std::uint64_t reader = 0; reader < request.readers; ++reader) {
    rusage usage_before{};
    if (::getrusage(RUSAGE_SELF, &usage_before) != 0)
      throw std::runtime_error("getrusage before replay failed");
    const auto wall = nanos(CLOCK_MONOTONIC),
               cpu = nanos(CLOCK_PROCESS_CPUTIME_ID);
    auto replay = engine.open_replay(sub, request.after, mode, kernel);
    for (;;) {
      result.status =
          replay.next_batch(static_cast<std::size_t>(request.batch), records);
      for (const auto &record : records) {
        tb::sink_delivery(result.sink, record);
        ++result.count;
        result.bytes += record.payload.size();
        if (sha) {
          sequences.little_u64(record.seq);
          payloads.update(record.payload);
        }
      }
      if (result.status != Status::More)
        break;
    }
    result.cpu_ns += nanos(CLOCK_PROCESS_CPUTIME_ID) - cpu;
    result.wall_ns += nanos(CLOCK_MONOTONIC) - wall;
    rusage usage_after{};
    if (::getrusage(RUSAGE_SELF, &usage_after) != 0)
      throw std::runtime_error("getrusage after replay failed");
    result.user_ns +=
        usage_ns(usage_after.ru_utime) - usage_ns(usage_before.ru_utime);
    result.system_ns +=
        usage_ns(usage_after.ru_stime) - usage_ns(usage_before.ru_stime);
    result.effective = replay.effective_mode();
    result.upper_seq = replay.upper_seq();
    result.upper_pos = replay.upper_pos();
    result.error = replay.error();
    result.checkpoint = replay.checkpoint();
    add(result.work, replay.work());
  }
  if (sha) {
    result.seq_hash = sequences.hex();
    result.payload_hash = payloads.hex();
  }
  return result;
}
std::string outcome(const Result &r) {
  if (!r.error)
    return "ok";
  return r.error->kind == ReplayError::HistoryExpired ? "history_expired"
                                                      : "fell_behind";
}
void write_result(std::ostream &out, const Request &r, const Result &result,
                  std::uint64_t wall, std::uint64_t cpu, int cpu_start,
                  int cpu_end, std::uint64_t freq_start,
                  std::uint64_t freq_end, const topics::Registry &registry) {
  out << "{\"kind\":\"replay\",\"id\":" << tb::json(r.id)
      << ",\"experiment\":" << tb::json(r.experiment)
      << ",\"status\":" << tb::json(outcome(result))
      << ",\"requested_mode\":" << tb::json(r.mode) << ",\"effective_mode\":"
      << tb::json(result.effective == ReplayMode::Scan ? "scan" : "indexed")
      << ",\"kernel\":" << tb::json(r.kernel)
      << ",\"cache\":" << tb::json(r.cache) << ",\"after_seq\":" << r.after
      << ",\"readers\":" << r.readers << ",\"wall_ns\":" << wall
      << ",\"cpu_ns\":" << cpu << ",\"cpu_start\":" << cpu_start
      << ",\"user_ns\":" << result.user_ns
      << ",\"system_ns\":" << result.system_ns << ",\"cpu_end\":" << cpu_end
      << ",\"freq_start_khz\":" << freq_start
      << ",\"freq_end_khz\":" << freq_end << ",\"out_count\":" << result.count
      << ",\"payload_bytes\":" << result.bytes << ",\"sink64\":" << result.sink
      << ",\"seq_sha256\":" << tb::json(result.seq_hash)
      << ",\"payload_sha256\":" << tb::json(result.payload_hash)
      << ",\"upper_seq\":" << result.upper_seq
      << ",\"upper_pos\":" << result.upper_pos << ",\"checkpoint\":";
  if (result.checkpoint)
    out << "{\"after_seq\":" << result.checkpoint->after_seq
        << ",\"next_pos\":" << result.checkpoint->next_pos << '}';
  else
    out << "null";
  out << ",\"error\":";
  if (result.error)
    out << "{\"kind\":" << tb::json(outcome(result))
        << ",\"requested_after\":" << result.error->requested_after
        << ",\"last_delivered\":" << result.error->last_delivered
        << ",\"oldest_retained\":" << result.error->oldest_retained << '}';
  else
    out << "null";
  const auto &w = result.work;
  out << ",\"work\":{\"bytes_inspected\":" << w.bytes_inspected
      << ",\"entries_visited\":" << w.entries_visited
      << ",\"records_fetched\":" << w.records_fetched
      << ",\"delivered\":" << w.delivered
      << ",\"pads_inspected\":" << w.pads_inspected
      << ",\"seek_data_examined\":" << w.seek_data_examined
      << ",\"seek_pads_examined\":" << w.seek_pads_examined
      << ",\"index_seeks\":" << w.index_seeks
      << "},\"selected_partitions\":" << result.selected_partitions
      << ",\"estimated_entries\":" << result.estimated_entries
      << ",\"range_records\":" << result.range_records
      << ",\"estimated_index_fraction\":";
  if (result.range_records != 0 && !result.wide)
    out << static_cast<double>(result.estimated_entries) /
               static_cast<double>(result.range_records);
  else
    out << "null";
  out << ",\"wide\":" << (result.wide ? "true" : "false")
      << ",\"registry_topics\":" << registry.topic_count()
      << ",\"registry_partitions\":" << registry.partition_count()
      << ",\"subscription_observers\":" << registry.observer_count()
      << ",\"counters\":null}\n";
}
void memory(std::ostream &out, const Loaded &loaded, const Options &options) {
  const auto &engine = *loaded.engine;
  const auto &ring = engine.ring();
  out << "{\"kind\":\"memory\",\"status\":\"ok\",\"ring_bytes\":"
      << options.config.ring_bytes
      << ",\"block_entries\":" << options.config.index.entries_per_block
      << ",\"blocks\":" << options.config.index.blocks
      << ",\"publications\":" << loaded.publications
      << ",\"retained_records\":" << ring.head_seq() - ring.tail_seq()
      << ",\"head_pos\":" << ring.head_pos()
      << ",\"tail_pos\":" << ring.tail_pos()
      << ",\"head_seq\":" << ring.head_seq()
      << ",\"tail_seq\":" << ring.tail_seq()
      << ",\"registry_topics\":" << engine.registry().topic_count()
      << ",\"registry_partitions\":" << engine.registry().partition_count()
      << ",\"checkpoint_bytes\":" << ring.checkpoint_slots() * sizeof(LogPos);
  if (const auto *index = engine.index()) {
    const auto stats = index->stats();
    const auto recount = index->recount(ring.tail_pos());
    if (stats.gauges != recount.gauges || stats.memory != recount.memory)
      throw std::logic_error("memory recount mismatch");
    index->check_invariants(ring.tail_pos());
    const auto &g = stats.gauges;
    const auto &m = stats.memory;
    out << ",\"recount_equal\":true,\"allocated_high_water\":"
        << stats.allocated_high_water << ",\"gauges\":{"
        << "\"allocated_blocks\":" << g.allocated_blocks
        << ",\"free_blocks\":" << g.free_blocks
        << ",\"sealed_blocks\":" << g.sealed_blocks
        << ",\"allocated_entries\":" << g.allocated_entries
        << ",\"live_entries\":" << g.live_entries
        << ",\"expired_allocated_entries\":" << g.expired_allocated_entries
        << ",\"open_slack\":" << g.open_slack
        << ",\"sealed_partial_slack\":" << g.sealed_partial_slack
        << ",\"free_block_slots\":" << g.free_block_slots
        << "},\"memory\":{\"metadata_reserved_bytes\":"
        << m.metadata_reserved_bytes
        << ",\"entries_reserved_bytes\":" << m.entries_reserved_bytes
        << ",\"sealed_flags_reserved_bytes\":" << m.sealed_flags_reserved_bytes
        << ",\"heap_used_bytes\":" << m.heap_used_bytes
        << ",\"heap_reserved_bytes\":" << m.heap_reserved_bytes
        << ",\"partition_state_used_bytes\":" << m.partition_state_used_bytes
        << ",\"partition_state_reserved_bytes\":"
        << m.partition_state_reserved_bytes
        << ",\"partition_list_used_bytes\":" << m.partition_list_used_bytes
        << ",\"partition_list_reserved_bytes\":"
        << m.partition_list_reserved_bytes
        << ",\"control_bytes\":" << m.control_bytes
        << ",\"reserved_bytes\":" << m.reserved_bytes
        << ",\"allocator_overhead_measured\":false}";
  } else
    out << ",\"recount_equal\":null,\"memory\":null";
  out << "}\n";
}
void allocator(std::ostream &out, Loaded &loaded, const Options &o) {
#if defined(__GLIBC__) && !defined(__SANITIZE_ADDRESS__)
#if defined(__has_feature)
#if __has_feature(address_sanitizer)
  throw std::runtime_error("allocator boundary unavailable under ASan");
#endif
#endif
  if (const auto *preload = std::getenv("LD_PRELOAD"); preload && *preload)
    throw std::invalid_argument("preloaded allocator unsupported");
  const auto expected = loaded.engine->index()->stats();
  const auto partition_count = loaded.engine->registry().partition_count();
  loaded.engine.reset();
  // Schedule, trace map and output objects preexist this Index-only boundary.
  const auto before = ::mallinfo2();
  auto index = std::make_unique<index::Index>(o.config.index);
  for (const auto &entry : loaded.schedule) {
    auto prep = index->prepare_append(entry.partition, entry.pos, entry.tail,
                                      partition_count, entry.evictions);
    if (!std::holds_alternative<index::PreparedAppend>(prep))
      throw std::logic_error("allocator replay pressure");
    index->commit(std::move(std::get<index::PreparedAppend>(prep)),
                  entry.retained);
  }
  const auto after = ::mallinfo2();
  const auto actual = index->stats();
  if (actual != expected)
    throw std::logic_error("actual-schedule allocator index differs");
  const auto charged =
      static_cast<std::int64_t>(after.uordblks + after.hblkhd) -
      static_cast<std::int64_t>(before.uordblks + before.hblkhd);
  out << "{\"kind\":\"allocator\",\"status\":\"ok\",\"method\":\"glibc-"
         "mallinfo2-real-schedule-replay\",\"glibc\":"
      << tb::json(gnu_get_libc_version())
      << ",\"schedule_rows\":" << loaded.schedule.size()
      << ",\"stats_equal\":true,\"requested_reserved_bytes\":"
      << actual.memory.reserved_bytes << ",\"charged_delta_bytes\":" << charged
      << ",\"observed_allocator_overhead_bytes\":"
      << charged - static_cast<std::int64_t>(actual.memory.reserved_bytes)
      << ",\"before\":{\"uordblks\":" << before.uordblks
      << ",\"hblkhd\":" << before.hblkhd << ",\"arena\":" << before.arena
      << "},\"after\":{\"uordblks\":" << after.uordblks
      << ",\"hblkhd\":" << after.hblkhd << ",\"arena\":" << after.arena
      << "},\"scope\":\"Index allocations only; same actual real-trace "
         "positional and eviction schedule; Ring and Registry excluded\","
         "\"limitations\":\"Signed allocator delta includes rounding, reuse "
         "and retained freed chunks; not RSS or per-object headers\"}\n";
#else
  (void)out;
  (void)loaded;
  (void)o;
  throw std::runtime_error("allocator diagnostic requires unsanitized glibc");
#endif
}
} // namespace

int main(int argc, char **argv) {
  try {
    auto o = options(argc, argv);
    for (const auto& source : {o.synthetic ? o.mix : o.trace, o.requests, o.term_dictionary})
      tiplog::cli::require_distinct_files(source, o.output);
    const auto todo = requests(o.requests, term_dictionary(o.term_dictionary));
    std::ofstream out(o.output, std::ios::app);
    if (!out)
      throw std::runtime_error("cannot open output");
    out << std::setprecision(std::numeric_limits<double>::max_digits10);
    auto loaded = load(o);
    // Intern every requested root and settle all observer filters before the
    // first warm-up or measurement. Sorted unique term strings make zero-volume
    // topic IDs, hook order and registry gauges independent of shuffled arms.
    std::map<std::string, subs::CompiledSubscription> compiled;
    std::map<std::string, std::string> compilation_errors;
    for (const auto &request : todo)
      compiled.try_emplace(request.terms);
    for (auto &[terms, subscription] : compiled) {
      try {
        if (terms.starts_with('@'))
          throw std::invalid_argument("unknown or malformed term alias: " + terms);
        subscription = loaded.engine->compile(specification(terms));
      } catch (const std::invalid_argument &error) {
        compilation_errors.emplace(terms, error.what());
      } catch (const topics::RepresentationLimit &error) {
        compilation_errors.emplace(terms, error.what());
      }
    }
    const auto &registry = loaded.engine->registry();
    tb::Sha256 registry_hash;
    for (const auto &topic : registry.all_topics()) {
      registry_hash.little_u64(topic.id);
      registry_hash.little_u64(topic.path.size());
      registry_hash.update(std::as_bytes(std::span(topic.path)));
    }
    out << "{\"kind\":\"prefill\",\"status\":\"ok\",\"publications\":"
        << loaded.publications
        << ",\"index_enabled\":" << (o.config.index_enabled ? "true" : "false")
        << ",\"ring_bytes\":" << o.config.ring_bytes
        << ",\"block_entries\":" << o.config.index.entries_per_block
        << ",\"publish_wall_ns\":" << loaded.publish_wall
        << ",\"publish_cpu_ns\":" << loaded.publish_cpu
        << ",\"user_ns\":" << loaded.publish_user_ns
        << ",\"system_ns\":" << loaded.publish_system_ns
        << ",\"publish_sink64\":" << loaded.sink
        << ",\"cpu_start\":" << loaded.publish_cpu_start
        << ",\"cpu_end\":" << loaded.publish_cpu_end
        << ",\"freq_start_khz\":" << loaded.publish_freq_start
        << ",\"freq_end_khz\":" << loaded.publish_freq_end
        << ",\"head_seq\":" << loaded.engine->stats().head_seq
        << ",\"tail_seq\":" << loaded.engine->stats().tail_seq
        << ",\"head_pos\":" << loaded.engine->stats().head_pos
        << ",\"tail_pos\":" << loaded.engine->stats().tail_pos
        << ",\"capacity_and_pressure_data_evicted\":"
        << loaded.engine->ring().stats().data_evicted
        << ",\"pressure_data_evicted\":"
        << loaded.engine->ring().stats().pressure_data_evicted
        << ",\"pad_bytes_appended\":"
        << loaded.engine->ring().stats().pad_bytes_appended
        << ",\"registry_topics\":" << registry.topic_count()
        << ",\"registry_partitions\":" << registry.partition_count()
        << ",\"subscription_observers\":" << registry.observer_count()
        << ",\"registry_identity_sha256\":" << tb::json(registry_hash.hex())
        << ",\"registry_identity_scope\":\"after sorted unique request compilation; "
           "topic-id u64LE, path-byte-length u64LE, path UTF-8 in registry order\""
        << ",\"subscription_compilation_errors\":" << compilation_errors.size()
        << ",\"timing_scope\":\"trace traversal or synthetic generation plus "
           "publish and identical sequence/payload sink; excludes trace "
           "validation and dictionary setup\","
           "\"work_counter_scope\":\"replay loop decoded spans and DATA "
           "fetches; popped postings; ring seek header counts separate; "
           "excludes uninstrumented index seek comparisons\"";
    if (o.synthetic) {
      auto sorted_counts = loaded.owner_counts;
      std::sort(sorted_counts.begin(), sorted_counts.end(), std::greater<>());
      tb::Sha256 counts_hash;
      for (const auto count : loaded.owner_counts)
        counts_hash.little_u64(count);
      std::uint64_t top10 = 0;
      for (std::size_t i = 0;
           i < std::min<std::size_t>(10, sorted_counts.size()); ++i)
        top10 += sorted_counts[i];
      out << ",\"observed_owner_runs\":" << loaded.owner_runs
          << ",\"observed_run_mean\":";
      if (loaded.owner_runs)
        out << static_cast<double>(loaded.publications) /
                   static_cast<double>(loaded.owner_runs);
      else
        out << "null";
      out << ",\"owner_top1_count\":" << sorted_counts.front()
          << ",\"owner_top10_count\":" << top10
          << ",\"owner_counts_sha256\":" << tb::json(counts_hash.hex())
          << ",\"event_counts\":[" << loaded.event_counts[0] << ','
          << loaded.event_counts[1] << ',' << loaded.event_counts[2] << "]"
          << ",\"owner_counts\":[";
      for (std::size_t i = 0; i < loaded.owner_counts.size(); ++i) {
        if (i)
          out << ',';
        out << loaded.owner_counts[i];
      }
      out << ']';
    }
    out << "}\n";
    std::vector<std::byte> scratch(64ULL << 20);
    std::uint64_t scratch_sink = 0;
    // Registry and compiled plans are now immutable. Every measured arm still
    // constructs a new captured replay; no request-loop compilation occurs.
    bool run_failed = false;
    auto write_failure = [&](const Request &r, std::string_view status,
                             const std::exception &error) {
      out << "{\"kind\":\"replay\",\"id\":" << tb::json(r.id)
          << ",\"experiment\":" << tb::json(r.experiment)
          << ",\"status\":" << tb::json(status) << ",\"reason\":"
          << tb::json(error.what())
          << ",\"registry_topics\":" << registry.topic_count()
          << ",\"registry_partitions\":" << registry.partition_count()
          << ",\"subscription_observers\":" << registry.observer_count()
          << "}\n";
    };
    for (const auto &r : todo) {
      bool valid = true;
      try {
        if (r.batch == 0 || r.batch > (1ULL << 20) || r.readers == 0 ||
            r.readers > 100000)
          throw std::invalid_argument("batch/readers range");
        if (const auto error = compilation_errors.find(r.terms);
            error != compilation_errors.end())
          throw std::invalid_argument(error->second);
        const auto mode = replay_mode(r.mode);
        const auto kernel = merge_kernel(r.kernel);
        if (r.cache != "repeat-warm" && r.cache != "scratch-thrashed")
          throw std::invalid_argument("cache treatment name");
        // Mode eligibility also depends on the compiled plan and index. Probe
        // construction before warm-up/cache treatment, outside timed replay.
        // Known representation/configuration rejections stay reject arms;
        // unexpected failures still escape this narrowly typed validation.
        (void)loaded.engine->open_replay(compiled.at(r.terms), r.after, mode, kernel);
      } catch (const std::invalid_argument &error) {
        write_failure(r, "invalid_config", error);
        valid = false;
      } catch (const index::RepresentationLimit &error) {
        write_failure(r, "invalid_config", error);
        valid = false;
      }
      try {
        if (valid) {
          const auto &sub = compiled.at(r.terms);
          std::vector<Delivered> records;
          records.reserve(static_cast<std::size_t>(r.batch));
          if (r.cache == "repeat-warm") {
            const auto warm = drain(*loaded.engine, sub, r, false, records);
            scratch_sink ^= warm.sink;
          } else if (r.cache == "scratch-thrashed") {
            for (std::size_t i = 0; i < scratch.size(); i += 64) {
              scratch[i] = static_cast<std::byte>((i / 64 + scratch_sink) & 255);
              scratch_sink += std::to_integer<unsigned>(scratch[i]);
            }
            asm volatile(""
                         :
                         : "r"(scratch.data()), "r"(scratch_sink)
                         : "memory");
          } else
            throw std::invalid_argument("cache treatment name");
          const auto freq_start = frequency();
          const auto cpu_start = ::sched_getcpu();
          auto actual = drain(*loaded.engine, sub, r, false, records);
          const auto cpu_end = ::sched_getcpu();
          const auto freq_end = frequency();
          auto digested = drain(*loaded.engine, sub, r, true, records);
          tb::verify_replay(actual, digested);
          actual.seq_hash = std::move(digested.seq_hash);
          actual.payload_hash = std::move(digested.payload_hash);
          actual.wide = sub.wide();
          actual.selected_partitions = sub.filters().size();
          const auto &ring = loaded.engine->ring();
          actual.range_records =
              actual.upper_seq > r.after ? actual.upper_seq - r.after : 0;
          if (!actual.wide && loaded.engine->index() &&
              r.after >= ring.tail_seq() - 1 && r.after < ring.head_seq() - 1) {
            const auto lower = ring.seek_after(r.after);
            for (const auto &filter : sub.filters())
              actual.estimated_entries += loaded.engine->index()->estimate_count(
                  filter.partition, lower, ring.head_pos());
          }
          write_result(out, r, actual, actual.wall_ns, actual.cpu_ns, cpu_start,
                       cpu_end, freq_start, freq_end, registry);
        }
      } catch (const std::exception &error) {
        write_failure(r, tb::execution_failure_status(error), error);
        run_failed = true;
      }
      out.flush();
      if (!out)
        throw std::runtime_error("failed writing result");
    }
    if (o.memory)
      memory(out, loaded, o);
    if (o.allocator) {
      if (!o.config.index_enabled)
        throw std::invalid_argument("allocator replay requires index");
      allocator(out, loaded, o);
    }
    out.flush();
    if (!out) throw std::runtime_error("failed writing final result");
    out.close();
    if (!out) throw std::runtime_error("failed closing result output");
    return run_failed ? 1 : 0;
  } catch (const std::exception &error) {
    std::cerr << "tiplog_bench: " << error.what() << '\n';
    return 1;
  }
}
