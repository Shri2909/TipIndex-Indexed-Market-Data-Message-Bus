#pragma once

#include "tiplog/types.hpp"

#include <limits>
#include <memory>
#include <optional>
#include <span>
#include <stdexcept>
#include <string_view>
#include <unordered_map>

namespace tiplog::topics {

class RepresentationLimit : public std::length_error {
 public:
  using std::length_error::length_error;
};

struct Topic {
  TopicId id{};
  std::string path;
  TopicId parent{};  // Zero is the absence of a parent, never a topic ID.
  std::uint32_t depth{};
  PartitionId partition{};
  std::uint16_t local_id{};
  bool operator==(const Topic&) const = default;
};
struct Partition {
  PartitionId id{};
  TopicId root{};
  std::uint32_t topic_count{};
  bool operator==(const Partition&) const = default;
};
struct Limits {
  std::uint64_t max_topics{std::numeric_limits<TopicId>::max()};
  // UINT32_MAX is reserved as the later block-pool free-owner sentinel.
  std::uint64_t max_partitions{std::numeric_limits<PartitionId>::max()};
  std::uint32_t max_local_topics{65536};
};

// Updates are prepared before any registration is committed. A subscription may
// allocate in prepare(), but commit() must only perform nonthrowing mutations.
class TopicObserver {
 public:
  class Update {
   public:
    virtual ~Update() = default;
    virtual void commit() noexcept = 0;
  };
  virtual ~TopicObserver() = default;
  virtual std::unique_ptr<Update> prepare(std::span<const Topic>) = 0;
};

namespace detail {
struct ObserverHub;
}

class ObserverHandle {
 public:
  ObserverHandle() = default;
  ~ObserverHandle();
  ObserverHandle(const ObserverHandle&) = delete;
  ObserverHandle& operator=(const ObserverHandle&) = delete;
  ObserverHandle(ObserverHandle&&) noexcept;
  ObserverHandle& operator=(ObserverHandle&&) noexcept;
  void reset() noexcept;

 private:
  friend class Registry;
  ObserverHandle(std::weak_ptr<detail::ObserverHub>, TopicId, std::uint64_t);
  std::weak_ptr<detail::ObserverHub> hub_;
  TopicId root_{};
  std::uint64_t serial_{};
};

class Registry {
 public:
  class Lifetime {
   public:
    [[nodiscard]] bool alive() const noexcept { return alive_; }
   private:
    friend class Registry;
    bool alive_{true};
  };
  Registry();
  explicit Registry(Limits);
  ~Registry();
  Registry(const Registry&) = delete;
  Registry& operator=(const Registry&) = delete;
  Registry(Registry&&) = delete;
  Registry& operator=(Registry&&) = delete;

  // Invalid paths or exhausted representations leave all topics/partitions and
  // subscription filters unchanged. References/spans may invalidate on intern.
  TopicId intern(std::string_view path);
  [[nodiscard]] std::optional<TopicId> find(std::string_view path) const;
  [[nodiscard]] const Topic& get(TopicId) const;
  [[nodiscard]] const Partition& partition(PartitionId) const;
  [[nodiscard]] std::span<const Topic> all_topics() const noexcept { return topics_; }
  [[nodiscard]] std::span<const Partition> all_partitions() const noexcept { return partitions_; }
  [[nodiscard]] std::size_t topic_count() const noexcept { return topics_.size(); }
  [[nodiscard]] std::size_t partition_count() const noexcept { return partitions_.size(); }
  [[nodiscard]] const Limits& limits() const noexcept { return limits_; }
  [[nodiscard]] std::weak_ptr<const Lifetime> identity() const noexcept;
  [[nodiscard]] std::size_t observer_count() const noexcept;
  ObserverHandle observe(TopicId root, const std::shared_ptr<TopicObserver>&);

  static void validate_path(std::string_view);

 private:
  struct StringHash {
    using is_transparent = void;
    std::size_t operator()(std::string_view value) const noexcept;
  };
  using PathMap = std::unordered_map<std::string, TopicId, StringHash, std::equal_to<>>;
  Limits limits_;
  std::vector<Topic> topics_;
  std::vector<Partition> partitions_;
  PathMap paths_;
  std::shared_ptr<detail::ObserverHub> observers_;
  std::shared_ptr<Lifetime> lifetime_;
};

}  // namespace tiplog::topics
