#pragma once
// Independent test-only live history model. Only ScanOracle's copied records,
// item boundaries and raw path matcher are used; no production engine helpers.
#include "scan_oracle.hpp"
#include <algorithm>
#include <stdexcept>

namespace tiplog::ref {
class OracleTail {
 public:
  OracleTail(const ScanOracle& history, SubscriptionSpec sub, Seq after)
      : history_(&history), sub_(std::move(sub)), requested_(after), last_(after) {
    if (after > history.head_seq() - 1)
      throw std::invalid_argument("reference future tail floor");
    const auto initial = history.open_replay(sub_, after); // validation only
    upper_ = initial.upper_seq(); upper_pos_ = initial.upper_pos();
    state_ = initial.status(); checkpoint_ = initial.checkpoint(); error_ = initial.error();
    next_ = static_cast<std::size_t>(after);
  }
  Status poll(std::size_t budget, std::vector<OracleRecord>& out) {
    out.clear();
    if (budget == 0 || state_ == Status::Error) return state_;
    for (;;) {
      if (state_ == Status::Done) {
        if (checkpoint_->after_seq == history_->head_seq() - 1) return state_;
        const auto old = *checkpoint_;
        upper_ = history_->head_seq() - 1; upper_pos_ = history_->head_pos();
        if (old.after_seq + 1 < history_->tail_seq()) return expire();
        next_ = static_cast<std::size_t>(old.after_seq);
        const auto canonical = history_->full_records()[next_].pos;
        auto start = canonical;
        // An internally completed checkpoint is trusted only while its exact
        // boundary remains retained. An expired PAD alone is not lost DATA.
        if (old.next_pos >= history_->tail_pos() && old.next_pos <= canonical) {
          const auto& items = history_->items();
          const auto found = std::lower_bound(items.begin(), items.end(), old.next_pos,
              [](const OracleItem& item, LogPos pos) { return item.pos < pos; });
          if (found != items.end() && found->pos == old.next_pos) start = old.next_pos;
        }
        checkpoint_ = ResumeCheckpoint{old.after_seq, start}; state_ = Status::More;
      }
      if (checkpoint_->next_pos == upper_pos_) {
        state_ = Status::Done; checkpoint_ = ResumeCheckpoint{upper_, upper_pos_};
        continue;
      }
      if (checkpoint_->next_pos < history_->tail_pos()) return expire();
      while (next_ < static_cast<std::size_t>(upper_)) {
        const auto& record = history_->full_records()[next_++];
        checkpoint_ = ResumeCheckpoint{record.seq, record.pos + record.size};
        if (ScanOracle::matches(sub_, record.path)) {
          out.push_back(record); last_ = record.seq;
          if (out.size() == budget) return state_;
        }
      }
      state_ = Status::Done; checkpoint_ = ResumeCheckpoint{upper_, upper_pos_};
    }
  }
  [[nodiscard]] Status status() const noexcept { return state_; }
  [[nodiscard]] std::optional<ReplayError> error() const noexcept { return error_; }
  [[nodiscard]] std::optional<ResumeCheckpoint> checkpoint() const noexcept { return checkpoint_; }
  [[nodiscard]] Seq upper_seq() const noexcept { return upper_; }
  [[nodiscard]] LogPos upper_pos() const noexcept { return upper_pos_; }
 private:
  Status expire() {
    state_ = Status::Error;
    error_ = ReplayError{ReplayError::FellBehind, requested_, last_, history_->tail_seq()};
    return state_;
  }
  const ScanOracle* history_;
  SubscriptionSpec sub_;
  Seq requested_{};
  Seq last_{};
  Seq upper_{};
  LogPos upper_pos_{};
  std::size_t next_{};
  Status state_{Status::More};
  std::optional<ResumeCheckpoint> checkpoint_;
  std::optional<ReplayError> error_;
};
} // namespace tiplog::ref
