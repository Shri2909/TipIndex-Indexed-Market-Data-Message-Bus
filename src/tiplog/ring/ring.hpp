#pragma once

#include "tiplog/types.hpp"

#include <cstddef>
#include <cstdint>
#include <limits>
#include <span>
#include <vector>

namespace tiplog::ring {

struct RingConfig {
  std::size_t ring_bytes{};
  std::size_t max_record_bytes{};
  std::uint32_t ckpt_log2{8};
  // Exclusive logical-head bound; at most 2^51.
  LogPos position_limit{LogPos{1} << 51U};
  // Exclusive published-sequence bound.
  Seq sequence_limit{std::numeric_limits<Seq>::max()};
};

struct Item {
  LogPos pos{};
  std::size_t size{};
  bool pad{};
  TopicId topic{};
  Seq seq{};
  std::span<const std::byte> payload;
};

struct Published {
  Seq seq{};
  LogPos pos{};
  std::size_t size{};
};

struct RingStats {
  std::uint64_t data_appended{};
  std::uint64_t data_evicted{};
  std::uint64_t data_bytes_evicted{};
  std::uint64_t pad_items_appended{};
  std::uint64_t pad_bytes_appended{};
  std::uint64_t pad_items_evicted{};
  std::uint64_t pad_bytes_evicted{};
  std::uint64_t pressure_data_evicted{};
  std::uint64_t pressure_bytes_evicted{};
  bool operator==(const RingStats&) const = default;
};

struct SeekMetrics {
  std::uint64_t data_examined{};
  std::uint64_t pads_examined{};
};

// Single-threaded retained byte log of DATA and PAD items.
class Ring {
 public:
  struct Layout {
    LogPos original_head{};
    LogPos original_tail{};
    Seq original_sequence{};
    LogPos data_pos{};
    LogPos end_pos{};
    LogPos tail_pos{};
    Seq tail_seq{};
    std::size_t record_bytes{};
    std::size_t padding_bytes{};
    std::size_t payload_bytes{};
    std::uint64_t data_evicted{};
    std::uint64_t data_bytes_evicted{};
    std::uint64_t pad_items_evicted{};
    std::uint64_t pad_bytes_evicted{};
    std::uint64_t pressure_data_evicted{};
    std::uint64_t pressure_bytes_evicted{};
    LogPos last_evicted_start{};
    bool evicted_any{};
    bool pressure{};
  };

  class Plan {
   public:
    Plan(Plan&&) noexcept = default;
    Plan& operator=(Plan&&) noexcept = default;
    Plan(const Plan&) = delete;
    Plan& operator=(const Plan&) = delete;
    [[nodiscard]] const Layout& layout() const noexcept { return layout_; }

   private:
    friend class Ring;
    Plan() = default;
    const Ring* owner_{};
    Layout layout_;
    std::span<const std::byte> source_;
    std::vector<std::byte> alias_copy_;
  };

  explicit Ring(RingConfig config);
  Ring(const Ring&) = delete;
  Ring& operator=(const Ring&) = delete;
  Ring(Ring&&) = delete;
  Ring& operator=(Ring&&) = delete;

  [[nodiscard]] LogPos head_pos() const noexcept { return head_pos_; }
  [[nodiscard]] LogPos tail_pos() const noexcept { return tail_pos_; }
  [[nodiscard]] Seq head_seq() const noexcept { return head_seq_; }
  [[nodiscard]] Seq tail_seq() const noexcept { return tail_seq_; }
  [[nodiscard]] const RingStats& stats() const noexcept { return stats_; }
  [[nodiscard]] std::size_t checkpoint_slots() const noexcept { return checkpoints_.size(); }
  [[nodiscard]] SeekMetrics last_seek_metrics() const noexcept { return last_seek_; }
  [[nodiscard]] std::span<const std::byte> storage_bytes() const noexcept { return bytes_; }

  // minimum_tail: optional pressure target at an existing boundary; 0 means
  // capacity-only eviction. Does not mutate.
  [[nodiscard]] Layout dry_run(std::size_t payload_bytes, LogPos minimum_tail = 0) const;
  // Copies the payload only if it aliases ring storage.
  [[nodiscard]] Plan plan_append(std::span<const std::byte> payload,
                                 LogPos minimum_tail = 0) const;
  // Consume a Plan exactly once, with no ring mutation in between; a stale or
  // foreign plan terminates. Never allocates or rejects.
  [[nodiscard]] Published commit(Plan&& plan, TopicId topic) noexcept;
  Seq append(TopicId topic, std::span<const std::byte> payload);

  // O(1). pos must be a retained item boundary (tail_pos(), seek_after(), an
  // index posting, or prior pos + size); an aligned interior position is a
  // precondition violation. Payload is valid until the next mutation. Use
  // at_checked() for untrusted positions.
  [[nodiscard]] Item at(LogPos pos) const;
  // Walks from the tail, O(retained items); non-boundaries throw out_of_range.
  [[nodiscard]] Item at_checked(LogPos pos) const;
  [[nodiscard]] bool is_boundary(LogPos pos) const;
  // First retained DATA with seq > after, or head_pos. Expired history throws.
  [[nodiscard]] LogPos seek_after(Seq after) const;
  void check_invariants() const;

 private:
  [[nodiscard]] Item decode(LogPos pos) const;
  [[nodiscard]] std::size_t physical(LogPos pos) const noexcept;
  void note_checkpoint(Seq seq, LogPos pos) noexcept;
  RingConfig config_;
  std::vector<std::byte> bytes_;
  // Sparse seek positions; validated against the retained DATA header on use.
  std::vector<LogPos> checkpoints_;
  LogPos head_pos_{};
  LogPos tail_pos_{};
  Seq head_seq_{1};
  Seq tail_seq_{1};
  RingStats stats_;
  mutable SeekMetrics last_seek_;
  LogPos last_evicted_start_{};
  bool has_evicted_{};
  bool capacity_only_{true};
};

}  // namespace tiplog::ring
