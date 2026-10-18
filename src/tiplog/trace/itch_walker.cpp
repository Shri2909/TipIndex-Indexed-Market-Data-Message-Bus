#include "tiplog/trace/itch_walker.hpp"

#include "tiplog/trace/reader.hpp"

#include <algorithm>
#include <limits>
#include <ostream>

namespace tiplog::trace {

std::uint16_t itch_message_size(unsigned char type) noexcept {
  switch (type) {
    case 'S': return 12;
    case 'R': return 39;
    case 'H': return 25;
    case 'Y': return 20;
    case 'L': return 26;
    case 'V': return 35;
    case 'W': return 12;
    case 'K': return 28;
    case 'J': return 35;
    case 'h': return 21;
    case 'A': return 36;
    case 'F': return 40;
    case 'E': return 31;
    case 'C': return 36;
    case 'X': return 23;
    case 'D': return 19;
    case 'U': return 35;
    case 'P': return 44;
    case 'Q': return 40;
    case 'B': return 19;
    case 'I': return 50;
    case 'N': return 20;
    case 'O': return 48;
    default: return 0;
  }
}

void ItchWalker::feed(std::span<const std::byte> input) {
  if (input.size() > std::numeric_limits<std::uint64_t>::max() - total_bytes_)
    throw FormatError("BinaryFILE byte counter overflow");
  total_bytes_ += input.size();
  while (!input.empty()) {
    if (terminated_) throw FormatError("bytes follow BinaryFILE terminator");
    if (length_filled_ < 2) {
      length_bytes_[length_filled_++] = input.front();
      input = input.subspan(1);
      if (length_filled_ < 2) continue;
      length_ = static_cast<std::uint16_t>(
          (std::to_integer<unsigned>(length_bytes_[0]) << 8U) |
          std::to_integer<unsigned>(length_bytes_[1]));
      if (length_ == 0) { terminated_ = true; continue; }
      if (length_ > payload_.size()) throw FormatError("unsupported ITCH frame length");
    }
    const auto count = std::min(input.size(), static_cast<std::size_t>(length_) - payload_filled_);
    std::copy_n(input.begin(), count, payload_.begin() + static_cast<std::ptrdiff_t>(payload_filled_));
    payload_filled_ += count;
    input = input.subspan(count);
    if (payload_filled_ == length_) {
      accept_message();
      length_filled_ = 0;
      payload_filled_ = 0;
    }
  }
}

void ItchWalker::accept_message() {
  const auto type = std::to_integer<unsigned char>(payload_[0]);
  if (itch_message_size(type) == 0) throw FormatError("unknown ITCH message type");
  if (itch_message_size(type) != length_) throw FormatError("ITCH length disagrees with specification");
  const auto locate = (std::to_integer<unsigned>(payload_[1]) << 8U) |
                      std::to_integer<unsigned>(payload_[2]);
  std::uint64_t ts = 0;
  for (std::size_t i = 5; i < 11; ++i)
    ts = (ts << 8U) | std::to_integer<unsigned char>(payload_[i]);
  if (total_count_ != 0 && ts < previous_ts_) ++inversions_;
  previous_ts_ = ts;
  const auto add = [this](MessageCounter& counter) {
    ++counter.count;
    counter.payload_bytes += length_;
    counter.framed_bytes += static_cast<std::uint64_t>(length_) + 2;
  };
  add(types_[type]);
  add(locates_[locate]);
  ++total_count_;
  payload_bytes_ += length_;
}

void ItchWalker::finish() const {
  if (!terminated_ && (length_filled_ != 0 || payload_filled_ != 0))
    throw FormatError("truncated BinaryFILE length/payload");
}

void ItchWalker::write_json(std::ostream& out) const {
  finish();
  out << "{\n  \"total_uncompressed_bytes\": " << total_bytes_
      << ",\n  \"message_count\": " << total_count_
      << ",\n  \"payload_bytes\": " << payload_bytes_
      << ",\n  \"terminated\": " << (terminated_ ? "true" : "false")
      << ",\n  \"incomplete\": " << (terminated_ ? "false" : "true")
      << ",\n  \"timestamp_inversions\": " << inversions_ << ",\n  \"by_type\": {";
  const auto counters = [&out](const MessageCounter& c) {
    out << "{\"count\":" << c.count << ",\"payload_bytes\":" << c.payload_bytes
        << ",\"framed_bytes\":" << c.framed_bytes << '}';
  };
  bool first = true;
  for (std::size_t i = 0; i < types_.size(); ++i) {
    if (types_[i].count == 0) continue;
    if (!first) out << ',';
    first = false;
    out << '\n' << "    \"" << static_cast<char>(i) << "\":";
    counters(types_[i]);
  }
  out << "\n  },\n  \"by_locate\": {";
  first = true;
  for (std::size_t i = 0; i < locates_.size(); ++i) {
    if (locates_[i].count == 0) continue;
    if (!first) out << ',';
    first = false;
    out << '\n' << "    \"" << i << "\":";
    counters(locates_[i]);
  }
  out << "\n  }\n}\n";
}

}  // namespace tiplog::trace
