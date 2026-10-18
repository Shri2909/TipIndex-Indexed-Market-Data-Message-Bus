#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <iosfwd>
#include <span>

namespace tiplog::trace {

struct MessageCounter {
  std::uint64_t count{};
  std::uint64_t payload_bytes{};
  std::uint64_t framed_bytes{};
};

// Independently transcribed from Nasdaq's ITCH field-offset tables. This module
// shares no lengths, framing decoder, or topic-routing helpers with Python.
[[nodiscard]] std::uint16_t itch_message_size(unsigned char type) noexcept;

class ItchWalker {
 public:
  void feed(std::span<const std::byte> input);
  void finish() const;
  [[nodiscard]] std::uint64_t total_uncompressed_bytes() const noexcept { return total_bytes_; }
  [[nodiscard]] std::uint64_t message_count() const noexcept { return total_count_; }
  [[nodiscard]] std::uint64_t payload_bytes() const noexcept { return payload_bytes_; }
  [[nodiscard]] std::uint64_t timestamp_inversions() const noexcept { return inversions_; }
  [[nodiscard]] bool terminated() const noexcept { return terminated_; }
  [[nodiscard]] const auto& by_type() const noexcept { return types_; }
  [[nodiscard]] const auto& by_locate() const noexcept { return locates_; }
  void write_json(std::ostream& out) const;

 private:
  void accept_message();
  std::array<MessageCounter, 256> types_{};
  std::array<MessageCounter, 65536> locates_{};
  std::array<std::byte, 50> payload_{};
  std::array<std::byte, 2> length_bytes_{};
  std::size_t length_filled_{};
  std::size_t payload_filled_{};
  std::uint16_t length_{};
  bool terminated_{};
  std::uint64_t total_bytes_{};
  std::uint64_t total_count_{};
  std::uint64_t payload_bytes_{};
  std::uint64_t inversions_{};
  std::uint64_t previous_ts_{};
};

}  // namespace tiplog::trace
