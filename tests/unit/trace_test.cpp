#include "tiplog/trace/itch_walker.hpp"
#include "tiplog/trace/reader.hpp"
#include "tiplog/types.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <filesystem>
#include <fstream>
#include <limits>
#include <memory>
#include <sstream>
#include <utility>
#include <vector>

namespace {
using Bytes = std::vector<std::byte>;
using tiplog::trace::FormatError;
using tiplog::trace::Reader;

void set_le(Bytes& bytes, std::size_t at, std::uint64_t value, std::size_t width) {
  for (std::size_t i = 0; i < width; ++i) {
    bytes.at(at + i) = static_cast<std::byte>(value & 255U);
    value >>= 8U;
  }
}
void append_le(Bytes& bytes, std::uint64_t value, std::size_t width) {
  const auto at = bytes.size();
  bytes.resize(at + width);
  set_le(bytes, at, value, width);
}
void append_string(Bytes& bytes, std::string_view value) {
  for (const auto c : value) bytes.push_back(static_cast<std::byte>(c));
}

// Test-only encoder follows the saved wire layout, not the production parser.
Bytes trace(std::vector<std::pair<std::uint32_t, Bytes>> records = {{1, {std::byte{42}}}},
            std::vector<std::pair<std::uint32_t, std::string>> topics = {{1, "itch/A/add/A"}}) {
  Bytes bytes(64);
  constexpr std::array<unsigned char, 8> magic{'T', 'P', 'L', 'T', 'R', 'C', 0, 1};
  for (std::size_t i = 0; i < magic.size(); ++i) bytes[i] = static_cast<std::byte>(magic[i]);
  set_le(bytes, 8, 1, 4);
  set_le(bytes, 16, records.size(), 8);
  for (const auto& [id, payload] : records) {
    append_le(bytes, id, 4);
    append_le(bytes, payload.size(), 2);
    append_le(bytes, 0, 2);
    append_le(bytes, 1234567890123ULL, 8);
    bytes.insert(bytes.end(), payload.begin(), payload.end());
    while (bytes.size() % 8 != 0) bytes.push_back(std::byte{});
  }
  set_le(bytes, 24, bytes.size(), 8);
  const auto dict_start = bytes.size();
  append_le(bytes, topics.size(), 4);
  for (const auto& [id, path] : topics) {
    append_le(bytes, id, 4);
    append_le(bytes, path.size(), 2);
    append_string(bytes, path);
  }
  set_le(bytes, 32, bytes.size() - dict_start, 8);
  return bytes;
}

TEST(TraceV05, GoldenHeaderDictionaryAndRecord) {
  const auto bytes = trace();
  const Reader reader(bytes);
  ASSERT_EQ(reader.header().record_count, 1U);
  ASSERT_EQ(reader.dictionary().size(), 1U);
  EXPECT_EQ(reader.topic_path(1), "itch/A/add/A");
  Reader::Cursor cursor;
  tiplog::trace::Record record;
  ASSERT_TRUE(reader.next(cursor, record));
  EXPECT_EQ(record.topic_id, 1U);
  EXPECT_EQ(record.ts_ns, 1234567890123ULL);
  ASSERT_EQ(record.payload.size(), 1U);
  EXPECT_EQ(record.payload[0], std::byte{42});
  EXPECT_FALSE(reader.next(cursor, record));
  EXPECT_FALSE(reader.next(cursor, record));
}

TEST(TraceV05, EmptyAndMaximumPayloadAndMultipleTopics) {
  const auto empty = trace({}, {});
  EXPECT_EQ(Reader(empty).header().record_count, 0U);
  const Bytes big(65535, std::byte{0xfe});
  const auto bytes = trace({{9, {}}, {7, big}, {9, {std::byte{1}, std::byte{2}}}},
                           {{9, "a/b"}, {7, "a/c"}});
  const Reader reader(bytes);
  std::vector<std::size_t> sizes;
  reader.for_each([&](const auto& record) { sizes.push_back(record.payload.size()); });
  EXPECT_EQ(sizes, (std::vector<std::size_t>{0, 65535, 2}));
}

TEST(TraceV05, EveryTruncationRejected) {
  const auto bytes = trace();
  for (std::size_t size = 0; size < bytes.size(); ++size) {
    SCOPED_TRACE(size);
    EXPECT_THROW(Reader{std::span<const std::byte>(bytes).first(size)}, FormatError);
  }
}

TEST(TraceV05, HeaderFlagsReservedVersionAndMagicRejected) {
  for (const std::size_t at : {0U, 6U, 7U, 8U, 12U, 15U, 48U, 63U}) {
    auto bytes = trace();
    bytes[at] ^= std::byte{8};
    EXPECT_THROW(Reader{bytes}, FormatError) << at;
  }
}

TEST(TraceV05, DictionaryOffsetLengthOverflowAlignmentAndCountRejected) {
  for (const auto value : {0ULL, 63ULL, 65ULL, 80ULL, std::numeric_limits<unsigned long long>::max()}) {
    auto bytes = trace();
    set_le(bytes, 24, value, 8);
    EXPECT_THROW(Reader{bytes}, FormatError) << value;
  }
  for (const auto value : {0ULL, 1ULL, 999ULL, std::numeric_limits<unsigned long long>::max()}) {
    auto bytes = trace();
    set_le(bytes, 32, value, 8);
    EXPECT_THROW(Reader{bytes}, FormatError) << value;
  }
  auto bytes = trace();
  set_le(bytes, 88, 0xffffffff, 4);
  EXPECT_THROW(Reader{bytes}, FormatError);
}

TEST(TraceV05, ExactRecordCountAndDictionaryBoundaryRequired) {
  for (const auto count : {0ULL, 2ULL, std::numeric_limits<unsigned long long>::max()}) {
    auto bytes = trace();
    set_le(bytes, 16, count, 8);
    EXPECT_THROW(Reader{bytes}, FormatError);
  }
  auto bytes = trace();
  set_le(bytes, 68, 65535, 2);
  EXPECT_THROW(Reader{bytes}, FormatError);
}

TEST(TraceV05, MissingIdsZeroIdsDuplicateIdsAndPathsRejected) {
  const auto missing = trace({{2, {}}});
  EXPECT_THROW(Reader{missing}, FormatError);
  const auto zero = trace({{0, {}}}, {{0, "a"}});
  EXPECT_THROW(Reader{zero}, FormatError);
  const auto duplicate_id = trace({{1, {}}}, {{1, "a"}, {1, "b"}});
  EXPECT_THROW(Reader{duplicate_id}, FormatError);
  const auto duplicate_path = trace({{1, {}}}, {{1, "a"}, {2, "a"}});
  EXPECT_THROW(Reader{duplicate_path}, FormatError);
}

TEST(TraceV05, CanonicalUtf8PathsRequired) {
  for (const std::string& path : std::vector<std::string>{"", "/a", "a/", "a//b", std::string("a\0b", 3),
                                 std::string("\xc0\xaf", 2), std::string("\xed\xa0\x80", 3),
                                 std::string("\xf4\x90\x80\x80", 4), std::string("\xc2", 1)}) {
    const auto bytes = trace({{1, {}}}, {{1, path}});
    EXPECT_THROW(Reader{bytes}, FormatError);
  }
  const auto valid = trace({{1, {}}}, {{1, "a/\xc3\xa9"}});
  EXPECT_NO_THROW(Reader{valid});
}

TEST(TraceV05, TopicResourceBoundariesMatchRegistryContract) {
  const auto allowed = trace({}, {{1, std::string(tiplog::max_topic_path_bytes, 'a')}});
  EXPECT_NO_THROW(Reader{allowed});
  const auto oversized = trace({}, {{1, std::string(tiplog::max_topic_path_bytes + 1, 'a')}});
  EXPECT_THROW(Reader{oversized}, FormatError);
  std::string path = "a";
  for (std::size_t depth = 1; depth < tiplog::max_topic_depth; ++depth) path += "/a";
  const auto deepest = trace({}, {{1, path}});
  EXPECT_NO_THROW(Reader{deepest});
  path += "/a";
  const auto too_deep = trace({}, {{1, path}});
  EXPECT_THROW(Reader{too_deep}, FormatError);
}

TEST(TraceV05, FlagsPaddingAndTrailingBytesRejected) {
  for (const std::size_t at : {70U, 71U, 81U, 87U}) {
    auto bytes = trace();
    bytes[at] = std::byte{1};
    EXPECT_THROW(Reader{bytes}, FormatError);
  }
  auto bytes = trace();
  bytes.push_back(std::byte{});
  EXPECT_THROW(Reader{bytes}, FormatError);
  set_le(bytes, 32, bytes.size() - 88, 8);
  EXPECT_THROW(Reader{bytes}, FormatError);
}

TEST(TraceV05, FileMappingMoveAndRewind) {
  const auto bytes = trace();
  const auto path = std::filesystem::temp_directory_path() /
      ("tiplog-trace-" + std::to_string(reinterpret_cast<std::uintptr_t>(&bytes)) + ".mdt");
  {
    std::ofstream out(path, std::ios::binary);
    out.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
  }
  {
    Reader first(path);
    Reader second(std::move(first));
    Reader third(bytes);
    third = std::move(second);
    EXPECT_EQ(third.topic_path(1), "itch/A/add/A");
    for (int i = 0; i < 2; ++i) {
      std::size_t count = 0;
      third.for_each([&](const auto&) { ++count; });
      EXPECT_EQ(count, 1U);
    }
  }
  EXPECT_TRUE(std::filesystem::remove(path));
  EXPECT_THROW(Reader{path}, std::system_error);
}

Bytes frame(unsigned char type, std::uint16_t size, std::uint16_t locate = 1,
            std::uint64_t timestamp = 1) {
  Bytes bytes(static_cast<std::size_t>(size) + 2);
  bytes[0] = static_cast<std::byte>(size >> 8U);
  bytes[1] = static_cast<std::byte>(size & 255U);
  bytes[2] = static_cast<std::byte>(type);
  if (size >= 3) {
    bytes[3] = static_cast<std::byte>(locate >> 8U);
    bytes[4] = static_cast<std::byte>(locate & 255U);
  }
  if (size >= 11) {
    for (std::size_t i = 0; i < 6; ++i) {
      bytes[12 - i] = static_cast<std::byte>(timestamp & 255U);
      timestamp >>= 8U;
    }
  }
  return bytes;
}

TEST(ItchWalkerV04, IndependentAll23TypesAndChunkBoundaries) {
  const std::vector<std::pair<unsigned char, std::uint16_t>> lengths{
      {'S', 12}, {'R', 39}, {'H', 25}, {'Y', 20}, {'L', 26}, {'V', 35}, {'W', 12},
      {'K', 28}, {'J', 35}, {'h', 21}, {'A', 36}, {'F', 40}, {'E', 31}, {'C', 36},
      {'X', 23}, {'D', 19}, {'U', 35}, {'P', 44}, {'Q', 40}, {'B', 19}, {'I', 50},
      {'N', 20}, {'O', 48}};
  Bytes bytes;
  std::uint64_t expected_payload = 0;
  for (const auto& [type, length] : lengths) {
    auto message = frame(type, length, 65535);
    bytes.insert(bytes.end(), message.begin(), message.end());
    expected_payload += length;
  }
  bytes.push_back(std::byte{});
  bytes.push_back(std::byte{});
  for (const std::size_t chunk_size : {1U, 2U, 3U, 11U, 49U, 1024U}) {
    auto walker = std::make_unique<tiplog::trace::ItchWalker>();
    for (std::size_t at = 0; at < bytes.size(); at += chunk_size)
      walker->feed(std::span<const std::byte>(bytes).subspan(at, std::min(chunk_size, bytes.size() - at)));
    EXPECT_NO_THROW(walker->finish());
    EXPECT_TRUE(walker->terminated());
    EXPECT_EQ(walker->message_count(), 23U);
    EXPECT_EQ(walker->payload_bytes(), expected_payload);
    EXPECT_EQ(walker->total_uncompressed_bytes(), expected_payload + 46 + 2);
    EXPECT_EQ(walker->by_locate()[65535].count, 23U);
    for (const auto& [type, length] : lengths) {
      EXPECT_EQ(walker->by_type()[type].count, 1U);
      EXPECT_EQ(walker->by_type()[type].payload_bytes, length);
    }
  }
}

TEST(ItchWalkerV04, IncompleteAllowedButPartialAndTrailingRejected) {
  auto walker = std::make_unique<tiplog::trace::ItchWalker>();
  walker->feed(frame('S', 12));
  EXPECT_NO_THROW(walker->finish());
  EXPECT_FALSE(walker->terminated());
  const auto complete = frame('A', 36);
  for (std::size_t size = 1; size < complete.size(); ++size) {
    auto partial = std::make_unique<tiplog::trace::ItchWalker>();
    partial->feed(std::span<const std::byte>(complete).first(size));
    EXPECT_THROW(partial->finish(), FormatError);
  }
  const Bytes bad_terminator{std::byte{}, std::byte{}, std::byte{1}};
  auto trailing = std::make_unique<tiplog::trace::ItchWalker>();
  EXPECT_THROW(trailing->feed(bad_terminator), FormatError);
}

TEST(ItchWalkerV04, UnknownTypeWrongLengthAndOversizeRejected) {
  for (const auto& bytes : {frame('?', 12), frame('S', 11), frame('S', 13), frame('A', 51)}) {
    auto walker = std::make_unique<tiplog::trace::ItchWalker>();
    EXPECT_THROW(walker->feed(bytes), FormatError);
  }
}

TEST(ItchWalkerV04, TimestampInversionsAndJson) {
  auto walker = std::make_unique<tiplog::trace::ItchWalker>();
  walker->feed(frame('S', 12, 0, 100));
  walker->feed(frame('S', 12, 0, 100));
  walker->feed(frame('S', 12, 0, 99));
  walker->feed(frame('D', 19, 256, 200));
  EXPECT_EQ(walker->timestamp_inversions(), 1U);
  EXPECT_EQ(walker->by_locate()[0].count, 3U);
  EXPECT_EQ(walker->by_locate()[256].count, 1U);
  std::ostringstream output;
  walker->write_json(output);
  EXPECT_NE(output.str().find("\"incomplete\": true"), std::string::npos);
  EXPECT_NE(output.str().find("\"256\":{\"count\":1"), std::string::npos);
}
TEST(ItchWalkerV04, ErrorsIdentifyFrameByteOffsetIndependentOfChunking) {
  const auto prefix = frame('S', 12);
  const std::vector<Bytes> invalid{frame('?', 12), frame('S', 11), frame('A', 51),
                                 Bytes{std::byte{0}},
                                 Bytes{std::byte{0}, std::byte{12}, std::byte{'S'}}};
  for (const auto& suffix : invalid) {
    Bytes input(prefix);
    input.insert(input.end(), suffix.begin(), suffix.end());
    for (const std::size_t chunk : {1U, 2U, 7U, 1024U}) {
      auto walker = std::make_unique<tiplog::trace::ItchWalker>();
      try {
        for (std::size_t at = 0; at < input.size(); at += chunk)
          walker->feed(std::span<const std::byte>(input).subspan(at, std::min(chunk, input.size() - at)));
        walker->finish();
        FAIL() << "invalid frame accepted";
      } catch (const FormatError& error) {
        EXPECT_NE(std::string(error.what()).find("byte offset 14"), std::string::npos);
      }
    }
  }
  auto walker = std::make_unique<tiplog::trace::ItchWalker>();
  walker->feed(prefix);
  const Bytes trailing{std::byte{0}, std::byte{0}, std::byte{1}};
  try { walker->feed(trailing); FAIL(); }
  catch (const FormatError& error) {
    EXPECT_NE(std::string(error.what()).find("byte offset 16"), std::string::npos);
  }
}

}  // namespace
