// Audit: trace v1 reader and ITCH BinaryFILE walker robustness. Mutation
// fuzzing here is deterministic and runs in every preset (the libFuzzer
// targets only replay their saved corpus inside CTest).
#include "tiplog/trace/itch_walker.hpp"
#include "tiplog/trace/reader.hpp"

#include <gtest/gtest.h>

#include <random>
#include <string>
#include <vector>

namespace tiplog::trace {
namespace {

void put(std::vector<std::byte>& out, std::uint64_t value, int bytes) {
  for (int i = 0; i < bytes; ++i) out.push_back(static_cast<std::byte>((value >> (8 * i)) & 0xff));
}

struct Built {
  std::vector<std::byte> bytes;
  std::vector<std::vector<std::byte>> payloads;
  std::vector<std::uint32_t> ids;
};

// Independent writer for trace v1 (ARCHITECTURE 5.0).
Built build_trace(std::mt19937_64& random) {
  Built b;
  const auto topics = 1 + random() % 6;
  const auto records = random() % 40;
  b.bytes.resize(64);
  for (std::uint64_t r = 0; r < records; ++r) {
    const auto id = static_cast<std::uint32_t>(1 + random() % topics);
    std::vector<std::byte> payload(random() % 80);
    for (auto& x : payload) x = static_cast<std::byte>(random());
    put(b.bytes, id, 4);
    put(b.bytes, payload.size(), 2);
    put(b.bytes, 0, 2);
    put(b.bytes, random(), 8);
    b.bytes.insert(b.bytes.end(), payload.begin(), payload.end());
    while (b.bytes.size() % 8) b.bytes.push_back(std::byte{0});
    b.payloads.push_back(payload);
    b.ids.push_back(id);
  }
  const auto dict_offset = b.bytes.size();
  put(b.bytes, topics, 4);
  for (std::uint64_t t = 1; t <= topics; ++t) {
    const std::string path = "t/" + std::to_string(t) + "/x";
    put(b.bytes, t, 4);
    put(b.bytes, path.size(), 2);
    for (const char c : path) b.bytes.push_back(static_cast<std::byte>(c));
  }
  const char magic[8] = {'T', 'P', 'L', 'T', 'R', 'C', 0, 1};
  for (int i = 0; i < 8; ++i) b.bytes[i] = static_cast<std::byte>(magic[i]);
  std::vector<std::byte> header;
  put(header, 1, 4);
  put(header, 0, 4);
  put(header, records, 8);
  put(header, dict_offset, 8);
  put(header, b.bytes.size() - dict_offset, 8);
  put(header, 0x1122334455667788ULL, 8);
  std::copy(header.begin(), header.end(), b.bytes.begin() + 8);
  return b;
}

TEST(AuditTrace, ValidRoundTrip) {
  for (std::uint64_t seed = 1; seed <= 500; ++seed) {
    std::mt19937_64 random(seed);
    const auto built = build_trace(random);
    const Reader reader{std::span<const std::byte>(built.bytes)};
    std::size_t i = 0;
    reader.for_each([&](const Record& r) {
      ASSERT_LT(i, built.payloads.size());
      EXPECT_EQ(r.topic_id, built.ids[i]);
      EXPECT_TRUE(std::ranges::equal(r.payload, built.payloads[i]));
      ++i;
    });
    EXPECT_EQ(i, built.payloads.size());
  }
}

// Every mutated file must either validate and iterate completely, or throw
// FormatError; no other exception type, crash or sanitizer report.
TEST(AuditTrace, MutatedTracesFailOnlyWithFormatError) {
  std::uint64_t accepted = 0, rejected = 0;
  for (std::uint64_t seed = 1; seed <= 20000; ++seed) {
    std::mt19937_64 random(seed);
    auto bytes = build_trace(random).bytes;
    const auto mutations = 1 + random() % 4;
    for (std::uint64_t m = 0; m < mutations; ++m) {
      switch (random() % 4) {
        case 0: bytes[random() % bytes.size()] = static_cast<std::byte>(random()); break;
        case 1: bytes.resize(random() % (bytes.size() + 1)); break;
        case 2: bytes.insert(bytes.begin() + static_cast<std::ptrdiff_t>(random() % (bytes.size() + 1)),
                             static_cast<std::byte>(random())); break;
        default: if (bytes.size() > 24) bytes[16 + random() % 8] = static_cast<std::byte>(random());
      }
      if (bytes.empty()) break;
    }
    try {
      const Reader reader{std::span<const std::byte>(bytes)};
      std::uint64_t n = 0;
      reader.for_each([&](const Record&) { ++n; });
      EXPECT_EQ(n, reader.header().record_count);
      ++accepted;
    } catch (const FormatError&) {
      ++rejected;
    } catch (const std::exception& e) {
      FAIL() << "seed " << seed << ": non-FormatError exception: " << e.what();
    }
  }
  std::cout << "[audit] mutated traces accepted=" << accepted << " rejected=" << rejected << "\n";
  EXPECT_GT(rejected, 1000U);
}

std::vector<std::byte> itch_stream(std::mt19937_64& random, std::vector<unsigned char>* types) {
  const std::string kinds = "SRHYLVWKJhAFECXDUPQBINO";
  std::vector<std::byte> out;
  const auto count = random() % 60;
  for (std::uint64_t i = 0; i < count; ++i) {
    const auto kind = static_cast<unsigned char>(kinds[random() % kinds.size()]);
    const auto length = itch_message_size(kind);
    out.push_back(static_cast<std::byte>(length >> 8));
    out.push_back(static_cast<std::byte>(length & 0xff));
    out.push_back(static_cast<std::byte>(kind));
    for (std::uint16_t j = 1; j < length; ++j) out.push_back(static_cast<std::byte>(random()));
    types->push_back(kind);
  }
  return out;
}

// Chunking must not change results: feeding any split yields identical counts.
TEST(AuditTrace, ItchWalkerIsChunkInvariant) {
  for (std::uint64_t seed = 1; seed <= 2000; ++seed) {
    std::mt19937_64 random(seed);
    std::vector<unsigned char> types;
    const auto stream = itch_stream(random, &types);
    ItchWalker whole;
    whole.feed(stream);
    whole.finish();
    ItchWalker pieces;
    std::size_t offset = 0;
    while (offset < stream.size()) {
      const auto n = std::min<std::size_t>(stream.size() - offset, 1 + random() % 7);
      pieces.feed(std::span<const std::byte>(stream).subspan(offset, n));
      offset += n;
    }
    pieces.finish();
    ASSERT_EQ(whole.message_count(), types.size());
    ASSERT_EQ(pieces.message_count(), whole.message_count());
    ASSERT_EQ(pieces.payload_bytes(), whole.payload_bytes());
    for (std::size_t t = 0; t < 256; ++t) ASSERT_EQ(pieces.by_type()[t].count, whole.by_type()[t].count);
    // Every strict prefix that cuts a frame must fail finish().
    if (!stream.empty()) {
      ItchWalker truncated;
      truncated.feed(std::span<const std::byte>(stream).first(stream.size() - 1));
      EXPECT_THROW(truncated.finish(), FormatError);
    }
  }
}

}  // namespace
}  // namespace tiplog::trace
