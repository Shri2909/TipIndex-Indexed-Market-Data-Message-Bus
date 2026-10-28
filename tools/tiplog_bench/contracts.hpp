#pragma once

#include "tiplog/types.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <istream>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace tiplog::bench {

inline std::uint64_t number(std::string_view value) {
  std::uint64_t result{};
  const auto parsed =
      std::from_chars(value.data(), value.data() + value.size(), result);
  if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size())
    throw std::invalid_argument("expected unsigned decimal integer");
  return result;
}
inline std::vector<std::string> split(std::string_view value, char delimiter) {
  std::vector<std::string> result;
  for (;;) {
    const auto next = value.find(delimiter);
    result.emplace_back(value.substr(0, next));
    if (next == std::string_view::npos)
      return result;
    value.remove_prefix(next + 1);
  }
}

// Both workload generators validate the entire distribution before publishing.
// The harness supplies its supported payload bound; the checked-in empirical
// mix and its deterministic cumulative-count sampling are unchanged.
using PayloadMix = std::vector<std::pair<std::uint16_t, std::uint64_t>>;
inline PayloadMix read_payload_mix(std::istream &input,
                                   std::uint64_t maximum_payload = 256) {
  if (!input)
    throw std::invalid_argument("cannot read payload mix");
  std::string line;
  if (!std::getline(input, line))
    throw std::invalid_argument("missing payload mix header");
  if (!line.empty() && line.back() == '\r') line.pop_back();
  if (line != "type,payload_bytes,count")
    throw std::invalid_argument("payload mix header must be type,payload_bytes,count");
  PayloadMix result;
  std::array<bool, 256> types{};
  std::uint64_t total = 0;
  while (std::getline(input, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    const auto row = split(line, ',');
    if (row.size() != 3 || row[0].size() != 1 ||
        !((row[0][0] >= 'A' && row[0][0] <= 'Z') ||
          (row[0][0] >= 'a' && row[0][0] <= 'z')))
      throw std::invalid_argument("malformed payload mix row");
    const auto type = static_cast<unsigned char>(row[0][0]);
    const auto length = number(row[1]), count = number(row[2]);
    if (types[type] || length < 12 || length > maximum_payload ||
        length > UINT16_MAX || count == 0 || count > UINT64_MAX - total)
      throw std::invalid_argument("payload mix duplicate type, size, count or cumulative overflow");
    types[type] = true;
    total += count;
    result.emplace_back(static_cast<std::uint16_t>(length), total);
  }
  if (!input.eof()) throw std::runtime_error("failed reading payload mix");
  if (result.empty()) throw std::invalid_argument("empty payload mix");
  return result;
}

class ValidationFailure : public std::runtime_error {
public:
  using std::runtime_error::runtime_error;
};
inline std::string_view execution_failure_status(const std::exception& error) {
  return dynamic_cast<const ValidationFailure*>(&error) ? "validation_failure" : "runtime_error";
}
template <class Result>
inline void verify_replay(const Result &timed, const Result &untimed) {
  if (timed.sink != untimed.sink || timed.count != untimed.count ||
      timed.bytes != untimed.bytes || timed.status != untimed.status ||
      timed.error != untimed.error || timed.checkpoint != untimed.checkpoint ||
      timed.work != untimed.work)
    throw ValidationFailure("timed/untimed replay mismatch");
}
inline std::string json(std::string_view value) {
  std::string result{"\""};
  constexpr auto hex = "0123456789abcdef";
  for (const auto character : value) {
    const auto byte = static_cast<unsigned char>(character);
    if (byte == '"' || byte == '\\') {
      result += '\\';
      result += character;
    } else if (byte < 32) {
      result += "\\u00";
      result += hex[byte >> 4];
      result += hex[byte & 15];
    } else
      result += character;
  }
  return result + '"';
}

// Independent project implementation of FIPS 180-4 (2015), §§4.1.2,
// 4.2.2, 5.1.1, 5.2.1, 5.3.3 and 6.2. No reference code copied.
// Used only outside measured replay intervals. Not a cryptographic product.
class Sha256 {
public:
  void update(std::span<const std::byte> input) {
    if (input.size() > (std::numeric_limits<std::uint64_t>::max() / 8) - bytes_)
      throw std::length_error("SHA256 bit length exceeds u64");
    bytes_ += input.size();
    while (!input.empty()) {
      const auto count = std::min(input.size(), block_.size() - used_);
      std::copy_n(input.begin(), count,
                  block_.begin() + static_cast<std::ptrdiff_t>(used_));
      input = input.subspan(count);
      used_ += count;
      if (used_ == 64) {
        compress();
        used_ = 0;
      }
    }
  }
  void little_u64(std::uint64_t value) {
    std::array<std::byte, 8> bytes{};
    for (auto &byte : bytes) {
      byte = static_cast<std::byte>(value & 255);
      value >>= 8;
    }
    update(bytes);
  }
  [[nodiscard]] std::string hex() const {
    auto copy = *this;
    const auto bits = bytes_ * 8;
    copy.block_[copy.used_++] = std::byte{0x80};
    if (copy.used_ > 56) {
      std::fill(copy.block_.begin() + static_cast<std::ptrdiff_t>(copy.used_),
                copy.block_.end(), std::byte{});
      copy.compress();
      copy.used_ = 0;
    }
    std::fill(copy.block_.begin() + static_cast<std::ptrdiff_t>(copy.used_),
              copy.block_.begin() + 56, std::byte{});
    for (unsigned i = 0; i < 8; ++i)
      copy.block_[63 - i] = static_cast<std::byte>((bits >> (i * 8)) & 255);
    copy.compress();
    constexpr auto digits = "0123456789abcdef";
    std::string result;
    result.reserve(64);
    for (const auto word : copy.state_)
      for (int shift = 28; shift >= 0; shift -= 4)
        result += digits[(word >> shift) & 15];
    return result;
  }

private:
  void compress() {
    constexpr std::array<std::uint32_t, 64> constants{
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
        0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
        0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
        0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
        0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
        0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
        0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
        0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
    std::array<std::uint32_t, 64> schedule{};
    for (std::size_t i = 0; i < 16; ++i)
      for (std::size_t j = 0; j < 4; ++j)
        schedule[i] = (schedule[i] << 8) |
                      std::to_integer<std::uint32_t>(block_[4 * i + j]);
    for (std::size_t i = 16; i < 64; ++i) {
      const auto x = schedule[i - 15], y = schedule[i - 2];
      schedule[i] =
          schedule[i - 16] + (std::rotr(x, 7) ^ std::rotr(x, 18) ^ (x >> 3)) +
          schedule[i - 7] + (std::rotr(y, 17) ^ std::rotr(y, 19) ^ (y >> 10));
    }
    auto a = state_[0], b = state_[1], c = state_[2], d = state_[3];
    auto e = state_[4], f = state_[5], g = state_[6], h = state_[7];
    for (std::size_t i = 0; i < 64; ++i) {
      const auto first =
          h + (std::rotr(e, 6) ^ std::rotr(e, 11) ^ std::rotr(e, 25)) +
          ((e & f) ^ (~e & g)) + constants[i] + schedule[i];
      const auto second =
          (std::rotr(a, 2) ^ std::rotr(a, 13) ^ std::rotr(a, 22)) +
          ((a & b) ^ (a & c) ^ (b & c));
      h = g;
      g = f;
      f = e;
      e = d + first;
      d = c;
      c = b;
      b = a;
      a = first + second;
    }
    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
    state_[5] += f;
    state_[6] += g;
    state_[7] += h;
  }
  std::array<std::uint32_t, 8> state_{0x6a09e667, 0xbb67ae85, 0x3c6ef372,
                                      0xa54ff53a, 0x510e527f, 0x9b05688c,
                                      0x1f83d9ab, 0x5be0cd19};
  std::array<std::byte, 64> block_{};
  std::size_t used_{};
  std::uint64_t bytes_{};
};

inline constexpr std::uint64_t fnv_basis = 14695981039346656037ULL;
inline void sink_byte(std::uint64_t &state, std::byte byte) {
  state ^= std::to_integer<unsigned char>(byte);
  state *= 1099511628211ULL;
}
inline void sink_delivery(std::uint64_t &state, const Delivered &record) {
  auto seq = record.seq;
  for (unsigned i = 0; i < 8; ++i) {
    sink_byte(state, static_cast<std::byte>(seq & 255));
    seq >>= 8;
  }
  for (const auto byte : record.payload)
    sink_byte(state, byte);
}

// The two implementations use this written integer contract, not shared code.
struct Random {
  std::uint64_t state;
  std::uint64_t next() {
    auto value = (state += 0x9e3779b97f4a7c15ULL);
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
  }
  std::uint64_t bounded(std::uint64_t bound) {
    if (bound == 0)
      throw std::invalid_argument("zero RNG bound");
    const auto threshold = (-bound) % bound;
    for (;;) {
      const auto value = next();
      if (value >= threshold)
        return value % bound;
    }
  }
};
} // namespace tiplog::bench
