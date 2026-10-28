#include "differential/campaign.hpp"
#include "scan_oracle.hpp"
#include "tiplog/engine/engine.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <optional>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>

namespace tiplog::differential {
namespace {
void require(bool condition, std::string_view what) {
  if (!condition)
    throw std::runtime_error(std::string(what));
}
void digest(std::uint64_t &state, std::uint64_t value) {
  for (unsigned i = 0; i < 8; ++i) {
    state ^= value & 255U;
    state *= 1099511628211ULL;
    value >>= 8U;
  }
}
std::string path(std::mt19937_64 &random) {
  const auto root = random() % 3, symbol = random() % 12, family = random() % 4;
  std::string value = "root" + std::to_string(root);
  if (random() % 13 == 0)
    return value;
  value += "/sym" + std::to_string(symbol);
  if (random() % 7 == 0)
    return value;
  value += "/family" + std::to_string(family);
  if (random() % 3 == 0)
    value += "/leaf" + std::to_string(random() % 5);
  return value;
}
SubscriptionSpec subscription(std::mt19937_64 &random,
                              const std::vector<std::string> &paths) {
  SubscriptionSpec result;
  switch (random() % 8) {
  case 0:
    result.terms.push_back(
        {Term::Subtree, "root" + std::to_string(random() % 3)});
    break;
  case 1:
    result.terms.push_back({Term::Exact, "absent/symbol/family"});
    break;
  default: {
    const auto count = 1 + random() % 5;
    for (std::uint64_t i = 0; i < count; ++i) {
      auto value = paths[static_cast<std::size_t>(random() % paths.size())];
      if (random() % 3 == 0) {
        const auto slash = value.rfind('/');
        if (slash != std::string::npos)
          value.resize(slash);
      }
      result.terms.push_back(
          {random() % 2 ? Term::Exact : Term::Subtree, std::move(value)});
    }
    if (random() % 2 == 0)
      result.terms.push_back(result.terms.front());
    break;
  }
  }
  return result;
}
struct Pair {
  Replay actual;
  ref::OracleReplay expected;
};
void compare(const Engine &engine, const Replay &actual,
             const ref::OracleReplay &expected) {
  static_cast<void>(engine);
  require(actual.status() == expected.status(), "status mismatch");
  require(actual.error() == expected.error(), "error fields mismatch");
  require(actual.checkpoint() == expected.checkpoint(),
          "progress checkpoint mismatch");
  require(actual.upper_seq() == expected.upper_seq(),
          "upper sequence mismatch");
  require(actual.upper_pos() == expected.upper_pos(),
          "upper position mismatch");
}
void one_seed(const Config &config, std::uint64_t seed, Result &result) {
  std::mt19937_64 random(seed);
  const std::size_t capacity = std::size_t{4096} << (seed % 5);
  EngineConfig engine_config;
  engine_config.ring_bytes = capacity;
  engine_config.max_record_bytes = capacity / 2;
  engine_config.index.entries_per_block = 16;
  // The path grammar has exactly three roots and twelve symbols per root:
  // 39 path partitions including unused depth-one ancestors. Compiling the
  // deliberately nonexistent exact term also interns absent and absent/symbol,
  // giving an independently bounded total of 41 registered partitions.
  // The approved generic-minimum bound prevents pressure independently of
  // observed engine retention. V19/F3 cover intentional pressure separately.
  engine_config.index.blocks = index::Index::sizing_blocks(capacity, 16, 16, 41);
  Engine engine(engine_config);
  ref::ScanOracle oracle({capacity, capacity / 2});
  std::vector<std::string> paths;
  for (unsigned i = 0; i < 48; ++i)
    paths.push_back(path(random));
  std::array<std::optional<Pair>, 8> replays;
  std::vector<Delivered> actual;
  std::vector<ref::OracleRecord> expected;
  for (std::uint64_t operation = 0; operation < config.operations;
       ++operation) {
    try {
      const auto action = random() % 100;
      if (action < 56) {
        if (random() % 101 == 0)
          paths.push_back(path(random));
        const auto &name =
            paths[static_cast<std::size_t>(random() % paths.size())];
        const auto topic = engine.intern(name);
        std::size_t length = static_cast<std::size_t>(random() % 257);
        if (random() % 37 == 0)
          length = capacity / 2 - 16;
        if (random() % 89 == 0)
          length = capacity / 2; // strong-rejection fixture
        std::vector<std::byte> bytes(length);
        if (random() % 4 == 0) {
          // Preserve repeated-byte/equal-valued events as deliberate cases.
          std::fill(bytes.begin(), bytes.end(), static_cast<std::byte>(random() % 256));
        } else {
          std::uint64_t word = 0;
          for (std::size_t i = 0; i < bytes.size(); ++i) {
            if (i % 8 == 0) word = random();
            bytes[i] = static_cast<std::byte>(word & 255U);
            word >>= 8U;
          }
        }
        const auto before = engine.stats();
        bool rejected = false;
        Seq seq{};
        try {
          seq = engine.publish(topic, bytes);
        } catch (const std::length_error &) {
          rejected = true;
        }
        bool oracle_rejected = false;
        Seq reference{};
        try {
          reference = oracle.publish(name, bytes);
        } catch (const std::length_error &) {
          oracle_rejected = true;
        }
        require(rejected == oracle_rejected, "publish rejection mismatch");
        if (rejected) {
          ++result.rejected_publications;
          const auto after = engine.stats();
          require(after.head_seq == before.head_seq &&
                      after.tail_seq == before.tail_seq &&
                      after.head_pos == before.head_pos &&
                      after.tail_pos == before.tail_pos,
                  "rejection mutated log");
        } else {
          ++result.publications;
          if (!bytes.empty() && std::any_of(bytes.begin() + 1, bytes.end(),
                [&](auto byte) { return byte != bytes.front(); }))
            ++result.nonuniform_publications;
          require(seq == reference, "published sequence mismatch");
          digest(result.final_digest, seq);
        }
        require(engine.stats().head_pos == oracle.head_pos() &&
                    engine.stats().tail_pos == oracle.tail_pos() &&
                    engine.stats().head_seq == oracle.head_seq() &&
                    engine.stats().tail_seq == oracle.tail_seq(),
                "retention boundary mismatch");
      } else if (action < 75) {
        const auto slot = static_cast<std::size_t>(random() % replays.size());
        if (random() % 43 == 0) {
          bool actual_rejected = false, expected_rejected = false;
          try {
            static_cast<void>(engine.compile({}));
          } catch (const std::invalid_argument &) {
            actual_rejected = true;
          }
          try {
            static_cast<void>(oracle.open_replay({}, 0));
          } catch (const std::invalid_argument &) {
            expected_rejected = true;
          }
          require(actual_rejected && expected_rejected, "empty spec accepted");
          ++result.empty_specs_rejected;
        } else {
          auto spec = subscription(random, paths);
          const auto upper = engine.stats().head_seq - 1;
          Seq after{};
          switch (random() % 8) {
          case 0:
            after = 0;
            break;
          case 1:
            after = engine.stats().tail_seq - 1;
            break;
          case 2:
            after = upper;
            break;
          case 3:
            after = std::numeric_limits<Seq>::max();
            break;
          case 4:
            after = random() % (upper + 1);
            break;
          default:
            // Most opens should have retained work. Keep the expired/future/
            // empty cases above, but sample valid checkpoints independently
            // from the oracle's retained interval as well.
            after = oracle.tail_seq() - 1 +
                    random() % (oracle.head_seq() - oracle.tail_seq() + 1);
            break;
          }
          auto compiled = engine.compile(spec);
          replays[slot].emplace(Pair{
              engine.open_replay(compiled, after, config.mode, config.kernel),
              oracle.open_replay(spec, after)});
          auto &pair = *replays[slot];
          compare(engine, pair.actual, pair.expected);
          ++result.opens;
          if (pair.actual.effective_mode() == ReplayMode::Indexed) {
            ++result.indexed_opens;
            if (pair.actual.selected_partition_count() > 1)
              ++result.multicursor_opens;
          } else {
            ++result.scan_opens;
          }
          if (pair.actual.error())
            ++result.history_expired;
        }
      } else if (action < 97) {
        auto slot = static_cast<std::size_t>(random() % replays.size());
        if (random() % 4 != 0) {
          // Preserve arbitrary/stale-handle batches in one quarter of choices.
          // Otherwise use a still-live reader before it is overwritten/evicted.
          for (std::size_t offset = 0; offset < replays.size(); ++offset) {
            const auto candidate = (slot + offset) % replays.size();
            if (replays[candidate] && replays[candidate]->actual.status() == Status::More) {
              const auto checkpoint = replays[candidate]->actual.checkpoint();
              if (checkpoint && checkpoint->next_pos >= engine.stats().tail_pos &&
                  checkpoint->next_pos < replays[candidate]->actual.upper_pos()) {
                slot = candidate;
                break;
              }
            }
          }
        }
        if (replays[slot]) {
          auto &pair = *replays[slot];
          const auto budget = static_cast<std::size_t>(random() % 18);
          if (budget != 0 && pair.actual.status() == Status::More &&
              pair.actual.checkpoint()->next_pos < pair.actual.upper_pos() &&
              pair.actual.checkpoint()->next_pos >= engine.stats().tail_pos) {
            if (pair.actual.effective_mode() == ReplayMode::Indexed)
              ++result.indexed_execution_batches;
            else
              ++result.scan_execution_batches;
          }
          const auto status = pair.actual.next_batch(budget, actual);
          require(status == pair.expected.next_batch(budget, expected),
                  "batch return status mismatch");
          compare(engine, pair.actual, pair.expected);
          require(actual.size() == expected.size(), "batch length mismatch");
          for (std::size_t i = 0; i < actual.size(); ++i) {
            const auto &a = actual[i];
            const auto &e = expected[i];
            require(a.seq == e.seq && a.pos == e.pos,
                    "ordered record locator mismatch");
            require(engine.registry().get(a.topic).path == e.path,
                    "raw topic path mismatch");
            require(std::ranges::equal(a.payload, e.payload),
                    "payload mismatch");
            if (i != 0)
              require(actual[i - 1].seq < a.seq, "duplicate/unordered output");
            digest(result.final_digest, a.seq);
            digest(result.final_digest, a.pos);
            for (const auto byte : a.payload) {
              result.final_digest ^= std::to_integer<unsigned char>(byte);
              result.final_digest *= 1099511628211ULL;
            }
          }
          ++result.batches;
          result.delivered += actual.size();
          if (pair.actual.error() &&
              pair.actual.error()->kind == ReplayError::FellBehind)
            ++result.fell_behind;
        }
      } else {
        replays[static_cast<std::size_t>(random() % replays.size())].reset();
      }
      engine.check_invariants();
      ++result.operations;
    } catch (const std::exception &error) {
      std::ostringstream message;
      message << "seed=" << seed << " operation=" << operation
              << " capacity=" << capacity << ": " << error.what();
      throw std::runtime_error(message.str());
    }
  }
  ++result.seeds;
}
} // namespace
Result run(const Config &config) {
  if (config.seeds == 0 || config.operations == 0 ||
      config.seed_base > UINT64_MAX - (config.seeds - 1))
    throw std::invalid_argument("invalid differential range");
  Result result;
  for (std::uint64_t i = 0; i < config.seeds; ++i)
    one_seed(config, config.seed_base + i, result);
  return result;
}
} // namespace tiplog::differential
