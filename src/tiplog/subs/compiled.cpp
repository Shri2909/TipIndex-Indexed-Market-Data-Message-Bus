#include "tiplog/subs/compiled.hpp"

#include <algorithm>
#include <functional>
#include <unordered_set>
#include <utility>
#include <type_traits>

namespace tiplog::subs {
namespace {
static_assert(std::is_nothrow_move_constructible_v<PartitionFilter>);
static_assert(std::is_nothrow_move_assignable_v<PartitionFilter>);
struct PathHash {
  using is_transparent = void;
  std::size_t operator()(std::string_view path) const noexcept {
    return std::hash<std::string_view>{}(path);
  }
};
using Paths = std::unordered_set<std::string, PathHash, std::equal_to<>>;

bool has_subtree_prefix(const Paths& roots, std::string_view path,
                        bool include_self = true) {
  if (roots.empty()) return false;
  if (include_self && roots.contains(path)) return true;
  for (auto end = path.find('/'); end != std::string_view::npos;
       end = path.find('/', end + 1)) {
    if (roots.contains(path.substr(0, end))) return true;
  }
  return false;
}

// Own the strings rather than views into terms, so the lookup lifetime is
// independent of vector moves. Transparent lookup allocates no path prefixes.
// Matching uses one exact lookup plus one lookup per segment boundary, never
// a scan through the subscription's terms. No iteration order affects output.
struct Matching {
  Paths exact, subtree, whole_partition;
  explicit Matching(std::span<const Term> terms) {
    const auto subtrees = static_cast<std::size_t>(std::count_if(
        terms.begin(), terms.end(), [](const Term& term) {
          return term.kind == Term::Subtree;
        }));
    exact.reserve(terms.size() - subtrees);
    subtree.reserve(subtrees);
    whole_partition.reserve(subtrees);
    for (const auto& term : terms) {
      if (term.kind == Term::Exact) {
        exact.insert(term.path);
      } else {
        subtree.insert(term.path);
        // A depth-one/two subtree covers every topic in its partition.
        if (std::count(term.path.begin(), term.path.end(), '/') < 2)
          whole_partition.insert(term.path);
      }
    }
  }
  bool matches(std::string_view path) const {
    return exact.contains(path) || has_subtree_prefix(subtree, path);
  }
  bool covers_partition(std::string_view path) const {
    return has_subtree_prefix(whole_partition, path);
  }
};
auto find_filter(auto& filters, PartitionId partition) {
  return std::lower_bound(filters.begin(), filters.end(), partition,
                          [](const PartitionFilter& filter, PartitionId id) {
                            return filter.partition < id;
                          });
}
void include(PartitionFilter& filter, const topics::Topic& topic, bool all) {
  if (filter.all) return;
  if (all) {
    filter.all = true;
    filter.bits.clear();
    return;
  }
  const auto word = static_cast<std::size_t>(topic.local_id) / 64;
  if (filter.bits.size() <= word) filter.bits.resize(word + 1, 0);
  filter.bits[word] |= std::uint64_t{1} << (topic.local_id % 64);
}
}  // namespace

bool PartitionFilter::matches(std::uint16_t local_id) const noexcept {
  const auto word = static_cast<std::size_t>(local_id) / 64;
  return all || (word < bits.size() &&
                 (bits[word] & (std::uint64_t{1} << (local_id % 64))) != 0);
}

SubscriptionSpec normalize(const SubscriptionSpec& spec) {
  if (spec.terms.empty()) throw std::invalid_argument("subscription requires at least one term");
  SubscriptionSpec result = spec;
  for (const auto& term : result.terms) {
    topics::Registry::validate_path(term.path);
    if (term.kind != Term::Exact && term.kind != Term::Subtree) {
      throw std::invalid_argument("invalid subscription term kind");
    }
  }
  std::sort(result.terms.begin(), result.terms.end(), [](const Term& a, const Term& b) {
    if (a.path != b.path) return a.path < b.path;
    return a.kind < b.kind;
  });
  result.terms.erase(std::unique(result.terms.begin(), result.terms.end()), result.terms.end());
  Paths subtrees;
  subtrees.reserve(result.terms.size());
  for (const auto& term : result.terms) {
    if (term.kind == Term::Subtree) subtrees.insert(term.path);
  }
  std::vector<Term> retained;
  retained.reserve(result.terms.size());
  for (const auto& term : result.terms) {
    const bool covered = has_subtree_prefix(subtrees, term.path,
                                            term.kind == Term::Exact);
    if (!covered) retained.push_back(term);
  }
  result.terms = std::move(retained);
  return result;
}

namespace detail {
struct CompiledState final : topics::TopicObserver {
  topics::Registry* registry;
  std::weak_ptr<const topics::Registry::Lifetime> identity;
  std::vector<Term> terms;
  const Matching matching;
  std::vector<PartitionFilter> filters;
  std::vector<topics::ObserverHandle> hooks;
  bool wide{};

