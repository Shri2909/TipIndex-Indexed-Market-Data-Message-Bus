#pragma once

#include "tiplog/types.hpp"

#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <variant>
#include <vector>

namespace tiplog::index {

inline constexpr std::uint32_t none = std::numeric_limits<std::uint32_t>::max();
struct Config {
  std::uint32_t blocks{4096};
  std::uint32_t entries_per_block{1024};
  std::uint64_t sweep_evictions{1024};
  // Narrow widths/limits are explicit test hooks; production is 32 bits/u32
  // max.
  std::uint32_t delta_bits{32};
  std::uint32_t generation_limit{std::numeric_limits<std::uint32_t>::max()};
};
struct BlockMeta {
  LogPos base_pos{};
  LogPos last_pos{};
  std::uint32_t count{};
  PartitionId partition{none};
  std::uint32_t gen{};
  std::uint32_t next{none};
  bool operator==(const BlockMeta &) const = default;
};
static_assert(sizeof(BlockMeta) == 32);
struct Gauges {
  std::uint64_t allocated_blocks{};
  std::uint64_t free_blocks{};
  std::uint64_t sealed_blocks{};
  std::uint64_t allocated_entries{};
  std::uint64_t live_entries{};
  std::uint64_t expired_allocated_entries{};
  std::uint64_t open_slack{};
  std::uint64_t sealed_partial_slack{};
  std::uint64_t free_block_slots{};
  bool operator==(const Gauges &) const = default;
};
struct Memory {
  std::uint64_t metadata_reserved_bytes{};
  std::uint64_t entries_reserved_bytes{};
  std::uint64_t sealed_flags_reserved_bytes{};
  std::uint64_t heap_used_bytes{};
  std::uint64_t heap_reserved_bytes{};
  std::uint64_t partition_state_used_bytes{};
  std::uint64_t partition_state_reserved_bytes{};
  std::uint64_t partition_list_used_bytes{};
  std::uint64_t partition_list_reserved_bytes{};
  std::uint64_t control_bytes{};
  std::uint64_t reserved_bytes{};
  // Allocator headers/arenas are outside this exact requested/reserved
  // subtotal.
  bool allocator_overhead_measured{false};
  bool operator==(const Memory &) const = default;
};
struct Counters {
  std::uint64_t allocations{};
  std::uint64_t frees{};
  std::uint64_t seals{};
  std::uint64_t sweeps{};
  std::uint64_t swept_partitions{};
  std::uint64_t heap_pushes{};
  std::uint64_t heap_pops{};
  std::uint64_t generation_preflight_scans{};
  bool operator==(const Counters &) const = default;
};
struct Stats {
  Gauges gauges;
  Memory memory;
  Counters counters;
  std::uint64_t allocated_high_water{};
  LogPos tail_pos{};
  bool operator==(const Stats &) const = default;
};
struct Recount {
  Gauges gauges;
  Memory memory;
};
struct NeedTailThrough {
  LogPos last_pos{};
};
class RepresentationLimit : public std::length_error {
public:
  using std::length_error::length_error;
};
class StaleCursor : public std::runtime_error {
public:
  using std::runtime_error::runtime_error;
};
class Index;
class PreparedAppend {
public:
  PreparedAppend(const PreparedAppend &) = delete;
  PreparedAppend &operator=(const PreparedAppend &) = delete;
  PreparedAppend(PreparedAppend &&) noexcept = default;
  PreparedAppend &operator=(PreparedAppend &&) noexcept = default;

private:
  friend class Index;
  PreparedAppend() = default;
  const Index *owner_{};
  std::uint64_t version_{};
  PartitionId partition_{};
  LogPos pos_{};
  LogPos tail_{};
  std::uint64_t evictions_{};
  bool sweep_{};
  bool needs_block_{};
};
using Preparation = std::variant<PreparedAppend, NeedTailThrough>;
struct Cursor {
  std::uint32_t block{none};
  std::uint32_t generation{};
  std::uint32_t entry{};
  LogPos pos{std::numeric_limits<LogPos>::max()};
  [[nodiscard]] bool valid() const noexcept { return block != none; }
  bool operator==(const Cursor &) const = default;
};
struct Posting {
  PartitionId partition{};
  LogPos pos{};
  std::uint32_t block{};
  std::uint32_t generation{};
  bool operator==(const Posting &) const = default;
};

class Index {
public:
  explicit Index(const Config &config = {});
  Index(const Index &) = delete;
  Index &operator=(const Index &) = delete;
  Index(Index &&) = delete;
  Index &operator=(Index &&) = delete;
  // No published membership mutation. The caller commits immediately, with no
  // other mutation, after every ring/resource rejection has been preflighted.
  [[nodiscard]] Preparation prepare_append(PartitionId partition, LogPos pos,
                                           LogPos prospective_tail,
                                           std::size_t partition_count,
                                           std::uint64_t data_evictions = 0);
  void commit(PreparedAppend &&prepared,
              std::uint64_t retained_data_count) noexcept;
  [[nodiscard]] Cursor seek(PartitionId partition, LogPos lower_pos) const;
  bool advance(Cursor &cursor, LogPos current_tail) const;
  [[nodiscard]] std::uint64_t estimate_count(PartitionId partition,
                                             LogPos lower_pos,
                                             LogPos upper_pos) const noexcept;
  [[nodiscard]] Stats stats() const;
  [[nodiscard]] Recount recount(LogPos tail) const;
  void check_invariants(LogPos tail) const;
  [[nodiscard]] std::vector<Posting> entries() const;
  [[nodiscard]] std::vector<Posting> retained_entries(LogPos tail) const;
  [[nodiscard]] const std::vector<BlockMeta> &metadata() const noexcept {
    return meta_;
  }
  [[nodiscard]] const Config &config() const noexcept { return config_; }
  [[nodiscard]] static std::uint32_t
  sizing_blocks(std::uint64_t ring_bytes, std::uint32_t minimum_record_bytes,
                std::uint32_t block_entries, std::uint64_t partition_bound);

private:
  struct Partition {
    std::vector<std::uint32_t> ids;
    std::size_t first{};
  };
  struct HeapNode {
    LogPos last{};
    std::uint32_t block{};
    std::uint32_t generation{};
  };
  static_assert(sizeof(HeapNode) == 16);
  [[nodiscard]] static bool heap_greater(const HeapNode &,
                                         const HeapNode &) noexcept;
  [[nodiscard]] std::uint32_t last_block(PartitionId) const noexcept;
  [[nodiscard]] LogPos decode(std::uint32_t block,
                              std::uint32_t entry) const noexcept;
  [[nodiscard]] bool needs_new_block(PartitionId, LogPos,
                                     LogPos) const noexcept;
  [[nodiscard]] bool has_expired_open(PartitionId, LogPos) const noexcept;
  [[nodiscard]] Memory memory() const;
  void reserve_partition_append(PartitionId);
  void preflight_generations(LogPos tail, PartitionId target, bool sweep);
  void reclaim(LogPos tail) noexcept;
  void sweep_open(LogPos tail) noexcept;
  void free_front(PartitionId partition) noexcept;
  void seal(std::uint32_t block) noexcept;
  [[nodiscard]] std::uint32_t allocate(PartitionId, LogPos) noexcept;
  void validate_cursor(const Cursor &, LogPos current_tail) const;

  Config config_;
  std::vector<BlockMeta> meta_;
  std::vector<std::uint32_t> deltas_;
  std::vector<std::uint8_t> sealed_;
  std::vector<HeapNode> heap_;
  std::vector<Partition> partitions_;
  std::uint32_t free_head_{none};
  Gauges gauges_;
  Counters counters_;
  std::uint64_t high_water_{};
  std::uint64_t version_{};
  std::uint64_t evictions_since_sweep_{};
  bool near_generation_limit_{};
  bool has_appended_{};
  LogPos last_appended_{};
  LogPos tail_{};
};

} // namespace tiplog::index
