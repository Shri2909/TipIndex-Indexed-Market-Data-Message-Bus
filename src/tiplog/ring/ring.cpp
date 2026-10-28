#include "tiplog/ring/ring.hpp"

#include <algorithm>
#include <bit>
#include <exception>
#include <limits>
#include <optional>
#include <stdexcept>

namespace tiplog::ring {
namespace {
constexpr std::uint32_t pad_bit = std::uint32_t{1} << 31U;
constexpr std::uint32_t size_mask = 0x7ffffff8U;
constexpr std::size_t header_size = 16;

std::uint32_t read32(const std::byte* p) noexcept {
  std::uint32_t result = 0;
  for (unsigned i = 0; i < 4; ++i) {
    result |= std::uint32_t{std::to_integer<unsigned char>(p[i])} << (i * 8U);
  }
  return result;
}
std::uint64_t read64(const std::byte* p) noexcept {
  std::uint64_t result = 0;
  for (unsigned i = 0; i < 8; ++i) {
    result |= std::uint64_t{std::to_integer<unsigned char>(p[i])} << (i * 8U);
  }
  return result;
}
void write32(std::byte* p, std::uint32_t value) noexcept {
  for (unsigned i = 0; i < 4; ++i) {
    p[i] = static_cast<std::byte>((value >> (i * 8U)) & 0xffU);
  }
}
void write64(std::byte* p, std::uint64_t value) noexcept {
  for (unsigned i = 0; i < 8; ++i) {
    p[i] = static_cast<std::byte>((value >> (i * 8U)) & 0xffU);
  }
}

RingConfig checked_config(RingConfig config) {
  if (config.ring_bytes < 32 || config.ring_bytes > (std::size_t{1} << 31U) ||
      !std::has_single_bit(config.ring_bytes)) {
    throw std::invalid_argument("ring capacity must be a power of two in [32, 2GiB]");
  }
  if (config.max_record_bytes < header_size || config.max_record_bytes % 8 != 0 ||
      config.max_record_bytes > config.ring_bytes / 2) {
    throw std::invalid_argument("aligned max_record must be in [16, capacity/2]");
  }
  if (config.ckpt_log2 > 62) {
    throw std::invalid_argument("checkpoint logarithm exceeds representable interval");
  }
  if (config.position_limit <= header_size || config.position_limit > (LogPos{1} << 51U)) {
    throw std::invalid_argument("logical head limit must be in (16, 2^51]");
  }
  if (config.sequence_limit < 2) {
    throw std::invalid_argument("sequence limit must permit sequence one");
  }
  return config;
}
[[noreturn]] void corrupt(const char* message) { throw std::logic_error(message); }
}  // namespace

Ring::Ring(RingConfig config)
    : config_(checked_config(config)), bytes_(config_.ring_bytes),
      checkpoints_(static_cast<std::size_t>(
          (static_cast<std::uint64_t>(config_.ring_bytes / header_size) >> config_.ckpt_log2) + 2),
          std::numeric_limits<LogPos>::max()) {}

std::size_t Ring::physical(LogPos pos) const noexcept {
  return static_cast<std::size_t>(pos & static_cast<LogPos>(config_.ring_bytes - 1));
}

Item Ring::decode(LogPos pos) const {
  const auto offset = physical(pos);
  const auto word = read32(bytes_.data() + offset);
  const auto size = static_cast<std::size_t>(word & size_mask);
  const bool pad = (word & pad_bit) != 0;
  if (size == 0 || size > config_.ring_bytes - offset ||
      static_cast<LogPos>(size) > head_pos_ - pos) {
    corrupt("invalid ring item size or physical straddle");
  }
  if (pad) {
    if ((word & 7U) != 0 || size < 8 || size >= config_.ring_bytes ||
        offset + size != config_.ring_bytes) {
      corrupt("invalid PAD framing");
    }
    return Item{pos, size, true, 0, 0, {}};
  }
  const auto fill = static_cast<std::size_t>(word & 7U);
  if (size < header_size || size > config_.max_record_bytes || fill > size - header_size) {
    corrupt("invalid DATA framing");
  }
  const auto* source = bytes_.data() + offset;
  const auto topic = read32(source + 4);
  const auto seq = read64(source + 8);
  return Item{pos, size, false, topic, seq,
              std::span<const std::byte>{source + header_size, size - header_size - fill}};
}

Item Ring::at(LogPos pos) const {
  if (pos % 8 != 0 || pos < tail_pos_ || pos >= head_pos_) {
    throw std::out_of_range("ring item position is unaligned or not retained");
  }
  return decode(pos);
}

Item Ring::at_checked(LogPos pos) const {
  if (pos >= head_pos_ || !is_boundary(pos)) {
    throw std::out_of_range("ring item position is not a retained item boundary");
  }
  return decode(pos);
}

bool Ring::is_boundary(LogPos pos) const {
  if (pos % 8 != 0 || pos < tail_pos_ || pos > head_pos_) return false;
  auto cursor = tail_pos_;
  while (cursor < pos) cursor += decode(cursor).size;
  return cursor == pos;
}

Ring::Layout Ring::dry_run(std::size_t payload_bytes, LogPos minimum_tail) const {
  // Comparing before adding also catches SIZE_MAX inputs without overflow.
  if (payload_bytes > config_.max_record_bytes - header_size) {
    throw std::length_error("payload exceeds configured maximum record size");
  }
  const auto need = (header_size + payload_bytes + std::size_t{7}) & ~std::size_t{7};
  const auto room = config_.ring_bytes - physical(head_pos_);
  const auto pad = room < need ? room : 0;
  const auto total = static_cast<LogPos>(pad + need);
  if (head_seq_ >= config_.sequence_limit) {
    throw std::overflow_error("published sequence limit exhausted");
  }
  if (total >= config_.position_limit || head_pos_ >= config_.position_limit - total) {
    throw std::overflow_error("logical ring position limit exhausted");
  }
  if (minimum_tail != 0 && !is_boundary(minimum_tail)) {
    throw std::invalid_argument("pressure tail must be a retained item boundary or head");
  }

  Layout result;
  result.original_head = head_pos_;
  result.original_tail = tail_pos_;
  result.original_sequence = head_seq_;
  result.data_pos = head_pos_ + pad;
  result.end_pos = head_pos_ + total;
  result.tail_pos = tail_pos_;
  result.tail_seq = tail_seq_;
  result.record_bytes = need;
  result.padding_bytes = pad;
  result.payload_bytes = payload_bytes;
  const auto capacity_floor = result.end_pos > config_.ring_bytes
                                  ? result.end_pos - config_.ring_bytes : 0;
  const auto target = std::max(capacity_floor, minimum_tail);
  while (result.tail_pos < target) {
    const auto item = decode(result.tail_pos);
    const bool pressure = result.tail_pos >= capacity_floor;
    result.last_evicted_start = result.tail_pos;
    result.evicted_any = true;
    if (item.pad) {
      ++result.pad_items_evicted;
      result.pad_bytes_evicted += item.size;
    } else {
      ++result.data_evicted;
      result.data_bytes_evicted += item.size;
      result.tail_seq = item.seq + 1;
      if (pressure) ++result.pressure_data_evicted;
    }
    if (pressure) {
      result.pressure = true;
      result.pressure_bytes_evicted += item.size;
    }
    result.tail_pos += item.size;
  }
  if (result.tail_pos == head_pos_) result.tail_seq = head_seq_;
  return result;
}

Ring::Plan Ring::plan_append(std::span<const std::byte> payload, LogPos minimum_tail) const {
  Plan result;
  result.owner_ = this;
  result.layout_ = dry_run(payload.size(), minimum_tail);
  result.source_ = payload;
  if (!payload.empty()) {
    const auto source = reinterpret_cast<std::uintptr_t>(payload.data());
    const auto buffer = reinterpret_cast<std::uintptr_t>(bytes_.data());
    const auto buffer_end = buffer + bytes_.size();
    // Subtractions avoid overflowing a fabricated source+length expression.
    const bool overlap = source < buffer_end &&
                         (source >= buffer || payload.size() > buffer - source);
    if (overlap) result.alias_copy_.assign(payload.begin(), payload.end());
  }
  return result;
}

void Ring::note_checkpoint(Seq seq, LogPos pos) noexcept {
  const auto interval = Seq{1} << config_.ckpt_log2;
  if ((seq & (interval - 1)) == 0) {
    const auto slot = static_cast<std::size_t>((seq >> config_.ckpt_log2) % checkpoints_.size());
    checkpoints_[slot] = pos;
  }
}

Published Ring::commit(Plan&& plan, TopicId topic) noexcept {
  const auto& layout = plan.layout_;
  if (plan.owner_ != this || layout.original_head != head_pos_ ||
      layout.original_tail != tail_pos_ || layout.original_sequence != head_seq_) {
    std::terminate();
  }
  const auto payload = plan.alias_copy_.empty()
                           ? plan.source_ : std::span<const std::byte>{plan.alias_copy_};
  auto* destination = bytes_.data() + physical(head_pos_);
  if (layout.padding_bytes != 0) {
    write32(destination, pad_bit | static_cast<std::uint32_t>(layout.padding_bytes));
    write32(destination + 4, 0);
    destination = bytes_.data();
  }
  const auto fill = layout.record_bytes - header_size - payload.size();
  write32(destination, static_cast<std::uint32_t>(layout.record_bytes) |
                           static_cast<std::uint32_t>(fill));
  write32(destination + 4, topic);
  write64(destination + 8, head_seq_);
  std::copy(payload.begin(), payload.end(), destination + header_size);
  std::fill_n(destination + header_size + payload.size(), fill, std::byte{0});

  const Published result{head_seq_, layout.data_pos, layout.record_bytes};
  note_checkpoint(head_seq_, layout.data_pos);
  tail_pos_ = layout.tail_pos;
  tail_seq_ = layout.tail_seq;
  head_pos_ = layout.end_pos;
  ++head_seq_;
  ++stats_.data_appended;
  stats_.data_evicted += layout.data_evicted;
  stats_.data_bytes_evicted += layout.data_bytes_evicted;
  stats_.pad_items_evicted += layout.pad_items_evicted;
  stats_.pad_bytes_evicted += layout.pad_bytes_evicted;
  stats_.pressure_data_evicted += layout.pressure_data_evicted;
  stats_.pressure_bytes_evicted += layout.pressure_bytes_evicted;
  if (layout.padding_bytes != 0) {
    ++stats_.pad_items_appended;
    stats_.pad_bytes_appended += layout.padding_bytes;
  }
  if (layout.evicted_any) {
    last_evicted_start_ = layout.last_evicted_start;
    has_evicted_ = true;
  }
  capacity_only_ = capacity_only_ && !layout.pressure;
  plan.owner_ = nullptr;
  return result;
}

Seq Ring::append(TopicId topic, std::span<const std::byte> payload) {
  auto plan = plan_append(payload);
  return commit(std::move(plan), topic).seq;
}

LogPos Ring::seek_after(Seq after) const {
  last_seek_ = {};
  if (after >= head_seq_ - 1) return head_pos_;
  if (after < tail_seq_ - 1) throw std::out_of_range("requested history is no longer retained");
  const auto target = after + 1;
  const auto floor = (target >> config_.ckpt_log2) << config_.ckpt_log2;
  const auto slot = static_cast<std::size_t>((floor >> config_.ckpt_log2) % checkpoints_.size());
  const auto checkpoint = checkpoints_[slot];
  auto cursor = tail_pos_;
  std::optional<Item> first;
  if (floor != 0 && checkpoint >= tail_pos_ && checkpoint < head_pos_) {
    const auto item = decode(checkpoint);
    if (!item.pad && item.seq == floor) {
      cursor = checkpoint;
      first = item;
    }
  }
  while (cursor < head_pos_) {
    const auto item = first ? *first : decode(cursor);
    first.reset();
    if (item.pad) {
      ++last_seek_.pads_examined;
    } else {
      ++last_seek_.data_examined;
      if (item.seq >= target) return cursor;
    }
    cursor += item.size;
  }
  return head_pos_;
}

void Ring::check_invariants() const {
  if (head_pos_ < tail_pos_ || head_pos_ - tail_pos_ > config_.ring_bytes ||
      head_pos_ % 8 != 0 || tail_pos_ % 8 != 0 || head_pos_ >= config_.position_limit) {
    corrupt("INV-R1: invalid logical span");
  }
  auto cursor = tail_pos_;
  auto expected_seq = tail_seq_;
  while (cursor < head_pos_) {
    const auto item = decode(cursor);
    if (!item.pad) {
      if (item.seq != expected_seq) corrupt("INV-R5: DATA sequence is not consecutive");
      ++expected_seq;
      const auto fill = item.size - header_size - item.payload.size();
      const auto* padding = item.payload.data() + item.payload.size();
      for (std::size_t i = 0; i < fill; ++i) {
        if (padding[i] != std::byte{0}) corrupt("INV-R6: nonzero DATA fill");
      }
    }
    cursor += item.size;
  }
  if (cursor != head_pos_ || expected_seq != head_seq_) {
    corrupt("INV-R2/R5: item sum or sequence bound mismatch");
  }
  const auto capacity_floor = head_pos_ > config_.ring_bytes ? head_pos_ - config_.ring_bytes : 0;
  if (capacity_only_ && has_evicted_ &&
      !(last_evicted_start_ < capacity_floor && tail_pos_ >= capacity_floor)) {
    corrupt("INV-R7: capacity-only retention is not maximal");
  }
  const auto interval = Seq{1} << config_.ckpt_log2;
  for (std::size_t slot = 0; slot < checkpoints_.size(); ++slot) {
    const auto checkpoint = checkpoints_[slot];
    if (checkpoint == std::numeric_limits<LogPos>::max() || checkpoint < tail_pos_) continue;
    if (checkpoint >= head_pos_) {
      corrupt("invalid sparse checkpoint bounds");
    }
    const auto item = decode(checkpoint);
    if (item.pad || item.seq % interval != 0 ||
        (item.seq >> config_.ckpt_log2) % checkpoints_.size() != slot) {
      corrupt("invalid sparse checkpoint record");
    }
  }
  if (stats_.data_appended - stats_.data_evicted != head_seq_ - tail_seq_) {
    corrupt("ring DATA accounting does not match retention");
  }
}

}  // namespace tiplog::ring
