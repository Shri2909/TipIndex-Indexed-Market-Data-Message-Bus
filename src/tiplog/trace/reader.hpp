#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <span>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace tiplog::trace {

class FormatError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

struct Header {
  std::uint64_t record_count{};
  std::uint64_t dict_offset{};
  std::uint64_t dict_length{};
  std::uint64_t source_sha256_prefix{};
};

struct Topic {
  std::uint32_t id{};
  std::string path;
};

struct Record {
  std::uint32_t topic_id{};
  std::uint16_t flags{};
  std::uint64_t ts_ns{};
  std::span<const std::byte> payload;
};

// Validates the complete immutable file on construction. The filesystem overload
// owns a read-only mapping; the span overload borrows bytes for unit/fuzz tests.
// Records borrow that storage and remain valid until Reader destruction.
class Reader {
 public:
  struct Cursor {
    std::size_t offset{64};
    std::uint64_t index{};
  };

  explicit Reader(const std::filesystem::path& path);
  explicit Reader(std::span<const std::byte> bytes);
  ~Reader();
  Reader(const Reader&) = delete;
  Reader& operator=(const Reader&) = delete;
  Reader(Reader&& other) noexcept;
  Reader& operator=(Reader&& other) noexcept;

  [[nodiscard]] const Header& header() const noexcept { return header_; }
  [[nodiscard]] const std::vector<Topic>& dictionary() const noexcept { return topics_; }
  [[nodiscard]] const std::string& topic_path(std::uint32_t id) const;
  [[nodiscard]] bool next(Cursor& cursor, Record& record) const;
  template <class Callback>
  void for_each(Callback&& callback) const {
    Cursor cursor;
    Record record;
    while (next(cursor, record)) callback(record);
  }

 private:
  void validate();
  void unmap() noexcept;
  std::span<const std::byte> bytes_;
  void* mapping_{};
  std::size_t mapping_size_{};
  Header header_;
  std::vector<Topic> topics_;
  std::unordered_map<std::uint32_t, std::size_t> topic_index_;
};

}  // namespace tiplog::trace
