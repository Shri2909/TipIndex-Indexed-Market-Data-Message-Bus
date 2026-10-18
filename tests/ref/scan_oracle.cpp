#include "scan_oracle.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace tiplog::ref {
namespace {
void validate_path(std::string_view path) {
  if (path.empty() || path.front() == '/' || path.back() == '/' ||
      path.find("//") != std::string_view::npos || path.find('\0') != std::string_view::npos) {
    throw std::invalid_argument("oracle topic requires non-empty path segments");
  }
}
void validate_subscription(const SubscriptionSpec& sub) {
  if (sub.terms.empty()) throw std::invalid_argument("oracle subscription is empty");
  for (const auto& term : sub.terms) {
    validate_path(term.path);
    if (term.kind != Term::Exact && term.kind != Term::Subtree) {
      throw std::invalid_argument("oracle subscription kind is invalid");
    }
  }
}
}  // namespace

ScanOracle::ScanOracle(Config config) : config_(config) {
  if (config.ring_bytes < 32 || (config.ring_bytes & (config.ring_bytes - 1)) != 0 ||
      config.ring_bytes > (std::uint64_t{1} << 31) || config.max_record_bytes < 16 ||
      config.max_record_bytes % 8 != 0 || config.max_record_bytes > config.ring_bytes / 2 ||
      config.position_limit < 16 || config.sequence_limit < 2) {
    throw std::invalid_argument("oracle ring configuration is invalid");
  }
}

Seq ScanOracle::publish(std::string_view path, std::span<const std::byte> payload) {
  validate_path(path);
  // Division-based alignment and modulo-based placement intentionally avoid
  // the production ring's packed header, alignment and masking helpers.
  const auto max_size = config_.max_record_bytes;
  if (payload.size() > max_size - 16) throw std::length_error("oracle oversized payload");
  const std::uint64_t bytes = 16 + static_cast<std::uint64_t>(payload.size());
  const std::uint64_t need = ((bytes + 7) / 8) * 8;
  if (need > max_size) throw std::length_error("oracle oversized aligned record");
  const auto remainder = head_pos_ % config_.ring_bytes;
  const auto space = config_.ring_bytes - remainder;
  const auto pad = space < need ? space : 0;
  const auto advance = pad + need;
  if (head_pos_ >= config_.position_limit || advance >= config_.position_limit - head_pos_ ||
      next_seq_ >= config_.sequence_limit) {
    throw std::overflow_error("oracle logical lifetime exhausted");
  }
  OracleRecord record{next_seq_, head_pos_ + pad, std::string(path),
                      std::vector<std::byte>(payload.begin(), payload.end()), need};
  // All allocations precede visible state mutation, including retention.
  if (records_.size() == records_.capacity()) {
    records_.reserve(std::max(records_.size() + 1, records_.capacity() * 2));
  }
  const auto new_items = items_.size() + (pad == 0 ? 1U : 2U);
  if (new_items > items_.capacity()) {
    items_.reserve(std::max(new_items, items_.capacity() * 2));
  }
  if (pad != 0) items_.push_back({head_pos_, pad, std::nullopt});
  items_.push_back({record.pos, need, next_seq_});
  records_.push_back(std::move(record));
  head_pos_ += advance;
  ++next_seq_;
  const auto lower_bound = head_pos_ > config_.ring_bytes ? head_pos_ - config_.ring_bytes : 0;
  while (first_retained_item_ < items_.size() && items_[first_retained_item_].pos < lower_bound) {
    ++first_retained_item_;
  }
  return next_seq_ - 1;
}

LogPos ScanOracle::tail_pos() const noexcept {
  return first_retained_item_ < items_.size() ? items_[first_retained_item_].pos : head_pos_;
}

Seq ScanOracle::tail_seq() const noexcept {
  for (std::size_t i = first_retained_item_; i < items_.size(); ++i) {
    if (items_[i].seq) return *items_[i].seq;
  }
  return next_seq_;
}

std::vector<OracleRecord> ScanOracle::retained_records() const {
  std::vector<OracleRecord> retained;
  const auto first = tail_seq();
  for (const auto& record : records_) {
    if (record.seq >= first) retained.push_back(record);
  }
  return retained;
}

bool ScanOracle::matches(const SubscriptionSpec& sub, std::string_view path) {
  // Independent direct path union: no registry IDs, bitsets or normalization.
  for (const auto& term : sub.terms) {
    if (path == term.path) return true;
    if (term.kind == Term::Subtree && path.size() > term.path.size() &&
        path.compare(0, term.path.size(), term.path) == 0 && path[term.path.size()] == '/') {
      return true;
    }
  }
  return false;
}

OracleReplay ScanOracle::open_replay(const SubscriptionSpec& sub, Seq after_seq) const {
  return OracleReplay(*this, sub, after_seq);
}

OracleReplay::OracleReplay(const ScanOracle& oracle, const SubscriptionSpec& sub, Seq after_seq)
    : oracle_(&oracle), sub_(sub), requested_after_(after_seq), last_delivered_(after_seq),
      upper_seq_(oracle.head_seq() - 1), upper_pos_(oracle.head_pos()),
      end_record_(oracle.full_records().size()) {
  validate_subscription(sub_);
  // Empty ranges are recognized before after_seq + 1, including UINT64_MAX.
  if (after_seq >= upper_seq_) {
    status_ = Status::Done;
    next_record_ = end_record_;
    if (after_seq == upper_seq_) checkpoint_ = ResumeCheckpoint{upper_seq_, upper_pos_};
    return;
  }
  if (after_seq + 1 < oracle.tail_seq()) {
    status_ = Status::Error;
    error_ = ReplayError{ReplayError::HistoryExpired, requested_after_, last_delivered_, oracle.tail_seq()};
    return;
  }
  // Dense sequences index our complete copied history, independently of the
  // production sparse checkpoints. Opening skips any PAD before the first DATA.
  next_record_ = static_cast<std::size_t>(after_seq);
  checkpoint_ = ResumeCheckpoint{after_seq, oracle.records_[next_record_].pos};
}

Status OracleReplay::next_batch(std::size_t max, std::vector<OracleRecord>& out) {
  out.clear();
  if (max == 0 || status_ != Status::More) return status_;
  if (checkpoint_->next_pos == upper_pos_) {
    status_ = Status::Done;
    checkpoint_ = ResumeCheckpoint{upper_seq_, upper_pos_};
    return status_;
  }
  if (checkpoint_->next_pos < oracle_->tail_pos()) {
    status_ = Status::Error;
    error_ = ReplayError{ReplayError::FellBehind, requested_after_, last_delivered_, oracle_->tail_seq()};
    return status_;
  }
  while (next_record_ < end_record_) {
    const auto& record = oracle_->records_[next_record_];
    ++next_record_;
    checkpoint_ = ResumeCheckpoint{record.seq, record.pos + record.size};
    if (ScanOracle::matches(sub_, record.path)) {
      out.push_back(record);
      last_delivered_ = record.seq;
      if (out.size() == max) return Status::More;
    }
  }
  checkpoint_ = ResumeCheckpoint{upper_seq_, upper_pos_};
  status_ = Status::Done;
  return status_;
}

}  // namespace tiplog::ref
