#include "tiplog/engine/engine.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <charconv>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <numeric>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <sys/resource.h>
#include <sys/utsname.h>
#include <thread>
#include <time.h>
#include <utility>
#include <vector>

namespace {
using namespace tiplog;
constexpr std::uint64_t fixture_cap = 128ULL << 20;
constexpr std::uint64_t max_records = 2000000;
constexpr std::uint32_t block_entries = 1024;

std::uint64_t ns(clockid_t clock = CLOCK_MONOTONIC) {
  timespec value{};
  if (::clock_gettime(clock, &value) != 0)
    throw std::runtime_error("clock_gettime failed");
  return static_cast<std::uint64_t>(value.tv_sec) * 1000000000ULL +
         static_cast<std::uint64_t>(value.tv_nsec);
}
std::uint64_t number(std::string_view value) {
  std::uint64_t result{};
  const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
  if (value.empty() || parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size())
    throw std::invalid_argument("expected unsigned integer: " + std::string(value));
  return result;
}
std::string quoted(std::string_view value) {
  std::ostringstream out;
  out << '"';
  for (const char raw : value) {
    const auto ch = static_cast<unsigned char>(raw);
    if (ch == '"' || ch == '\\') out << '\\' << static_cast<char>(ch);
    else if (ch < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<unsigned>(ch) << std::dec;
    else out << static_cast<char>(ch);
  }
  out << '"';
  return out.str();
}
std::vector<std::string> split(std::string_view text) {
  std::vector<std::string> result;
  for (std::size_t start = 0;;) {
    const auto end = text.find(',', start);
    const auto item = text.substr(start, end == std::string_view::npos ? end : end - start);
    if (item.empty() || std::find(result.begin(), result.end(), item) != result.end())
      throw std::invalid_argument("empty or duplicate list entry");
    result.emplace_back(item);
    if (end == std::string_view::npos) return result;
    start = end + 1;
  }
}
bool one_of(std::string_view value, std::initializer_list<std::string_view> allowed) {
  return std::find(allowed.begin(), allowed.end(), value) != allowed.end();
}
struct Options {
  std::uint64_t records{10000}, seed{20261026}, outputs{1}, reps{3};
  std::vector<std::string> cases{"no-match", "late-match", "sparse", "dense"};
  std::vector<std::string> shapes{"small"}, partitions{"1"}, candidate_every{"1"};
  std::vector<std::string> modes{"scan", "indexed", "auto"}, kernels{"stdpq"};
  std::vector<std::string> budgets{"legacy", "unlimited", "1", "8", "32", "128", "512", "2048"};
  std::vector<std::string> schedules{"round-robin"};
  std::filesystem::path output;
};
Options parse(int argc, char **argv) {
  Options out;
  for (int i = 1; i < argc; ++i) {
    const std::string_view arg = argv[i];
    if (arg == "--help") {
      std::cout << "tiplog_poll_bench --output results/f01/NEW.jsonl "
          "[--records N --seed N --max-outputs N --reps N] "
          "[--cases no-match,late-match,sparse,dense] "
          "[--shapes small,fixed,variable,wrapped-variable] "
          "[--partitions 1,4,64,256 --modes scan,indexed,auto] "
          "[--candidate-every 1,4,16] "
          "[--kernels stdpq,binheap,quad,loser] "
          "[--budgets legacy,unlimited,1,8,32,128,512,2048] "
          "[--schedules round-robin,immediate-redrain]\n"
          "Static Replay study. Inspections exclude setup; all public poll time is measured.\n"
          "Output must be a new file under results/f01 or build/f01; no files are overwritten.\n";
      std::exit(0);
    }
    if (i + 1 == argc) throw std::invalid_argument("option needs a value");
    const std::string_view value = argv[++i];
    if (arg == "--records") out.records = number(value);
    else if (arg == "--seed") out.seed = number(value);
    else if (arg == "--max-outputs") out.outputs = number(value);
    else if (arg == "--reps") out.reps = number(value);
    else if (arg == "--cases") out.cases = split(value);
    else if (arg == "--shapes") out.shapes = split(value);
    else if (arg == "--partitions") out.partitions = split(value);
    else if (arg == "--candidate-every") out.candidate_every = split(value);
    else if (arg == "--modes") out.modes = split(value);
    else if (arg == "--kernels") out.kernels = split(value);
    else if (arg == "--budgets") out.budgets = split(value);
    else if (arg == "--schedules") out.schedules = split(value);
    else if (arg == "--output") out.output = value;
    else throw std::invalid_argument("unknown option: " + std::string(arg));
  }
  if (out.records == 0 || out.records > max_records || out.outputs == 0 ||
      out.outputs > max_records || out.reps == 0 || out.reps > 100 || out.output.empty())
    throw std::invalid_argument("records/output/repetition range or output path invalid");
  for (const auto &value : out.cases)
    if (!one_of(value, {"no-match", "late-match", "sparse", "dense"})) throw std::invalid_argument("unknown case");
  for (const auto &value : out.shapes)
    if (!one_of(value, {"small", "fixed", "variable", "wrapped-variable"})) throw std::invalid_argument("unknown shape");
  for (const auto &value : out.partitions)
    if (number(value) == 0 || number(value) > merge::max_cursors) throw std::invalid_argument("K must be in [1,65535], subject to the fixture cap");
  for (const auto &value : out.candidate_every)
    if (number(value) == 0 || number(value) > 1024) throw std::invalid_argument("candidate-every must be in [1,1024]");
  for (const auto &value : out.modes)
    if (!one_of(value, {"scan", "indexed", "auto"})) throw std::invalid_argument("unknown mode");
  for (const auto &value : out.kernels)
    if (!one_of(value, {"stdpq", "binheap", "quad", "loser"})) throw std::invalid_argument("unknown kernel");
  for (const auto &value : out.budgets)
    if (!one_of(value, {"legacy", "unlimited"}) && number(value) == 0) throw std::invalid_argument("benchmark budgets must be positive");
  for (const auto &value : out.schedules)
    if (!one_of(value, {"round-robin", "immediate-redrain"})) throw std::invalid_argument("unknown schedule");
  const auto root = std::filesystem::current_path();
  const auto target = std::filesystem::weakly_canonical(out.output);
  auto under = [&](const std::filesystem::path &base) {
    const auto relative = target.lexically_relative(std::filesystem::weakly_canonical(root / base));
    return !relative.empty() && *relative.begin() != ".." && relative != ".";
  };
  if (!under("results/f01") && !under("build/f01"))
    throw std::invalid_argument("output must resolve beneath results/f01 or build/f01 from the project root");
  out.output = target;
  return out;
}
class JsonLines {
public:
  explicit JsonLines(const std::filesystem::path &path) {
    std::filesystem::create_directories(path.parent_path());
    file_ = std::fopen(path.c_str(), "wx");
    if (!file_) throw std::runtime_error("cannot create new output file (existing files are refused)");
  }
  ~JsonLines() { if (file_) std::fclose(file_); }
  void line(const std::string &value) {
    if (std::fwrite(value.data(), 1, value.size(), file_) != value.size() ||
        std::fputc('\n', file_) == EOF || std::fflush(file_) != 0)
      throw std::runtime_error("output write/flush failed");
  }
  void close() {
    auto *closing = std::exchange(file_, nullptr);
    if (std::fclose(closing) != 0) throw std::runtime_error("output close failed");
  }
private:
  std::FILE *file_{};
};
struct Digest {
  std::uint64_t outputs{}, hash{14695981039346656037ULL};
  void byte(std::uint8_t value) { hash = (hash ^ value) * 1099511628211ULL; }
  void integer(std::uint64_t value) {
    for (unsigned i = 0; i < 8; ++i) byte(static_cast<std::uint8_t>(value >> (8U * i)));
  }
  void add(Seq seq, LogPos pos, TopicId topic, std::span<const std::byte> payload) {
    ++outputs;
    integer(seq); integer(pos); integer(topic); integer(payload.size());
    for (const auto value : payload) byte(std::to_integer<std::uint8_t>(value));
  }
  bool operator==(const Digest &) const = default;
};
std::string digest_json(const Digest &value) {
  std::ostringstream out;
  out << "{\"outputs\":" << value.outputs << ",\"fnv1a64\":\"" << std::hex
      << std::setw(16) << std::setfill('0') << value.hash << "\"}";
  return out.str();
}
std::size_t payload_size(std::string_view shape, std::uint64_t ordinal) {
  if (shape == "small") return 0;
  if (shape == "fixed") return 64;
  constexpr std::array<std::size_t, 6> sizes{0, 1, 17, 65, 129, 257};
  return sizes[ordinal % sizes.size()];
}
std::size_t span_size(std::string_view shape, std::uint64_t ordinal) {
  return (16 + payload_size(shape, ordinal) + 7) & ~std::size_t{7};
}
bool matches(std::string_view name, std::uint64_t ordinal, std::uint64_t count, std::uint64_t candidate_ordinal) {
  return name == "dense" || (name == "late-match" && ordinal + 1 == count) ||
         (name == "sparse" && candidate_ordinal % 128 == 127);
}
void make_payload(std::span<std::byte> payload, std::uint64_t seed, std::uint64_t ordinal) {
  std::uint64_t state = seed ^ (ordinal * 0x9e3779b97f4a7c15ULL);
  for (auto &value : payload) {
    state ^= state >> 12; state ^= state << 25; state ^= state >> 27;
    value = static_cast<std::byte>((state * 2685821657736338717ULL) >> 56);
  }
}
struct Fixture {
  std::unique_ptr<Engine> engine;
  subs::CompiledSubscription subscription;
  Digest oracle;
  Seq after{}, upper{};
  std::uint64_t build_ns{}, reserved_bytes{}, index_reserved_bytes{}, ring_checkpoint_bytes{}, conservative_topics_bytes{};
  std::uint64_t selected_partitions{}, candidate_records{}, data_bytes{}, pads_in_range{}, priming_records{};
};
Fixture fixture(const Options &o, const std::string &name, const std::string &shape, std::uint64_t k, std::uint64_t candidate_every) {
  const auto start = ns();
  Fixture f;
  for (std::uint64_t i = 0; i < o.records; ++i) f.data_bytes += span_size(shape, i);
  const auto ring_bytes = std::bit_ceil(std::max<std::uint64_t>(4096, f.data_bytes + 560));
  f.conservative_topics_bytes = (k + 5) * 4096;
  if (ring_bytes > fixture_cap) throw std::length_error("fixture ring exceeds 128MiB cap");
  EngineConfig c;
  c.ring_bytes = ring_bytes;
  c.max_record_bytes = 512;
  c.index.entries_per_block = block_entries;
  c.index.blocks = index::Index::sizing_blocks(ring_bytes, 16, block_entries, k + 5);
  c.pool_policy = PoolPolicy::RejectPublish;
  f.ring_checkpoint_bytes = ((ring_bytes / 16 >> c.ckpt_log2) + 2) * sizeof(LogPos);
  const auto estimated_index = static_cast<std::uint64_t>(c.index.blocks) *
      (sizeof(index::BlockMeta) + 4 * block_entries + 1 + 16) + (k + 5) * 128;
  if (ring_bytes + f.ring_checkpoint_bytes + estimated_index + f.conservative_topics_bytes > fixture_cap)
    throw std::length_error("fixture ring/index/topic estimate exceeds 128MiB cap");
  f.engine = std::make_unique<Engine>(c);
  std::vector<TopicId> hit, miss;
  SubscriptionSpec spec;
  for (std::uint64_t i = 0; i < k; ++i) {
    const auto base = "bench/p" + std::to_string(i);
    hit.push_back(f.engine->intern(base + "/hit"));
    miss.push_back(f.engine->intern(base + "/miss"));
    spec.terms.push_back({Term::Exact, base + "/hit"});
  }
  f.subscription = f.engine->compile(spec);
  f.selected_partitions = f.subscription.filters().size();
  const auto filler = f.engine->intern("priming/filler");
  const auto background = f.engine->intern("background/unselected");
  if (shape == "wrapped-variable") {
    // Place the wrap inside the captured target range. Priming is excluded from
    // the oracle and replay; subsequent publication evicts only priming data.
    const auto target = (ring_bytes - f.data_bytes / 2) & ~std::uint64_t{7};
    std::array<std::byte, 264> payload{};
    while (f.engine->ring().head_pos() + 16 <= target) {
      const auto available = target - f.engine->ring().head_pos();
      const auto bytes = std::min<std::uint64_t>(280, available);
      const auto aligned = bytes & ~std::uint64_t{7};
      const auto length = aligned >= 16 ? aligned - 16 : 0;
      f.engine->publish(filler, std::span(payload).first(static_cast<std::size_t>(length)));
      ++f.priming_records;
    }
  }
  f.after = f.engine->ring().head_seq() - 1;
  std::array<std::byte, 257> payload{};
  for (std::uint64_t i = 0; i < o.records; ++i) {
    const auto length = payload_size(shape, i);
    auto bytes = std::span(payload).first(length);
    make_payload(bytes, o.seed, i);
    // The last record is selected even when not on the stride, preserving a
    // true late-match fixture. Sparse selectivity is among selected candidates.
    const auto selected = i % candidate_every == 0 || i + 1 == o.records;
    const auto match = selected && matches(name, i, o.records, f.candidate_records);
    const auto topic = selected ? (match ? hit : miss)[f.candidate_records % k] : background;
    if (selected) ++f.candidate_records;
    const auto seq = f.engine->publish(topic, bytes);
    if (match) f.oracle.add(seq, f.engine->ring().head_pos() - span_size(shape, i), topic, bytes);
  }
  f.upper = f.engine->ring().head_seq() - 1;
  if (f.after + 1 < f.engine->ring().tail_seq()) throw std::logic_error("fixture evicted primary history");
  for (auto pos = f.engine->ring().seek_after(f.after); pos < f.engine->ring().head_pos();) {
    const auto item = f.engine->ring().at(pos);
    if (item.pad) ++f.pads_in_range;
    pos += item.size;
  }
  f.index_reserved_bytes = f.engine->index()->stats().memory.reserved_bytes;
  f.ring_checkpoint_bytes = f.engine->ring().checkpoint_slots() * sizeof(LogPos);
  f.reserved_bytes = ring_bytes + f.ring_checkpoint_bytes + f.index_reserved_bytes + f.conservative_topics_bytes;
  if (f.reserved_bytes > fixture_cap) throw std::length_error("exact fixture reserved subtotal exceeds 128MiB cap");
  f.build_ns = ns() - start;
  return f;
}
void add(ReplayWork &a, const ReplayWork &b) {
  a.bytes_inspected += b.bytes_inspected; a.entries_visited += b.entries_visited;
  a.records_fetched += b.records_fetched; a.delivered += b.delivered;
  a.pads_inspected += b.pads_inspected; a.seek_data_examined += b.seek_data_examined;
  a.seek_pads_examined += b.seek_pads_examined; a.index_seeks += b.index_seeks;
}
ReplayWork delta(const ReplayWork &a, const ReplayWork &b) {
  return {a.bytes_inspected - b.bytes_inspected, a.entries_visited - b.entries_visited,
    a.records_fetched - b.records_fetched, a.delivered - b.delivered,
    a.pads_inspected - b.pads_inspected, a.seek_data_examined - b.seek_data_examined,
    a.seek_pads_examined - b.seek_pads_examined, a.index_seeks - b.index_seeks};
}
std::string work_json(const ReplayWork &w) {
  std::ostringstream out;
  out << "{\"bytes_inspected\":" << w.bytes_inspected << ",\"entries_visited\":" << w.entries_visited
      << ",\"records_fetched\":" << w.records_fetched << ",\"delivered\":" << w.delivered
      << ",\"pads_inspected\":" << w.pads_inspected << ",\"seek_data_examined\":" << w.seek_data_examined
      << ",\"seek_pads_examined\":" << w.seek_pads_examined << ",\"index_seeks\":" << w.index_seeks << '}';
  return out.str();
}
struct Samples {
  std::vector<std::uint64_t> values;
  std::uint64_t sum{};
  void push(std::uint64_t value) { values.push_back(value); sum += value; }
  std::string json() {
    std::sort(values.begin(), values.end());
    auto percentile = [&](std::uint64_t p) -> std::uint64_t {
      if (values.empty()) return 0;
      return values[(p * values.size() + 99) / 100 - 1];
    };
    std::ostringstream out;
    out << "{\"sample_count\":" << values.size() << ",\"p50\":" << percentile(50)
        << ",\"p95\":" << percentile(95) << ",\"p99\":" << percentile(99)
        << ",\"max\":" << (values.empty() ? 0 : values.back()) << ",\"sum\":" << sum << '}';
    return out.str();
  }
};
ReplayMode mode(std::string_view text) {
  return text == "scan" ? ReplayMode::Scan : text == "indexed" ? ReplayMode::Indexed : ReplayMode::Auto;
}
std::string_view mode_name(ReplayMode value) { return value == ReplayMode::Scan ? "scan" : value == ReplayMode::Indexed ? "indexed" : "auto"; }
MergeKernel kernel(std::string_view text) {
  return text == "stdpq" ? MergeKernel::StdPQ : text == "binheap" ? MergeKernel::BinHeap :
      text == "quad" ? MergeKernel::Quad : MergeKernel::Loser;
}
std::size_t stop_index(PollStop stop) {
  switch (stop) {
  case PollStop::NoWork: return 0;
  case PollStop::OutputLimit: return 1;
  case PollStop::InspectionLimit: return 2;
  case PollStop::SnapshotDone: return 3;
  case PollStop::CaughtUp: return 4;
  case PollStop::Error: return 5;
  }
  throw std::logic_error("unknown poll stop");
}
struct Arm { std::string mode, kernel, budget, schedule; };
std::uint64_t rss() {
  rusage value{};
  if (::getrusage(RUSAGE_SELF, &value) != 0) throw std::runtime_error("getrusage failed");
  return static_cast<std::uint64_t>(value.ru_maxrss) * 1024;
}
std::string run(const Options &o, Fixture &f, const Arm &arm) {
  EngineConfig service_config;
  service_config.ring_bytes = 4096;
  service_config.index_enabled = false;
  Engine victim(service_config), publisher(service_config);
  const auto victim_topic = victim.intern("victim/message");
  const auto publish_topic = publisher.intern("publisher/message");
  std::array<std::byte, 16> service_payload{};
  victim.publish(victim_topic, service_payload);
  const auto victim_sub = victim.compile({{{Term::Exact, "victim/message"}}});
  std::vector<Delivered> victim_output;
  victim_output.reserve(1);
  const auto open_start = ns();
  auto replay = f.engine->open_replay(f.subscription, f.after, mode(arm.mode), kernel(arm.kernel));
  const auto open_ns = ns() - open_start;
  const auto open_work = replay.work();
  const auto effective = replay.effective_mode();
  const auto bounded = !one_of(arm.budget, {"legacy", "unlimited"});
  const auto cap = bounded ? std::optional<std::uint64_t>{number(arm.budget)} : std::nullopt;
  Samples latency, victim_delay, publisher_delay;
  const auto sample_bound = o.records + f.pads_in_range + 2;
  latency.values.reserve(sample_bound); victim_delay.values.reserve(sample_bound); publisher_delay.values.reserve(sample_bound);
  Digest actual;
  ReplayWork work;
  std::array<std::uint64_t, 6> stops{};
  std::uint64_t calls{}, inspections{}, max_inspections{}, max_outputs{}, zero_outputs{}, service_calls{};
  std::vector<Delivered> output;
  // Deliberately leave output initially unreserved: normal public-call growth
  // and its allocator cost are inside the first poll timing.
  const auto cpu_start = ns(CLOCK_THREAD_CPUTIME_ID);
  const auto drain_start = ns();
  auto serve = [&](std::uint64_t eligibility) {
    victim_delay.push(ns() - eligibility);
    auto short_reader = victim.open_replay(victim_sub, 0);
    const auto state = short_reader.next_batch(1, victim_output);
    if (state == Status::Error || victim_output.size() != 1 || victim_output[0].seq != 1 ||
        victim_output[0].payload.size() != service_payload.size()) throw std::logic_error("victim reader failed");
    publisher_delay.push(ns() - eligibility);
    publisher.publish(publish_topic, service_payload);
    ++service_calls;
  };
  Status status = replay.status();
  do {
    if (calls >= sample_bound) throw std::logic_error("drain exceeded conservative progress bound");
    const auto eligibility = ns();
    const auto before = replay.work();
    const auto poll_start = ns();
    std::optional<PollResult> result;
    if (arm.budget == "legacy") status = replay.next_batch(static_cast<std::size_t>(o.outputs), output);
    else {
      result = replay.next_batch(PollLimits{static_cast<std::size_t>(o.outputs), cap}, output);
      status = result->status;
    }
    const auto elapsed = ns() - poll_start;
    latency.push(elapsed);
    ++calls;
    const auto observed = delta(replay.work(), before);
    add(work, observed);
    const auto units = effective == ReplayMode::Indexed ? observed.entries_visited : observed.records_fetched + observed.pads_inspected;
    if (result) {
      ++stops[stop_index(result->stop)];
      if (result->inspections_used != units || result->work_delta != observed)
        throw std::logic_error("reported poll work disagrees with cumulative physical work");
    }
    if ((cap && units > *cap) || output.size() > o.outputs) throw std::logic_error("poll exceeded supplied limit");
    if (bounded && status == Status::More && units == 0 && output.empty()) throw std::logic_error("positive bounded poll made no progress");
    inspections += units;
    max_inspections = std::max(max_inspections, units);
    max_outputs = std::max(max_outputs, static_cast<std::uint64_t>(output.size()));
    if (output.empty()) ++zero_outputs;
    for (const auto &item : output) actual.add(item.seq, item.pos, item.topic, item.payload);
    if (arm.schedule == "round-robin") serve(eligibility);
    if (status == Status::Error) throw std::logic_error("static retained replay returned Error");
  } while (status == Status::More);
  if (arm.schedule == "immediate-redrain") serve(drain_start);
  const auto drain_ns = ns() - drain_start;
  const auto cpu_ns = ns(CLOCK_THREAD_CPUTIME_ID) - cpu_start;
  if (actual != f.oracle || work.delivered != actual.outputs) throw std::logic_error("eventual replay differs from independent publication-time oracle");
  if (!replay.checkpoint() || replay.checkpoint()->after_seq != f.upper || replay.upper_seq() != f.upper)
    throw std::logic_error("replay final captured boundary mismatch");
  std::ostringstream out;
  out << std::setprecision(17)
      << "\"status\":\"ok\",\"correctness\":\"passed\",\"effective_mode\":" << quoted(mode_name(effective))
      << ",\"selected_partition_count\":" << replay.selected_partition_count()
      << ",\"open_elapsed_ns\":" << open_ns << ",\"open_work\":" << work_json(open_work)
      << ",\"poll_work\":" << work_json(work) << ",\"all_work\":" << work_json(replay.work())
      << ",\"calls\":" << calls << ",\"inspections_used\":" << inspections
      << ",\"max_inspections_in_call\":" << max_inspections << ",\"max_outputs_in_call\":" << max_outputs
      << ",\"zero_output_calls\":" << zero_outputs << ",\"service_calls\":" << service_calls
      << ",\"stop_counts\":{\"NoWork\":" << stops[0] << ",\"OutputLimit\":" << stops[1]
      << ",\"InspectionLimit\":" << stops[2] << ",\"SnapshotDone\":" << stops[3]
      << ",\"CaughtUp\":" << stops[4] << ",\"Error\":" << stops[5] << '}'
      << ",\"stop_counts_available\":" << (arm.budget == "legacy" ? "false" : "true")
      << ",\"drain_elapsed_ns\":" << drain_ns << ",\"drain_cpu_ns\":" << cpu_ns
      << ",\"outputs_per_drain_second\":" << (static_cast<double>(actual.outputs) * 1e9 / static_cast<double>(drain_ns))
      << ",\"fixture_records_per_poll_second\":" << (static_cast<double>(o.records) * 1e9 / static_cast<double>(std::max<std::uint64_t>(1, latency.sum)))
      << ",\"poll_latency_ns\":" << latency.json() << ",\"victim_service_delay_ns\":" << victim_delay.json()
      << ",\"publisher_service_delay_ns\":" << publisher_delay.json()
      << ",\"output_digest\":" << digest_json(actual) << ",\"oracle_digest\":" << digest_json(f.oracle)
      << ",\"final_checkpoint\":{\"after_seq\":" << replay.checkpoint()->after_seq << ",\"next_pos\":" << replay.checkpoint()->next_pos << '}'
      << ",\"peak_rss_bytes\":" << rss();
  return out.str();
}
std::string host_json() {
  utsname host{};
  if (::uname(&host) != 0) throw std::runtime_error("uname failed");
  std::ostringstream out;
  out << "{\"system\":" << quoted(host.sysname) << ",\"release\":" << quoted(host.release)
      << ",\"machine\":" << quoted(host.machine) << ",\"hostname\":" << quoted(host.nodename)
      << ",\"hardware_concurrency\":" << std::thread::hardware_concurrency()
      << ",\"compiler\":" << quoted(__VERSION__)
#ifdef NDEBUG
      << ",\"ndebug\":true"
#else
      << ",\"ndebug\":false"
#endif
      << '}';
  return out.str();
}
} // namespace

int main(int argc, char **argv) {
  try {
    const auto o = parse(argc, argv);
    JsonLines output(o.output);
    const auto host = host_json();
    bool failed = false;
    for (const auto &name : o.cases) for (const auto &shape : o.shapes)
      for (const auto &k_text : o.partitions) for (const auto &candidate_text : o.candidate_every) {
      const auto k = number(k_text);
      const auto candidate_every = number(candidate_text);
      std::optional<Fixture> f;
      std::string fixture_error;
      bool infeasible{};
      try { f.emplace(fixture(o, name, shape, k, candidate_every)); }
      catch (const std::length_error &error) { fixture_error = error.what(); infeasible = true; }
      catch (const std::exception &error) { fixture_error = error.what(); }
      std::vector<Arm> arms;
      for (const auto &m : o.modes) for (const auto &merge : o.kernels)
        for (const auto &budget : o.budgets) for (const auto &schedule : o.schedules)
          arms.push_back({m, merge, budget, schedule});
      for (std::uint64_t repetition = 0; repetition < o.reps; ++repetition) {
        const auto rotation = static_cast<std::size_t>((o.seed + repetition * 17) % arms.size());
        for (std::size_t order = 0; order < arms.size(); ++order) {
          const auto &arm = arms[(order + rotation) % arms.size()];
          std::ostringstream row;
          row << "{\"schema\":\"tiplog.f01.poll-benchmark.v1\",\"reader\":\"replay\",\"case\":" << quoted(name)
              << ",\"shape\":" << quoted(shape) << ",\"records\":" << o.records << ",\"seed\":" << o.seed
              << ",\"configured_partitions\":" << k << ",\"mode\":" << quoted(arm.mode) << ",\"kernel\":" << quoted(arm.kernel)
              << ",\"candidate_every\":" << candidate_every
              << ",\"budget\":" << quoted(arm.budget) << ",\"schedule\":" << quoted(arm.schedule)
              << ",\"max_outputs\":" << o.outputs << ",\"repetition\":" << repetition << ",\"arm_order\":" << order
              << ",\"host\":" << host << ',';
          if (!f) {
            failed = true;
            row << "\"status\":" << quoted(infeasible ? "infeasible" : "error") << ",\"error\":" << quoted(fixture_error);
          } else {
            row << "\"fixture_build_ns\":" << f->build_ns << ",\"fixture_reserved_bytes\":" << f->reserved_bytes
                << ",\"index_reserved_bytes\":" << f->index_reserved_bytes
                << ",\"ring_checkpoint_bytes\":" << f->ring_checkpoint_bytes
                << ",\"conservative_topics_bytes\":" << f->conservative_topics_bytes
                << ",\"fixture_data_bytes\":" << f->data_bytes << ",\"fixture_pads_in_range\":" << f->pads_in_range
                << ",\"fixture_candidate_records\":" << f->candidate_records
                << ",\"fixture_priming_records\":" << f->priming_records << ",\"fixture_selected_partitions\":" << f->selected_partitions << ',';
            try { row << run(o, *f, arm); }
            catch (const std::exception &error) {
              failed = true;
              row << "\"status\":\"error\",\"error\":" << quoted(error.what());
            }
          }
          row << '}';
          output.line(row.str());
        }
      }
    }
    output.close();
    return failed ? 1 : 0;
  } catch (const std::exception &error) {
    std::cerr << "tiplog_poll_bench: " << error.what() << '\n';
    return 1;
  }
}
