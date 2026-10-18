#include "tiplog/driver/trace_driver.hpp"
#include "tiplog/engine/engine.hpp"

#include <algorithm>
#include <charconv>
#include <filesystem>
#include <iostream>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {
std::uint64_t number(std::string_view value) {
  std::uint64_t result{};
  const auto parsed =
      std::from_chars(value.data(), value.data() + value.size(), result);
  if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()) {
    throw std::invalid_argument("expected unsigned decimal integer");
  }
  return result;
}
void hash_number(std::uint64_t &state, std::uint64_t value) {
  for (unsigned i = 0; i < 8; ++i) {
    state ^= value & 255U;
    state *= 1099511628211ULL;
    value >>= 8U;
  }
}
void hash_delivery(std::uint64_t &state, const tiplog::Delivered &record) {
  hash_number(state, record.seq);
  hash_number(state, record.pos);
  for (const auto byte : record.payload) {
    state ^= std::to_integer<unsigned char>(byte);
    state *= 1099511628211ULL;
  }
}
} // namespace

int main(int argc, char **argv) {
  try {
    tiplog::driver::Config config;
    tiplog::EngineConfig engine_config;
    engine_config.ring_bytes = std::size_t{1} << 20;
    engine_config.max_record_bytes = engine_config.ring_bytes / 2;
    tiplog::SubscriptionSpec subscription;
    std::filesystem::path path;
    std::string_view backend = "engine", mode_name = "scan";
    tiplog::ReplayMode mode = tiplog::ReplayMode::Scan;
    for (int i = 1; i < argc; ++i) {
      const std::string_view arg(argv[i]);
      if (arg == "--help") {
        std::cout
            << "tiplog_sim --trace FILE [--seed N] [--max-records N] [--budget "
               "N] "
               "[--consume-every N] [--pause FIRST:COUNT] [--jitter-budget] "
               "[--ring-bytes N] [--max-record-bytes N] [--exact "
               "PATH|--subtree PATH] "
               "[--backend engine|recording] [--mode scan|indexed] "
               "[--index-enabled 0|1] [--pool-blocks N] [--block-entries N] "
               "[--pool-policy force-evict|reject-publish] [--minimum-record-bytes 16|32]\n"
               "Engine backend uses captured snapshots and chains only "
               "completed progress; "
               "retention failures are explicit in JSON. Default subscription: "
               "Subtree(itch).\n";
        return 0;
      }
      if (arg == "--jitter-budget") {
        config.jitter_budget = true;
        continue;
      }
      if (i + 1 >= argc)
        throw std::invalid_argument("option requires a value");
      const std::string_view value(argv[++i]);
      if (arg == "--trace")
        path = value;
      else if (arg == "--backend")
        backend = value;
      else if (arg == "--mode")
        mode_name = value;
      else if (arg == "--index-enabled") {
        if (value != "0" && value != "1")
          throw std::invalid_argument("index-enabled must be 0 or 1");
        engine_config.index_enabled = value == "1";
      } else if (arg == "--pool-blocks" || arg == "--block-entries") {
        const auto count = number(value);
        if (count > UINT32_MAX)
          throw std::invalid_argument("index block setting exceeds u32");
        if (arg == "--pool-blocks")
          engine_config.index.blocks = static_cast<std::uint32_t>(count);
        else
          engine_config.index.entries_per_block = static_cast<std::uint32_t>(count);
      } else if (arg == "--minimum-record-bytes")
        engine_config.minimum_record_bytes = static_cast<std::size_t>(number(value));
      else if (arg == "--pool-policy") {
        if (value == "force-evict")
          engine_config.pool_policy = tiplog::PoolPolicy::ForceEvict;
        else if (value == "reject-publish")
          engine_config.pool_policy = tiplog::PoolPolicy::RejectPublish;
        else
          throw std::invalid_argument("invalid pool policy");
      }
      else if (arg == "--seed")
        config.seed = number(value);
      else if (arg == "--max-records")
        config.max_records = number(value);
      else if (arg == "--ring-bytes")
        engine_config.ring_bytes = static_cast<std::size_t>(number(value));
      else if (arg == "--max-record-bytes")
        engine_config.max_record_bytes =
            static_cast<std::size_t>(number(value));
      else if (arg == "--exact")
        subscription.terms.push_back({tiplog::Term::Exact, std::string(value)});
      else if (arg == "--subtree")
        subscription.terms.push_back(
            {tiplog::Term::Subtree, std::string(value)});
      else if (arg == "--budget") {
        const auto budget = number(value);
        if (budget > std::numeric_limits<std::size_t>::max())
          throw std::invalid_argument("budget too large");
        config.batch_budget = static_cast<std::size_t>(budget);
      } else if (arg == "--consume-every")
        config.consume_every = number(value);
      else if (arg == "--pause") {
        const auto colon = value.find(':');
        if (colon == std::string_view::npos)
          throw std::invalid_argument("pause requires FIRST:COUNT");
        config.pauses.push_back(
            {number(value.substr(0, colon)), number(value.substr(colon + 1))});
      } else
        throw std::invalid_argument("unknown option");
    }
    if (mode_name == "scan")
      mode = tiplog::ReplayMode::Scan;
    else if (mode_name == "indexed")
      mode = tiplog::ReplayMode::Indexed;
    else
      throw std::invalid_argument("invalid mode (Auto is a P5 task)");
    if (path.empty())
      throw std::invalid_argument("--trace FILE is required");
    if (backend != "engine" && backend != "recording")
      throw std::invalid_argument("invalid backend");
    const tiplog::trace::Reader reader(path);
    tiplog::driver::Result result;
    std::uint64_t delivered = 0, replay_digest = 14695981039346656037ULL,
                  batches = 0, snapshots = 0;
    tiplog::Status final_status = tiplog::Status::Done;
    std::optional<tiplog::ReplayError> final_error;
    std::optional<tiplog::ResumeCheckpoint> final_checkpoint;
    tiplog::EngineStats final_stats;
    tiplog::ring::RingStats final_ring_stats;
    if (backend == "recording") {
      tiplog::Seq sequence = 0;
      result = tiplog::driver::drive_trace(
          reader, config,
          [&sequence](std::string_view, std::span<const std::byte>) {
            return ++sequence;
          });
    } else {
      tiplog::Engine engine(engine_config);
      if (subscription.terms.empty())
        subscription.terms.push_back({tiplog::Term::Subtree, "itch"});
      const auto sub = engine.compile(subscription);
      std::optional<tiplog::Replay> replay;
      tiplog::Seq resume_after = 0;
      std::vector<tiplog::Delivered> out;
      auto consume = [&](std::size_t budget) {
        if (final_error)
          return;
        if (!replay || replay->status() == tiplog::Status::Done) {
          if (replay)
            resume_after = replay->checkpoint()->after_seq;
          replay.emplace(engine.open_replay(sub, resume_after, mode));
          ++snapshots;
        }
        final_status = replay->next_batch(budget, out);
        ++batches;
        for (const auto &record : out) {
          hash_delivery(replay_digest, record);
          ++delivered;
        }
        final_error = replay->error();
        final_checkpoint = replay->checkpoint();
      };
      result = tiplog::driver::drive_trace(
          reader, config,
          [&engine](std::string_view topic,
                    std::span<const std::byte> payload) {
            return engine.publish(engine.intern(topic), payload);
          },
          [&](const tiplog::driver::Tick &tick) {
            if (!tick.paused)
              consume(tick.budget);
          });
      // Finish the current captured range, then the final published range. This
      // is deterministic draining, outside any latency/throughput experiment.
      while (!final_error) {
        consume(std::max<std::size_t>(1, config.batch_budget));
        if (final_status == tiplog::Status::Done &&
            final_checkpoint->after_seq == engine.stats().head_seq - 1)
          break;
      }
      final_stats = engine.stats();
      final_ring_stats = engine.ring().stats();
      engine.check_invariants();
    }
    std::cout << "{\"backend\":\"" << backend
              << "\",\"mode\":\"" << mode_name << "\",\"seed\":" << result.seed
              << ",\"published\":" << result.published
              << ",\"first_seq\":" << result.first_seq
              << ",\"last_seq\":" << result.last_seq
              << ",\"payload_bytes\":" << result.payload_bytes
              << ",\"publication_digest_fnv1a64\":" << result.publication_digest
              << ",\"schedule_digest_fnv1a64\":" << result.schedule_digest
              << ",\"delivered\":" << delivered
              << ",\"replay_digest_fnv1a64\":" << replay_digest
              << ",\"batches\":" << batches << ",\"snapshots\":" << snapshots
              << ",\"outcome\":\"" << (final_error ? "error" : "done")
              << "\",\"head_pos\":" << final_stats.head_pos
              << ",\"tail_pos\":" << final_stats.tail_pos
              << ",\"head_seq\":" << final_stats.head_seq
              << ",\"tail_seq\":" << final_stats.tail_seq
              << ",\"pressure_data_evicted\":" << final_ring_stats.pressure_data_evicted
              << ",\"pressure_bytes_evicted\":" << final_ring_stats.pressure_bytes_evicted;
    if (final_checkpoint)
      std::cout << ",\"checkpoint\":{\"after_seq\":"
                << final_checkpoint->after_seq
                << ",\"next_pos\":" << final_checkpoint->next_pos << '}';
    if (final_error)
      std::cout << ",\"error\":{\"kind\":\""
                << (final_error->kind == tiplog::ReplayError::HistoryExpired
                        ? "HistoryExpired"
                        : "FellBehind")
                << "\",\"requested_after\":" << final_error->requested_after
                << ",\"last_delivered\":" << final_error->last_delivered
                << ",\"oldest_retained\":" << final_error->oldest_retained
                << '}';
    std::cout << "}\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "tiplog_sim: " << error.what() << '\n';
    return 1;
  }
}
