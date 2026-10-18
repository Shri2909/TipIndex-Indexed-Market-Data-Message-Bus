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
                              const std::vector<std::string> &paths,
                              bool one_partition) {
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
    const auto selected = paths[static_cast<std::size_t>(random() % paths.size())];
    const auto first_slash = selected.find('/');
    if (one_partition && first_slash == std::string::npos) {
      result.terms.push_back({Term::Subtree, selected});
      break; // Root subscriptions are the explicitly exercised wide fallback.
    }
    const auto second_slash = first_slash == std::string::npos
                                  ? std::string::npos
                                  : selected.find('/', first_slash + 1);
    const auto partition = selected.substr(0, second_slash);
    std::vector<std::string> candidates;
    if (one_partition) {
      for (const auto &candidate : paths)
        if (candidate == partition ||
            (candidate.starts_with(partition) &&
             candidate.size() > partition.size() &&
             candidate[partition.size()] == '/'))
          candidates.push_back(candidate);
    }
    for (std::uint64_t i = 0; i < count; ++i) {
      auto value = one_partition
          ? candidates[static_cast<std::size_t>(random() % candidates.size())]
          : paths[static_cast<std::size_t>(random() % paths.size())];
      if (random() % 3 == 0) {
        const auto slash = value.rfind('/');
        if (slash != std::string::npos &&
            (!one_partition || slash >= partition.size()))
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
        const auto fill = static_cast<std::byte>(random() % 256);
        std::fill(bytes.begin(), bytes.end(),
                  fill); // equal-valued independent events occur
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
          auto spec = subscription(random, paths, config.mode == ReplayMode::Indexed);
          const auto upper = engine.stats().head_seq - 1;
          Seq after{};
          switch (random() % 6) {
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
          default:
            after = random() % (upper + 1);
            break;
          }
          auto compiled = engine.compile(spec);
          replays[slot].emplace(Pair{
              engine.open_replay(compiled, after, config.mode, config.kernel),
              oracle.open_replay(spec, after)});
          auto &pair = *replays[slot];
          compare(engine, pair.actual, pair.expected);
          ++result.opens;
          if (pair.actual.effective_mode() == ReplayMode::Indexed)
            ++result.indexed_opens;
          else
            ++result.scan_opens;
          if (pair.actual.error())
            ++result.history_expired;
        }
      } else if (action < 97) {
        const auto slot = static_cast<std::size_t>(random() % replays.size());
        if (replays[slot]) {
          auto &pair = *replays[slot];
          const auto budget = static_cast<std::size_t>(random() % 18);
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
