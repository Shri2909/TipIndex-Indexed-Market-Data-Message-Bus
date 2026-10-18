#include "tiplog/driver/trace_driver.hpp"

#include <limits>
#include <random>
#include <stdexcept>

namespace tiplog::driver {
namespace {
void digest_byte(std::uint64_t& digest, std::uint8_t value) {
  digest ^= value;
  digest *= 1099511628211ULL;
}
void digest_number(std::uint64_t& digest, std::uint64_t value) {
  for (unsigned i = 0; i < 8; ++i) {
    digest_byte(digest, static_cast<std::uint8_t>(value & 255U));
    value >>= 8;
  }
}
}  // namespace

Result drive_trace(const trace::Reader& reader, const Config& config,
                   const Publish& publish, const Consume& consume) {
  if (!publish || config.consume_every == 0) throw std::invalid_argument("invalid driver callbacks/cadence");
  for (const auto& pause : config.pauses) {
    if (pause.first_tick == 0 || pause.ticks > std::numeric_limits<std::uint64_t>::max() - pause.first_tick) {
      throw std::invalid_argument("driver pause is outside tick range");
    }
  }
  std::mt19937_64 random(config.seed);
  Result result;
  result.seed = config.seed;
  trace::Reader::Cursor cursor;
  trace::Record record;
  while (result.published < config.max_records && reader.next(cursor, record)) {
    const auto& path = reader.topic_path(record.topic_id);
    const Seq seq = publish(path, record.payload);
    if (seq == 0 || (result.published != 0 &&
        (result.last_seq == std::numeric_limits<Seq>::max() || seq != result.last_seq + 1))) {
      throw std::logic_error("driver publisher returned non-dense sequence numbers");
    }
    if (result.published == 0) result.first_seq = seq;
    ++result.published;
    result.last_seq = seq;
    if (record.payload.size() > std::numeric_limits<std::uint64_t>::max() - result.payload_bytes) {
      throw std::overflow_error("driver byte counter exhausted");
    }
    result.payload_bytes += static_cast<std::uint64_t>(record.payload.size());
    digest_number(result.publication_digest, seq);
    digest_number(result.publication_digest, static_cast<std::uint64_t>(path.size()));
    for (const char value : path) {
      digest_byte(result.publication_digest, static_cast<std::uint8_t>(static_cast<unsigned char>(value)));
    }
    digest_number(result.publication_digest, static_cast<std::uint64_t>(record.payload.size()));
    for (const auto value : record.payload) digest_byte(result.publication_digest, std::to_integer<std::uint8_t>(value));
    const auto tick = result.published;
    bool paused = false;
    for (const auto& pause : config.pauses) {
      if (tick >= pause.first_tick && tick - pause.first_tick < pause.ticks) paused = true;
    }
    std::size_t budget = 0;
    if (!paused && tick % config.consume_every == 0) {
      budget = config.batch_budget;
      if (config.jitter_budget && budget != 0) {
        budget = 1 + static_cast<std::size_t>(random() % static_cast<std::uint64_t>(budget));
      }
    }
    const Tick event{tick, seq, budget, paused};
    digest_number(result.schedule_digest, tick);
    digest_number(result.schedule_digest, seq);
    digest_number(result.schedule_digest, static_cast<std::uint64_t>(budget));
    digest_number(result.schedule_digest, paused ? 1 : 0);
    if (consume) consume(event);
  }
  return result;
}

}  // namespace tiplog::driver
