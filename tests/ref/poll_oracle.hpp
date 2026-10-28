#pragma once

// Independent, deliberately simple logical-position model for finite polling.
// No production ring, registry, filter, index, merge, or polling code is used.
#include "scan_oracle.hpp"

#include <algorithm>
#include <set>

namespace tiplog::ref {
enum class PollReason { NoWork, OutputLimit, InspectionLimit, SnapshotDone, CaughtUp, Error };
struct PollExpected {
  Status status;
  PollReason stop;
  std::uint64_t inspections{};
  std::vector<OracleRecord> output;
};
inline std::string partition_path(std::string_view path) {
  const auto first = path.find('/');
  if (first == path.npos) return std::string(path);
  const auto second = path.find('/', first + 1);
  return std::string(path.substr(0, second));
}

class PollOracleReplay {
 public:
  PollOracleReplay(const ScanOracle& oracle, SubscriptionSpec spec, Seq after,
                   bool indexed, const std::set<std::string>& registered,
                   std::optional<ResumeCheckpoint> supplied = std::nullopt)
      : oracle_(&oracle), spec_(std::move(spec)), indexed_(indexed), requested_(after), last_(after) {
    const auto opened = oracle.open_replay(spec_, after);
    status = opened.status(); error = opened.error(); checkpoint = opened.checkpoint();
    upper_seq = opened.upper_seq(); upper_pos = opened.upper_pos();
    if (supplied && status == Status::More && supplied->next_pos >= oracle.tail_pos() &&
        supplied->next_pos <= checkpoint->next_pos) {
      const auto& items = oracle.items();
      const auto item = std::lower_bound(items.begin(), items.end(), supplied->next_pos,
                                        [](const auto& value, LogPos pos) { return value.pos < pos; });
      if (item != items.end() && item->pos == supplied->next_pos) checkpoint = supplied;
    }
    for (const auto& path : registered)
      if (ScanOracle::matches(spec_, path)) selected_.insert(partition_path(path));
  }

  PollExpected poll(std::size_t outputs, std::optional<std::uint64_t> cap) {
    PollExpected answer{status, PollReason::NoWork, 0, {}};
    const auto finish = [&](PollReason stop) {
      answer.status = status; answer.stop = stop; return answer;
    };
    if (outputs == 0 || cap == 0) return finish(PollReason::NoWork);
    if (status != Status::More)
      return finish(status == Status::Error ? PollReason::Error : PollReason::SnapshotDone);
    if (checkpoint->next_pos == upper_pos) {
      status = Status::Done;
      return finish(PollReason::SnapshotDone);
    }
    if (checkpoint->next_pos < oracle_->tail_pos()) {
      status = Status::Error;
      error = ReplayError{ReplayError::FellBehind, requested_, last_, oracle_->tail_seq()};
      return finish(PollReason::Error);
    }
    const auto& items = oracle_->items();
    auto item = std::lower_bound(items.begin(), items.end(), checkpoint->next_pos,
                                [](const auto& value, LogPos pos) { return value.pos < pos; });
    for (; item != items.end() && item->pos < upper_pos; ++item) {
      const OracleRecord* record = item->seq ? &oracle_->full_records().at(*item->seq - 1) : nullptr;
      if (indexed_ && (!record || !selected_.contains(partition_path(record->path)))) continue;
      // Looking for an eligible item is metadata in this model. No item after
      // an exhausted allowance is traversed/decoded in the production contract.
      if (cap && answer.inspections == *cap) return finish(PollReason::InspectionLimit);
      ++answer.inspections;
      const bool match = record && ScanOracle::matches(spec_, record->path);
      if (match) {
        answer.output.push_back(*record);
        last_ = record->seq;
      }
      if (!indexed_ || cap || match) {
        if (record) checkpoint->after_seq = record->seq;
        checkpoint->next_pos = item->pos + item->size;
      }
      if (answer.output.size() == outputs) return finish(PollReason::OutputLimit);
    }
    checkpoint = ResumeCheckpoint{upper_seq, upper_pos};
    status = Status::Done;
    return finish(PollReason::SnapshotDone);
  }

  Status status{Status::More};
  std::optional<ReplayError> error;
  std::optional<ResumeCheckpoint> checkpoint;
  Seq upper_seq{};
  LogPos upper_pos{};
 private:
  const ScanOracle* oracle_;
  SubscriptionSpec spec_;
  bool indexed_;
  Seq requested_;
  Seq last_;
  std::set<std::string> selected_;
};

class PollOracleTail {
 private:
  const ScanOracle* oracle_;
  SubscriptionSpec spec_;
  Seq requested_;
  Seq last_;
 public:
  PollOracleTail(const ScanOracle& oracle, SubscriptionSpec spec, Seq after,
                 bool indexed, const std::set<std::string>& registered)
      : oracle_(&oracle), spec_(std::move(spec)), requested_(after), last_(after),
        replay(oracle, spec_, after, indexed, registered) {
    status = replay.status; checkpoint = replay.checkpoint; error = replay.error;
  }
  // On each new range Auto may choose a different execution mode. The harness
  // uses explicit Scan/Indexed for interleaved tails; Auto is covered by Replay
  // campaigns and deterministic Tail tests independently of this model.
  PollExpected poll(std::size_t outputs, std::optional<std::uint64_t> cap,
                    bool indexed, const std::set<std::string>& registered) {
    PollExpected answer{status, PollReason::NoWork, 0, {}};
    const auto finish = [&](PollReason stop) {
      answer.status = status; answer.stop = stop; return answer;
    };
    if (outputs == 0 || cap == 0) return finish(PollReason::NoWork);
    if (status == Status::Error) return finish(PollReason::Error);
    for (;;) {
      if (replay.status == Status::Done) {
        if (checkpoint->after_seq == oracle_->head_seq() - 1) {
          status = Status::Done; return finish(PollReason::CaughtUp);
        }
        if (cap && answer.inspections == *cap) {
          status = Status::More; return finish(PollReason::InspectionLimit);
        }
        replay = PollOracleReplay(*oracle_, spec_, checkpoint->after_seq,
                                  indexed, registered, checkpoint);
        if (replay.status == Status::Error) {
          status = Status::Error;
          error = ReplayError{ReplayError::FellBehind, requested_, last_, oracle_->tail_seq()};
          return finish(PollReason::Error);
        }
      }
      auto remaining = cap;
      if (remaining) *remaining -= answer.inspections;
      auto part = replay.poll(outputs - answer.output.size(), remaining);
      answer.inspections += part.inspections;
      answer.output.insert(answer.output.end(), part.output.begin(), part.output.end());
      if (!part.output.empty()) last_ = part.output.back().seq;
      status = part.status;
      if (replay.checkpoint) checkpoint = replay.checkpoint;
      if (status == Status::Error) {
        error = ReplayError{ReplayError::FellBehind, requested_, last_, oracle_->tail_seq()};
        return finish(PollReason::Error);
      }
      if (status == Status::More) return finish(part.stop);
    }
  }
  Status status{Status::More};
  std::optional<ReplayError> error;
  std::optional<ResumeCheckpoint> checkpoint;
  PollOracleReplay replay;
};
}  // namespace tiplog::ref
