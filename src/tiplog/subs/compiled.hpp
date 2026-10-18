#pragma once

#include "tiplog/topics/registry.hpp"

#include <memory>
#include <span>

namespace tiplog::subs {

struct PartitionFilter {
  PartitionId partition{};
  bool all{};
  std::vector<std::uint64_t> bits;
  [[nodiscard]] bool matches(std::uint16_t local_id) const noexcept;
};

namespace detail {
struct CompiledState;
}

class CompiledSubscription {
 public:
  CompiledSubscription() = default;
  [[nodiscard]] bool wide() const noexcept;
  [[nodiscard]] bool matches(TopicId) const;
  [[nodiscard]] bool belongs_to(const topics::Registry&) const noexcept;
  [[nodiscard]] std::span<const Term> normalized_terms() const noexcept;
  // Ordered by partition ID, with one filter per selected partition. Views may
  // invalidate on registry.intern(); the single-threaded core never interleaves it.
  [[nodiscard]] std::span<const PartitionFilter> filters() const noexcept;
  [[nodiscard]] const PartitionFilter* partition_filter(PartitionId) const noexcept;

 private:
  friend CompiledSubscription compile(topics::Registry&, const SubscriptionSpec&);
  explicit CompiledSubscription(std::shared_ptr<detail::CompiledState> state)
      : state_(std::move(state)) {}
  std::shared_ptr<detail::CompiledState> state_;
};

// Empty specs are rejected: the product defines a nonempty union of terms.
// Duplicate terms and covered exact/subtree terms are removed deterministically.
[[nodiscard]] SubscriptionSpec normalize(const SubscriptionSpec&);
[[nodiscard]] CompiledSubscription compile(topics::Registry&, const SubscriptionSpec&);

}  // namespace tiplog::subs
