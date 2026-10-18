#pragma once

// Test-only specification model. This file deliberately imports no registry,
// compiled subscription, ring, index or production matching implementation.
#include "tiplog/types.hpp"

#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace tiplog::ref {

struct OracleRecord {
  Seq seq{};
  LogPos pos{};
  std::string path;
  std::vector<std::byte> payload;
  std::uint64_t size{};
  bool operator==(const OracleRecord&) const = default;
};

struct OracleItem {
  LogPos pos{};
  std::uint64_t size{};
  // PAD has no sequence; DATA's sequence also indexes full_records()[seq - 1].
  std::optional<Seq> seq;
  bool operator==(const OracleItem&) const = default;
};

class OracleReplay;

class ScanOracle {
 public:
  struct Config {
    std::uint64_t ring_bytes{4096};
    std::uint64_t max_record_bytes{2048};
    // Exclusive logical-boundary limit; small values support near-limit tests.
    LogPos position_limit{LogPos{1} << 51};
    Seq sequence_limit{std::numeric_limits<Seq>::max()};
  };

  explicit ScanOracle(Config config);
  Seq publish(std::string_view path, std::span<const std::byte> payload);
  [[nodiscard]] OracleReplay open_replay(const SubscriptionSpec& sub, Seq after_seq) const;
  [[nodiscard]] LogPos head_pos() const noexcept { return head_pos_; }
  [[nodiscard]] LogPos tail_pos() const noexcept;
  [[nodiscard]] Seq head_seq() const noexcept { return next_seq_; }
  [[nodiscard]] Seq tail_seq() const noexcept;
  [[nodiscard]] const Config& config() const noexcept { return config_; }
  [[nodiscard]] const std::vector<OracleRecord>& full_records() const noexcept { return records_; }
  [[nodiscard]] const std::vector<OracleItem>& items() const noexcept { return items_; }
  [[nodiscard]] std::vector<OracleRecord> retained_records() const;
  [[nodiscard]] static bool matches(const SubscriptionSpec& sub, std::string_view path);

 private:
  friend class OracleReplay;
  Config config_;
  std::vector<OracleRecord> records_;
  std::vector<OracleItem> items_;
  std::size_t first_retained_item_{};
  LogPos head_pos_{};
  Seq next_seq_{1};
};

class OracleReplay {
 public:
  // Replaces out with this call's copied outputs. A zero budget changes neither
  // replay progress nor terminal state; already terminal calls remain stable.
  Status next_batch(std::size_t max, std::vector<OracleRecord>& out);
  [[nodiscard]] std::optional<ReplayError> error() const noexcept { return error_; }
  [[nodiscard]] Seq upper_seq() const noexcept { return upper_seq_; }
  [[nodiscard]] LogPos upper_pos() const noexcept { return upper_pos_; }
  [[nodiscard]] Status status() const noexcept { return status_; }
  [[nodiscard]] std::optional<ResumeCheckpoint> checkpoint() const noexcept { return checkpoint_; }

 private:
  friend class ScanOracle;
  OracleReplay(const ScanOracle& oracle, const SubscriptionSpec& sub, Seq after_seq);
  const ScanOracle* oracle_;
  SubscriptionSpec sub_;
  Seq requested_after_{};
  Seq last_delivered_{};
  Seq upper_seq_{};
  LogPos upper_pos_{};
  std::size_t next_record_{};
  std::size_t end_record_{};
  Status status_{Status::More};
  std::optional<ReplayError> error_;
  std::optional<ResumeCheckpoint> checkpoint_;
};

}  // namespace tiplog::ref
