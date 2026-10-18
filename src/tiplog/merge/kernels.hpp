#pragma once

#include "tiplog/types.hpp"

#include <algorithm>
#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <queue>
#include <span>
#include <stdexcept>
#include <utility>
#include <variant>
#include <vector>

namespace tiplog::merge {
using Key = std::uint64_t;
inline constexpr Key sentinel = std::numeric_limits<Key>::max();
inline constexpr std::uint32_t max_cursors = 65535;
inline constexpr LogPos position_limit = LogPos{1} << 51U;
[[nodiscard]] inline Key pack(LogPos pos, std::uint32_t id,
                              std::uint32_t count = max_cursors) {
  if ((pos & 7U) != 0 || pos >= position_limit || count > max_cursors ||
      id >= count)
    throw std::invalid_argument("packed merge key outside representation");
  return ((pos >> 3U) << 16U) | id;
}
[[nodiscard]] inline LogPos position(Key key) {
  if ((key & 0xffffU) >= max_cursors)
    throw std::invalid_argument("invalid key has no position");
  return (key >> 16U) << 3U;
}
[[nodiscard]] inline std::uint32_t cursor_id(Key key) {
  if ((key & 0xffffU) >= max_cursors)
    throw std::invalid_argument("invalid key has no cursor");
  return static_cast<std::uint32_t>(key & 0xffffU);
}
[[nodiscard]] inline LogPos unpack_pos(Key key) { return position(key); }
[[nodiscard]] inline std::uint32_t unpack_id(Key key) { return cursor_id(key); }

namespace detail {
void validate_heads(std::span<const Key> heads);
inline void validate_replacement(Key old, Key replacement) {
  if (old == sentinel ||
      (replacement != sentinel &&
       ((old & 0xffffU) != (replacement & 0xffffU) || replacement <= old)))
    throw std::invalid_argument("replacement must advance the winning cursor");
}
struct AlignedDelete {
  void operator()(Key *data) const noexcept;
};
} // namespace detail

class StdPQ {
public:
  explicit StdPQ(std::span<const Key> heads = {});
  [[nodiscard]] bool empty() const noexcept { return heap_.empty(); }
  [[nodiscard]] Key top() const noexcept {
    return empty() ? sentinel : heap_.top();
  }
  void pop() {
    if (empty())
      throw std::out_of_range("pop empty StdPQ");
    heap_.pop();
  }
  void replace_top(Key replacement) {
    detail::validate_replacement(top(), replacement);
    heap_.pop();
    if (replacement != sentinel)
      heap_.push(replacement);
  }

private:
  std::priority_queue<Key, std::vector<Key>, std::greater<Key>> heap_;
};
class BinHeap {
public:
  explicit BinHeap(std::span<const Key> heads = {});
  [[nodiscard]] bool empty() const noexcept { return heap_.empty(); }
  [[nodiscard]] Key top() const noexcept {
    return empty() ? sentinel : heap_[0];
  }
  void pop() {
    if (empty())
      throw std::out_of_range("pop empty BinHeap");
    const auto last = heap_.back();
    heap_.pop_back();
    if (!empty())
      sift(0, last);
  }
  void replace_top(Key replacement) {
    detail::validate_replacement(top(), replacement);
    if (replacement == sentinel)
      pop();
    else
      sift(0, replacement);
  }

private:
  void sift(std::size_t hole, Key value) noexcept {
    const auto count = heap_.size();
    while (hole < count / 2) {
      auto child = 2 * hole + 1;
      if (child + 1 < count && heap_[child + 1] < heap_[child])
        ++child;
      if (value <= heap_[child])
        break;
      heap_[hole] = heap_[child];
      hole = child;
    }
    heap_[hole] = value;
  }
  std::vector<Key> heap_;
};
class Quad {
public:
  explicit Quad(std::span<const Key> heads = {}, std::uint32_t padding = 3);
  Quad(Quad &&other) noexcept
      : data_(std::move(other.data_)), size_(std::exchange(other.size_, 0)),
        padding_(std::exchange(other.padding_, 0)) {}
  Quad &operator=(Quad &&other) noexcept {
    if (this != &other) {
      data_ = std::move(other.data_);
      size_ = std::exchange(other.size_, 0);
      padding_ = std::exchange(other.padding_, 0);
    }
    return *this;
  }
  Quad(const Quad &) = delete;
  Quad &operator=(const Quad &) = delete;
  [[nodiscard]] bool empty() const noexcept { return size_ == 0; }
  [[nodiscard]] Key top() const noexcept { return empty() ? sentinel : at(0); }
  [[nodiscard]] std::uint32_t padding() const noexcept { return padding_; }
  [[nodiscard]] const Key *physical_base() const noexcept {
    return data_.get();
  }
  [[nodiscard]] const Key *logical_base() const noexcept {
    return data_ ? data_.get() + padding_ : nullptr;
  }
  void pop() {
    if (empty())
      throw std::out_of_range("pop empty Quad");
    const auto last = at(size_ - 1);
    --size_;
    if (!empty())
      sift(0, last);
  }
  void replace_top(Key replacement) {
    detail::validate_replacement(top(), replacement);
    if (replacement == sentinel)
      pop();
    else
      sift(0, replacement);
  }

private:
  [[nodiscard]] Key &at(std::size_t i) noexcept {
    return data_.get()[i + padding_];
  }
  [[nodiscard]] const Key &at(std::size_t i) const noexcept {
    return data_.get()[i + padding_];
  }
  void sift(std::size_t hole, Key value) noexcept {
    while (size_ > 1 && hole <= (size_ - 2) / 4) {
      auto child = 4 * hole + 1;
      const auto end = std::min(child + 4, size_);
      auto best = child;
      for (++child; child < end; ++child)
        if (at(child) < at(best))
          best = child;
      if (value <= at(best))
        break;
      at(hole) = at(best);
      hole = best;
    }
    at(hole) = value;
  }
  std::unique_ptr<Key, detail::AlignedDelete> data_;
  std::size_t size_{};
  std::uint32_t padding_{3};
};
class Loser {
public:
  explicit Loser(std::span<const Key> heads = {});
  Loser(Loser &&other) noexcept
      : nodes_(std::move(other.nodes_)),
        active_(std::exchange(other.active_, 0)) {}
  Loser &operator=(Loser &&other) noexcept {
    if (this != &other) {
      nodes_ = std::move(other.nodes_);
      active_ = std::exchange(other.active_, 0);
    }
    return *this;
  }
  Loser(const Loser &) = default;
  Loser &operator=(const Loser &) = default;
  [[nodiscard]] bool empty() const noexcept { return active_ == 0; }
  [[nodiscard]] Key top() const noexcept {
    return empty() ? sentinel : nodes_[0];
  }
  [[nodiscard]] std::size_t padded_leaves() const noexcept {
    return nodes_.size();
  }
  void pop() {
    if (empty())
      throw std::out_of_range("pop empty Loser");
    replace_top(sentinel);
  }
  void replace_top(Key replacement) {
    const auto old = top();
    detail::validate_replacement(old, replacement);
    const auto id = static_cast<std::uint32_t>(old & 0xffffU);
    if (replacement == sentinel)
      --active_;
    auto value = replacement;
    // The path belongs to the old winning leaf. Swaps change candidate
    // identity, never the path currently being replayed.
    for (auto node = (nodes_.size() + id) / 2; node != 0; node /= 2) {
      const auto opponent = nodes_[node];
      const bool opponent_wins = opponent < value;
      nodes_[node] = opponent_wins ? value : opponent;
      value = opponent_wins ? opponent : value;
    }
    nodes_[0] = value;
  }

private:
  std::vector<Key> nodes_;
  std::size_t active_{};
};
using Kernel = std::variant<StdPQ, BinHeap, Quad, Loser>;
[[nodiscard]] Kernel make_kernel(MergeKernel kind, std::span<const Key> heads);
} // namespace tiplog::merge
