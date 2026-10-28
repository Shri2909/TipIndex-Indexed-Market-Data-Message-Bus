// Original diagnostic; mallinfo2 field meanings: glibc manual §3.2.3.10.
// This measures a declared single-thread process allocation boundary, not RSS
// or universally exact per-object allocator headers. See results/p4/memory-sources.md.
#include "tiplog/index/index.hpp"

#include <algorithm>
#include <bit>
#include <charconv>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <memory>
#include <string_view>
#include <utility>
#include <variant>

#if defined(__has_feature)
# if __has_feature(address_sanitizer)
#  define TIPLOG_MEMORY_ASAN 1
# endif
#endif
#if defined(__GLIBC__) && !defined(__SANITIZE_ADDRESS__) && !defined(TIPLOG_MEMORY_ASAN)
#include <gnu/libc-version.h>
#include <malloc.h>

namespace {
std::uint64_t parse(std::string_view text) {
  std::uint64_t value{};
  const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value);
  if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size())
    throw std::invalid_argument("unsigned integer required");
  return value;
}
void print_info(const char* name, const struct mallinfo2& info) {
  std::printf("\"%s\":{\"arena\":%zu,\"ordblks\":%zu,\"smblks\":%zu,"
      "\"hblks\":%zu,\"hblkhd\":%zu,\"usmblks\":%zu,\"fsmblks\":%zu,"
      "\"uordblks\":%zu,\"fordblks\":%zu,\"keepcost\":%zu}", name,
      info.arena, info.ordblks, info.smblks, info.hblks, info.hblkhd,
      info.usmblks, info.fsmblks, info.uordblks, info.fordblks, info.keepcost);
}
std::int64_t difference(std::uint64_t after, std::uint64_t before) {
  const auto limit = static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max());
  if (after > limit || before > limit) throw std::overflow_error("diagnostic delta limit");
  return static_cast<std::int64_t>(after) - static_cast<std::int64_t>(before);
}
std::uint64_t sum(std::uint64_t left, std::uint64_t right) {
  if (right > std::numeric_limits<std::uint64_t>::max() - left)
    throw std::overflow_error("diagnostic sum limit");
  return left + right;
}
}  // namespace

int main(int argc, char** argv) {
  try {
    std::uint64_t capacity = 1U << 20U, publications = 100000, partitions = 100, entries = 256;
    for (int i = 1; i < argc; i += 2) {
      if (i + 1 == argc) throw std::invalid_argument("option requires value");
      const std::string_view option(argv[i]);
      const auto value = parse(argv[i + 1]);
      if (option == "--ring-bytes") capacity = value;
      else if (option == "--publications") publications = value;
      else if (option == "--partitions") partitions = value;
      else if (option == "--block-entries") entries = value;
      else throw std::invalid_argument("unknown option");
    }
    if (capacity < 64 || !std::has_single_bit(capacity) || capacity > (1ULL << 31U) ||
        publications == 0 || publications >= (1ULL << 40U) || partitions == 0 ||
        partitions >= tiplog::index::none || entries > tiplog::index::none)
      throw std::invalid_argument("diagnostic configuration range");
    if (const auto* preload = std::getenv("LD_PRELOAD"); preload && *preload)
      throw std::invalid_argument("alternate preloaded allocator is unsupported");
    tiplog::index::Config config;
    config.entries_per_block = static_cast<std::uint32_t>(entries);
    config.blocks = tiplog::index::Index::sizing_blocks(capacity, 16,
        config.entries_per_block, partitions);
    config.sweep_evictions = 256;
    const auto retained_limit = capacity / 16;
    // All parsing, schedule parameters and output setup precede the baseline.
    // No output or non-index dynamic container is used inside the boundary.
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    const auto before = ::mallinfo2();
    auto index = std::make_unique<tiplog::index::Index>(config);
    for (std::uint64_t i = 0; i < publications; ++i) {
      const auto position = i * 16;
      const auto tail = position + 16 > capacity ? position + 16 - capacity : 0;
      const auto partition = static_cast<tiplog::PartitionId>((i * 2654435761ULL) % partitions);
      auto preparation = index->prepare_append(partition, position, tail,
          static_cast<std::size_t>(partitions), i >= retained_limit ? 1 : 0);
      if (!std::holds_alternative<tiplog::index::PreparedAppend>(preparation))
        throw std::logic_error("adequately sized diagnostic encountered pressure");
      index->commit(std::move(std::get<tiplog::index::PreparedAppend>(preparation)),
          std::min(i + 1, retained_limit));
    }
    const auto after = ::mallinfo2();
    const auto stats = index->stats();
    const auto charged_after = sum(after.uordblks, after.hblkhd);
    const auto charged_before = sum(before.uordblks, before.hblkhd);
    const auto charged = difference(charged_after, charged_before);
    const auto system = difference(sum(after.arena, after.hblkhd), sum(before.arena, before.hblkhd));
    const auto overhead = difference(charged_after,
        sum(charged_before, stats.memory.reserved_bytes));
    // Independent structural verification is after the allocator snapshot.
    index->check_invariants(stats.tail_pos);
    std::printf("{\"status\":\"ok\",\"method\":\"fresh-single-thread-glibc-mallinfo2-delta\","
        "\"glibc\":\"%s\",\"ring_bytes\":%" PRIu64 ",\"publications\":%" PRIu64
        ",\"partitions\":%" PRIu64 ",\"block_entries\":%u,\"blocks\":%u,"
        "\"allocator_tunables_present\":%s,", gnu_get_libc_version(), capacity, publications,
        partitions, config.entries_per_block, config.blocks,
        std::getenv("GLIBC_TUNABLES") ? "true" : "false");
    print_info("before", before); std::printf(","); print_info("after", after);
    std::printf(",\"allocator_charged_delta_bytes\":%" PRId64
        ",\"system_reserved_delta_bytes\":%" PRId64
        ",\"index_requested_reserved_bytes\":%" PRIu64
        ",\"observed_allocator_overhead_bytes\":%" PRId64
        ",\"live_entries\":%" PRIu64 ",\"allocated_blocks\":%" PRIu64
        ",\"scope\":\"Index object and its allocations only; no Ring or Registry\","
        "\"limitations\":\"Process allocator delta includes chunk rounding and retained freed/tcache chunks; "
        "baseline reuse can affect the signed difference. It is not per-object headers, total RSS, "
        "or a portable allocator guarantee. No negative result is clamped.\"}\n",
        charged, system, stats.memory.reserved_bytes, overhead,
        stats.gauges.live_entries, stats.gauges.allocated_blocks);
    if (std::fflush(stdout) != 0 || std::ferror(stdout))
      throw std::runtime_error("failed writing index memory result");
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "index memory diagnostic: %s\n", error.what());
    return 1;
  }
}
#else
int main() {
  std::fprintf(stderr, "index memory diagnostic requires glibc without ASan\n");
  return 77;
}
#endif
