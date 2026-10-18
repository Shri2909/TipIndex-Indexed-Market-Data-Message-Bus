#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace tiplog {

using Seq = std::uint64_t;
using LogPos = std::uint64_t;
using TopicId = std::uint32_t;
using PartitionId = std::uint32_t;

struct Term {
  enum Kind : std::uint8_t { Exact, Subtree };
  Kind kind{};
  std::string path;
  bool operator==(const Term&) const = default;
};
struct SubscriptionSpec {
  std::vector<Term> terms;
  bool operator==(const SubscriptionSpec&) const = default;
};
struct ResumeCheckpoint {
  Seq after_seq{};
  LogPos next_pos{};
  bool operator==(const ResumeCheckpoint&) const = default;
};

enum class ReplayMode : std::uint8_t { Scan, Indexed, Auto };
enum class MergeKernel : std::uint8_t { StdPQ, BinHeap, Quad, Loser };
enum class PoolPolicy : std::uint8_t { ForceEvict, RejectPublish };
enum class Status : std::uint8_t { More, Done, Error };

struct Delivered {
  Seq seq{};
  LogPos pos{};
  TopicId topic{};
  std::span<const std::byte> payload;
};
struct ReplayError {
  enum Kind : std::uint8_t { HistoryExpired, FellBehind };
  Kind kind{};
  Seq requested_after{};
  Seq last_delivered{};
  Seq oldest_retained{};
  bool operator==(const ReplayError&) const = default;
};

}  // namespace tiplog
