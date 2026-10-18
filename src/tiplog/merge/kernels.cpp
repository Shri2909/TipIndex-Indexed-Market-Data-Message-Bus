#include "tiplog/merge/kernels.hpp"

#include <bit>
#include <new>

namespace tiplog::merge {
void detail::validate_heads(std::span<const Key> heads) {
  if (heads.size() > max_cursors)
    throw std::invalid_argument("too many merge cursors");
  for (std::size_t i = 0; i < heads.size(); ++i) {
    if (heads[i] != sentinel && (heads[i] & 0xffffU) != i)
      throw std::invalid_argument("merge head identity must match leaf slot");
  }
}
void detail::AlignedDelete::operator()(Key *data) const noexcept {
  ::operator delete(data, std::align_val_t{64});
}
StdPQ::StdPQ(std::span<const Key> heads) {
  detail::validate_heads(heads);
  std::vector<Key> values;
  values.reserve(heads.size());
  for (const auto key : heads)
    if (key != sentinel)
      values.push_back(key);
  heap_ = decltype(heap_)(std::greater<Key>{}, std::move(values));
}
BinHeap::BinHeap(std::span<const Key> heads) {
  detail::validate_heads(heads);
  heap_.reserve(heads.size());
  for (const auto key : heads)
    if (key != sentinel)
      heap_.push_back(key);
  std::make_heap(heap_.begin(), heap_.end(), std::greater<Key>{});
}
Quad::Quad(std::span<const Key> heads, std::uint32_t padding)
    : padding_(padding) {
  detail::validate_heads(heads);
  if (padding != 0 && padding != 3)
    throw std::invalid_argument("Quad padding must be 0 or 3");
  const auto slots = std::max<std::size_t>(1, heads.size() + padding);
  data_.reset(static_cast<Key *>(
      ::operator new(slots * sizeof(Key), std::align_val_t{64})));
  std::fill_n(data_.get(), slots, sentinel);
  for (const auto key : heads)
    if (key != sentinel)
      at(size_++) = key;
  if (size_ > 1) {
    for (auto i = (size_ - 2) / 4 + 1; i != 0;) {
      --i;
      sift(i, at(i));
    }
  }
}
Loser::Loser(std::span<const Key> heads) {
  detail::validate_heads(heads);
  const auto leaves = std::bit_ceil(std::max<std::size_t>(heads.size(), 1));
  nodes_.assign(leaves, sentinel);
  std::vector<Key> tournament(leaves * 2, sentinel);
  for (std::size_t i = 0; i < heads.size(); ++i) {
    tournament[leaves + i] = heads[i];
    if (heads[i] != sentinel)
      ++active_;
  }
  for (auto i = leaves; i > 1;) {
    --i;
    const auto left = tournament[2 * i];
    const auto right = tournament[2 * i + 1];
    tournament[i] = std::min(left, right);
    nodes_[i] = std::max(left, right);
  }
  nodes_[0] = tournament[1];
}
Kernel make_kernel(MergeKernel kind, std::span<const Key> heads) {
  switch (kind) {
  case MergeKernel::StdPQ:
    return StdPQ(heads);
  case MergeKernel::BinHeap:
    return BinHeap(heads);
  case MergeKernel::Quad:
    return Quad(heads);
  case MergeKernel::Loser:
    return Loser(heads);
  }
  throw std::invalid_argument("unknown merge kernel");
}
} // namespace tiplog::merge
