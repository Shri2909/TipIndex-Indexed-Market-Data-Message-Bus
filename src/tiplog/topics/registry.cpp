#include "tiplog/topics/registry.hpp"

#include <algorithm>
#include <utility>
#include <type_traits>

namespace tiplog::topics {
namespace {
template <class T>
void reserve_growth(std::vector<T>& values, std::size_t needed) {
  if (needed > values.capacity()) {
    const auto available = values.max_size() - values.capacity();
    const auto increment = std::min(available, values.capacity() / 2 + 1);
    values.reserve(std::max(needed, values.capacity() + increment));
  }
}
static_assert(std::is_nothrow_move_constructible_v<Topic>);
static_assert(std::is_nothrow_move_constructible_v<Partition>);
}  // namespace
namespace detail {
struct ObserverHub {
  struct Slot {
    std::uint64_t serial;
    std::weak_ptr<TopicObserver> observer;
  };
  std::unordered_map<TopicId, std::vector<Slot>> roots;
  std::uint64_t next_serial{1};
};
}  // namespace detail

ObserverHandle::ObserverHandle(std::weak_ptr<detail::ObserverHub> hub, TopicId root,
                               std::uint64_t serial)
    : hub_(std::move(hub)), root_(root), serial_(serial) {}
ObserverHandle::~ObserverHandle() { reset(); }
ObserverHandle::ObserverHandle(ObserverHandle&& other) noexcept
    : hub_(std::move(other.hub_)), root_(other.root_), serial_(std::exchange(other.serial_, 0)) {}
ObserverHandle& ObserverHandle::operator=(ObserverHandle&& other) noexcept {
  if (this != &other) {
    reset();
    hub_ = std::move(other.hub_);
    root_ = other.root_;
    serial_ = std::exchange(other.serial_, 0);
  }
  return *this;
}
void ObserverHandle::reset() noexcept {
  if (serial_ != 0) {
    if (auto hub = hub_.lock()) {
      const auto root = hub->roots.find(root_);
      if (root != hub->roots.end()) {
        auto& slots = root->second;
        std::erase_if(slots, [this](const auto& slot) { return slot.serial == serial_; });
        if (slots.empty()) hub->roots.erase(root);
      }
    }
    serial_ = 0;
  }
  hub_.reset();
}

Registry::Registry() : Registry(Limits{}) {}
Registry::Registry(Limits limits)
    : limits_(limits), observers_(std::make_shared<detail::ObserverHub>()), lifetime_(std::make_shared<Lifetime>()) {
  if (limits.max_topics > std::numeric_limits<TopicId>::max() ||
      limits.max_partitions > std::numeric_limits<PartitionId>::max() ||
      limits.max_local_topics > 65536) {
    throw std::invalid_argument("registry limits exceed their stored representations");
  }
}
Registry::~Registry() { lifetime_->alive_ = false; }
std::size_t Registry::StringHash::operator()(std::string_view value) const noexcept {
  return std::hash<std::string_view>{}(value);
}
void Registry::validate_path(std::string_view path) {
  if (path.empty() || path.front() == '/' || path.back() == '/' ||
      path.find("//") != std::string_view::npos || path.find('\0') != std::string_view::npos) {
    throw std::invalid_argument("topic path requires nonempty slash-separated segments");
  }
}
std::optional<TopicId> Registry::find(std::string_view path) const {
  const auto found = paths_.find(path);
  return found == paths_.end() ? std::nullopt : std::optional<TopicId>{found->second};
}
const Topic& Registry::get(TopicId id) const {
  if (id == 0 || static_cast<std::size_t>(id) > topics_.size()) {
    throw std::out_of_range("invalid topic ID");
  }
  return topics_[static_cast<std::size_t>(id) - 1];
}
const Partition& Registry::partition(PartitionId id) const {
  if (static_cast<std::size_t>(id) >= partitions_.size()) {
    throw std::out_of_range("invalid partition ID");
  }
  return partitions_[id];
}
std::weak_ptr<const Registry::Lifetime> Registry::identity() const noexcept { return lifetime_; }
std::size_t Registry::observer_count() const noexcept {
  std::size_t count = 0;
  for (const auto& [root, slots] : observers_->roots) {
    (void)root;
    count += slots.size();
  }
  return count;
}
ObserverHandle Registry::observe(TopicId root, const std::shared_ptr<TopicObserver>& observer) {
  (void)get(root);
  if (!observer) throw std::invalid_argument("null topic observer");
  if (observers_->next_serial == std::numeric_limits<std::uint64_t>::max()) {
    throw RepresentationLimit("topic observer serial exhausted");
  }
  const auto serial = observers_->next_serial;
  // Make both the root node and its vector before consuming a serial. Empty root
  // nodes from an allocation failure are harmless, and are never topic state.
  auto [found, inserted] = observers_->roots.try_emplace(root);
  try {
    found->second.push_back({serial, observer});
  } catch (...) {
    if (inserted) observers_->roots.erase(found);
    throw;
  }
  ++observers_->next_serial;
  return ObserverHandle{observers_, root, serial};
}

TopicId Registry::intern(std::string_view path) {
  validate_path(path);
  if (const auto existing = find(path)) return *existing;

  std::vector<Topic> pending;
  std::vector<Partition> new_partitions;
  // Counts are tentative until every limit and observer update is prepared.
  std::vector<std::pair<PartitionId, std::uint32_t>> additions;
  auto added_count = [&additions](PartitionId id) -> std::uint32_t& {
    const auto found = std::find_if(additions.begin(), additions.end(),
                                    [id](const auto& item) { return item.first == id; });
    if (found != additions.end()) return found->second;
    additions.emplace_back(id, 0);
    return additions.back().second;
  };

  TopicId parent = 0;
  std::uint64_t depth = 0;
  std::size_t end = 0;
  while (end < path.size()) {
    end = path.find('/', end);
    if (end == std::string_view::npos) end = path.size();
    ++depth;
    if (depth > std::numeric_limits<std::uint32_t>::max()) {
      throw RepresentationLimit("topic depth exhausted");
    }
    const auto prefix = path.substr(0, end);
    if (const auto existing = find(prefix)) {
      parent = *existing;
    } else {
      const auto next_count = static_cast<std::uint64_t>(topics_.size()) + pending.size() + 1;
      if (next_count > limits_.max_topics) throw RepresentationLimit("topic IDs exhausted");
      const auto id = static_cast<TopicId>(next_count);
      PartitionId partition_id = 0;
      if (depth <= 2) {
        const auto next_partition_count =
            static_cast<std::uint64_t>(partitions_.size()) + new_partitions.size() + 1;
        if (next_partition_count > limits_.max_partitions) {
          throw RepresentationLimit("partition IDs exhausted");
        }
        partition_id = static_cast<PartitionId>(next_partition_count - 1);
        new_partitions.push_back({partition_id, id, 0});
      } else {
        const Topic& ancestor = static_cast<std::size_t>(parent) <= topics_.size()
                                    ? get(parent)
                                    : pending[static_cast<std::size_t>(parent) - topics_.size() - 1];
        partition_id = ancestor.partition;
      }
      auto& additional = added_count(partition_id);
      const std::uint32_t current = static_cast<std::size_t>(partition_id) < partitions_.size()
                                        ? partitions_[partition_id].topic_count
                                        : 0;
      if (static_cast<std::uint64_t>(current) + additional >= limits_.max_local_topics) {
        throw RepresentationLimit("partition local topic IDs exhausted");
      }
      pending.push_back({id, std::string(prefix), parent, static_cast<std::uint32_t>(depth),
                         partition_id, static_cast<std::uint16_t>(current + additional)});
      ++additional;
      parent = id;
    }
    if (end == path.size()) break;
    ++end;
  }

  // Stage nodes and storage before commit. node insertion below does not allocate
  // after reserve; this map's string hash and equality do not throw.
  PathMap staged_paths;
  staged_paths.reserve(pending.size());
  for (const auto& topic : pending) staged_paths.emplace(topic.path, topic.id);
  reserve_growth(topics_, topics_.size() + pending.size());
  reserve_growth(partitions_, partitions_.size() + new_partitions.size());
  // max_load_factor remains its default 1.0 in this private map. Reserve a
  // geometric number of nodes before the commit, including the first bucket.
  const auto required_paths = paths_.size() + pending.size();
  if (paths_.empty() || required_paths > paths_.bucket_count()) {
    paths_.reserve(std::max(required_paths, paths_.size() + paths_.size() / 2 + 1));
  }

  std::vector<std::shared_ptr<TopicObserver>> affected;
  for (const auto& topic : pending) {
    TopicId ancestor = topic.id;
    while (ancestor != 0) {
      const auto hook = observers_->roots.find(ancestor);
      if (hook != observers_->roots.end()) {
        for (const auto& slot : hook->second) {
          if (auto observer = slot.observer.lock()) {
            const auto already = std::find_if(affected.begin(), affected.end(),
                [&observer](const auto& item) { return item.get() == observer.get(); });
            if (already == affected.end()) affected.push_back(std::move(observer));
          }
        }
      }
      const Topic& item = static_cast<std::size_t>(ancestor) <= topics_.size()
                              ? get(ancestor)
                              : pending[static_cast<std::size_t>(ancestor) - topics_.size() - 1];
      ancestor = item.parent;
    }
  }
  std::vector<std::unique_ptr<TopicObserver::Update>> updates;
  updates.reserve(affected.size());
  for (auto& observer : affected) {
    auto update = observer->prepare(pending);
    if (!update) throw std::logic_error("topic observer returned a null prepared update");
    updates.push_back(std::move(update));
  }

  for (auto& partition_info : new_partitions) partitions_.push_back(std::move(partition_info));
  for (const auto& [id, count] : additions) partitions_[id].topic_count += count;
  while (!staged_paths.empty()) {
    auto node = staged_paths.extract(staged_paths.begin());
    paths_.insert(std::move(node));
  }
  const auto result = pending.back().id;
  for (auto& topic : pending) topics_.push_back(std::move(topic));
  for (auto& update : updates) update->commit();
  return result;
}

}  // namespace tiplog::topics
