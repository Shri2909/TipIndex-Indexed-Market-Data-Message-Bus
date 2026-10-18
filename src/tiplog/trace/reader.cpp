#include "tiplog/trace/reader.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstring>
#include <limits>
#include <system_error>
#include <unordered_set>
#include <utility>

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace tiplog::trace {
namespace {

std::uint64_t little(std::span<const std::byte> bytes, std::size_t offset,
                     std::size_t length) {
  if (offset > bytes.size() || length > bytes.size() - offset)
    throw FormatError("truncated integer");
  std::uint64_t value = 0;
  for (std::size_t i = 0; i < length; ++i)
    value |= std::uint64_t{std::to_integer<unsigned char>(bytes[offset + i])} << (i * 8U);
  return value;
}

bool zeros(std::span<const std::byte> bytes) {
  return std::all_of(bytes.begin(), bytes.end(), [](std::byte b) { return b == std::byte{}; });
}

bool canonical_utf8_path(std::string_view path) {
  if (path.empty() || path.front() == '/' || path.back() == '/') return false;
  bool slash = false;
  for (std::size_t i = 0; i < path.size();) {
    const auto first = static_cast<unsigned char>(path[i]);
    if (first == 0 || (first == '/' && slash)) return false;
    slash = first == '/';
    if (first < 0x80U) { ++i; continue; }
    std::size_t width = 0;
    std::uint32_t cp = 0;
    std::uint32_t minimum = 0;
    if (first >= 0xc2U && first <= 0xdfU) { width = 2; cp = first & 0x1fU; minimum = 0x80U; }
    else if (first >= 0xe0U && first <= 0xefU) { width = 3; cp = first & 0x0fU; minimum = 0x800U; }
    else if (first >= 0xf0U && first <= 0xf4U) { width = 4; cp = first & 0x07U; minimum = 0x10000U; }
    else return false;
    if (width > path.size() - i) return false;
    for (std::size_t j = 1; j < width; ++j) {
      const auto b = static_cast<unsigned char>(path[i + j]);
      if ((b & 0xc0U) != 0x80U) return false;
      cp = (cp << 6U) | (b & 0x3fU);
    }
    if (cp < minimum || cp > 0x10ffffU || (cp >= 0xd800U && cp <= 0xdfffU)) return false;
    i += width;
  }
  return true;
}

}  // namespace

Reader::Reader(const std::filesystem::path& path) {
  const int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
  if (fd < 0) throw std::system_error(errno, std::generic_category(), "open trace");
  struct stat status {};
  if (::fstat(fd, &status) != 0) {
    const int error = errno;
    ::close(fd);
    throw std::system_error(error, std::generic_category(), "stat trace");
  }
  if (status.st_size <= 0 || static_cast<std::uintmax_t>(status.st_size) >
                                  std::numeric_limits<std::size_t>::max()) {
    ::close(fd);
    throw FormatError("empty or unaddressable trace");
  }
  mapping_size_ = static_cast<std::size_t>(status.st_size);
  mapping_ = ::mmap(nullptr, mapping_size_, PROT_READ, MAP_PRIVATE, fd, 0);
  const int map_error = errno;
  ::close(fd);
  if (mapping_ == MAP_FAILED) {
    mapping_ = nullptr;
    throw std::system_error(map_error, std::generic_category(), "mmap trace");
  }
  bytes_ = {static_cast<const std::byte*>(mapping_), mapping_size_};
  try { validate(); } catch (...) { unmap(); throw; }
}

Reader::Reader(std::span<const std::byte> bytes) : bytes_(bytes) { validate(); }
Reader::~Reader() { unmap(); }
void Reader::unmap() noexcept {
  if (mapping_ != nullptr) ::munmap(mapping_, mapping_size_);
  mapping_ = nullptr;
  mapping_size_ = 0;
}

Reader::Reader(Reader&& other) noexcept
    : bytes_(other.bytes_), mapping_(std::exchange(other.mapping_, nullptr)),
      mapping_size_(std::exchange(other.mapping_size_, 0)), header_(other.header_),
      topics_(std::move(other.topics_)), topic_index_(std::move(other.topic_index_)) {
  other.bytes_ = {};
}
Reader& Reader::operator=(Reader&& other) noexcept {
  if (this != &other) {
    unmap();
    bytes_ = other.bytes_;
    mapping_ = std::exchange(other.mapping_, nullptr);
    mapping_size_ = std::exchange(other.mapping_size_, 0);
    header_ = other.header_;
    topics_ = std::move(other.topics_);
    topic_index_ = std::move(other.topic_index_);
    other.bytes_ = {};
  }
  return *this;
}

void Reader::validate() {
  constexpr std::array<std::byte, 8> magic{
      std::byte{'T'}, std::byte{'P'}, std::byte{'L'}, std::byte{'T'},
      std::byte{'R'}, std::byte{'C'}, std::byte{0}, std::byte{1}};
  if (bytes_.size() < 64 || !std::equal(magic.begin(), magic.end(), bytes_.begin()))
    throw FormatError("invalid trace magic or truncated header");
  if (little(bytes_, 8, 4) != 1) throw FormatError("unsupported trace version");
  if (little(bytes_, 12, 4) != 0 || !zeros(bytes_.subspan(48, 16)))
    throw FormatError("unsupported flags or nonzero reserved header");
  header_ = {little(bytes_, 16, 8), little(bytes_, 24, 8),
             little(bytes_, 32, 8), little(bytes_, 40, 8)};
  if (header_.dict_offset < 64 || header_.dict_offset > bytes_.size() ||
      header_.dict_offset % 8 != 0 ||
      header_.dict_length != bytes_.size() - header_.dict_offset ||
      header_.dict_length < 4)
    throw FormatError("invalid dictionary offset/length or trailing bytes");
  if (header_.record_count > (header_.dict_offset - 64) / 16)
    throw FormatError("record count cannot fit in record region");
  const auto dict_start = static_cast<std::size_t>(header_.dict_offset);
  const auto count = little(bytes_, dict_start, 4);
  if (count > (header_.dict_length - 4) / 7)
    throw FormatError("dictionary count cannot fit");
  std::size_t offset = dict_start + 4;
  std::unordered_set<std::string> paths;
  for (std::uint64_t i = 0; i < count; ++i) {
    if (offset > bytes_.size() || bytes_.size() - offset < 6)
      throw FormatError("truncated dictionary entry");
    const auto id = static_cast<std::uint32_t>(little(bytes_, offset, 4));
    const auto size = static_cast<std::size_t>(little(bytes_, offset + 4, 2));
    offset += 6;
    if (size > bytes_.size() - offset) throw FormatError("truncated dictionary path");
    std::string path(reinterpret_cast<const char*>(bytes_.data() + offset), size);
    offset += size;
    if (id == 0 || !canonical_utf8_path(path) || topic_index_.contains(id) || !paths.insert(path).second)
      throw FormatError("invalid or duplicate dictionary id/path");
    topic_index_.emplace(id, topics_.size());
    topics_.push_back({id, std::move(path)});
  }
  if (offset != bytes_.size()) throw FormatError("trailing dictionary bytes");
  Cursor cursor;
  Record record;
  while (next(cursor, record)) {}
}

const std::string& Reader::topic_path(std::uint32_t id) const {
  const auto found = topic_index_.find(id);
  if (found == topic_index_.end()) throw FormatError("missing dictionary topic");
  return topics_[found->second].path;
}

bool Reader::next(Cursor& cursor, Record& record) const {
  const auto end = static_cast<std::size_t>(header_.dict_offset);
  if (cursor.index > header_.record_count || cursor.offset < 64 ||
      cursor.offset > end || cursor.offset % 8 != 0)
    throw FormatError("invalid trace cursor");
  if (cursor.index == header_.record_count) {
    if (cursor.offset != end) throw FormatError("record count leaves trailing bytes");
    return false;
  }
  if (end - cursor.offset < 16) throw FormatError("truncated record header");
  const auto offset = cursor.offset;
  const auto id = static_cast<std::uint32_t>(little(bytes_, offset, 4));
  const auto length = static_cast<std::size_t>(little(bytes_, offset + 4, 2));
  const auto flags = static_cast<std::uint16_t>(little(bytes_, offset + 6, 2));
  if (flags != 0 || !topic_index_.contains(id)) throw FormatError("record flags or missing dictionary id");
  const std::size_t encoded = (16 + length + 7) & ~std::size_t{7};
  if (encoded > end - offset) throw FormatError("truncated record payload/padding");
  if (!zeros(bytes_.subspan(offset + 16 + length, encoded - 16 - length)))
    throw FormatError("nonzero record padding");
  record = {id, flags, little(bytes_, offset + 8, 8), bytes_.subspan(offset + 16, length)};
  cursor.offset += encoded;
  ++cursor.index;
  return true;
}

}  // namespace tiplog::trace