  CompiledState(topics::Registry& source, std::vector<Term> normalized)
      : registry(&source), identity(source.identity()), terms(std::move(normalized)),
        matching(terms) {}

  struct Prepared final : Update {
    CompiledState& state;
    std::vector<PartitionFilter> changed;
    std::vector<PartitionFilter> added;
    explicit Prepared(CompiledState& source) : state(source) {}
    void commit() noexcept override {
      // Prepare has reserved the destination vector. Replacements swap vectors;
      // inserting a filter moves only noexcept vector/scalar members.
      for (auto& filter : changed) {
        const auto destination = find_filter(state.filters, filter.partition);
        destination->all = filter.all;
        destination->bits.swap(filter.bits);
      }
      for (auto& filter : added) {
        const auto destination = find_filter(state.filters, filter.partition);
        state.filters.insert(destination, std::move(filter));
      }
    }
  };

  std::unique_ptr<Update> prepare(std::span<const topics::Topic> pending) override {
    auto update = std::make_unique<Prepared>(*this);
    for (const auto& topic : pending) {
      if (!matching.matches(topic.path)) continue;
      const auto current = find_filter(filters, topic.partition);
      const bool exists = current != filters.end() && current->partition == topic.partition;
      if (exists && current->all) continue;
      auto& staged = exists ? update->changed : update->added;
      auto filter = find_filter(staged, topic.partition);
      if (filter == staged.end() || filter->partition != topic.partition) {
        filter = staged.insert(filter, exists ? *current : PartitionFilter{topic.partition, false, {}});
      }
      include(*filter, topic, matching.covers_partition(topic.path));
    }
    const auto required = filters.size() + update->added.size();
    if (required > filters.capacity()) {
      const auto increment = std::min(filters.max_size() - filters.capacity(),
                                      filters.capacity() / 2 + 1);
      filters.reserve(std::max(required, filters.capacity() + increment));
    }
    return update;
  }
};
}  // namespace detail

bool CompiledSubscription::wide() const noexcept { return state_ && state_->wide; }
bool CompiledSubscription::belongs_to(const topics::Registry& registry) const noexcept {
  if (!state_) return false;
  const auto identity = state_->identity.lock();
  const auto source = registry.identity().lock();
  return identity && identity->alive() && source && source->alive() && identity.get() == source.get();
}
bool CompiledSubscription::matches(TopicId id) const {
  if (!state_) return false;
  const auto lifetime = state_->identity.lock();
  if (!lifetime || !lifetime->alive()) return false;
  const auto& topic = state_->registry->get(id);
  const auto* filter = partition_filter(topic.partition);
  return filter && filter->matches(topic.local_id);
}
std::span<const Term> CompiledSubscription::normalized_terms() const noexcept {
  return state_ ? std::span<const Term>{state_->terms} : std::span<const Term>{};
}
std::span<const PartitionFilter> CompiledSubscription::filters() const noexcept {
  return state_ ? std::span<const PartitionFilter>{state_->filters} : std::span<const PartitionFilter>{};
}
const PartitionFilter* CompiledSubscription::partition_filter(PartitionId partition) const noexcept {
  if (!state_) return nullptr;
  const auto filter = find_filter(state_->filters, partition);
  return filter != state_->filters.end() && filter->partition == partition ? &*filter : nullptr;
}

CompiledSubscription compile(topics::Registry& registry, const SubscriptionSpec& spec) {
  auto normalized = normalize(spec);
  // Intern all roots, including exact topics that have never been published.
  // Validation precedes interning, so malformed terms have no registry effects.
  std::vector<TopicId> roots;
  roots.reserve(normalized.terms.size());
  for (const auto& term : normalized.terms) roots.push_back(registry.intern(term.path));
  auto state = std::make_shared<detail::CompiledState>(registry, std::move(normalized.terms));
  for (const auto& term : state->terms) {
    if (term.kind == Term::Subtree && std::count(term.path.begin(), term.path.end(), '/') < 1) {
      state->wide = true;
    }
  }
  for (const auto& topic : registry.all_topics()) {
    if (!state->matching.matches(topic.path)) continue;
    auto filter = find_filter(state->filters, topic.partition);
    if (filter == state->filters.end() || filter->partition != topic.partition) {
      filter = state->filters.insert(filter, PartitionFilter{topic.partition, false, {}});
    }
    include(*filter, topic, state->matching.covers_partition(topic.path));
  }
  state->hooks.reserve(state->terms.size());
  for (std::size_t i = 0; i < state->terms.size(); ++i) {
    if (state->terms[i].kind == Term::Subtree) {
      state->hooks.push_back(registry.observe(roots[i], state));
    }
  }
  return CompiledSubscription{std::move(state)};
}

}  // namespace tiplog::subs
