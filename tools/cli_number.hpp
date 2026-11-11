#pragma once

#include <charconv>
#include <cstdint>
#include <stdexcept>
#include <string_view>
#include <system_error>

namespace tiplog::cli {
inline std::uint64_t parse_u64(std::string_view text) {
  std::uint64_t value{};
  const auto end = text.data() + text.size();
  const auto parsed = std::from_chars(text.data(), end, value);
  if (parsed.ec != std::errc{} || parsed.ptr != end)
    throw std::invalid_argument("expected unsigned decimal integer");
  return value;
}
}  // namespace tiplog::cli
