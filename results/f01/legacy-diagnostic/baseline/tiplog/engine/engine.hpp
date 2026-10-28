#pragma once

#include "tiplog/ring/ring.hpp"
#include "tiplog/subs/compiled.hpp"
#include "tiplog/index/index.hpp"
#include "tiplog/merge/kernels.hpp"

#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>

namespace tiplog {

class PoolExhausted : public std::runtime_error {
public:
  PoolExhausted() : std::runtime_error("index block pool exhausted") {}
};
class InvalidRange : public std::invalid_argument {
public:
  InvalidRange() : std::invalid_argument("tail start is beyond the current head") {}
};

struct EngineConfig {
  std::size_t ring_bytes{4096};
  std::size_t max_record_bytes{2048};
  std::uint32_t ckpt_log2{8};
  LogPos position_limit{LogPos{1} << 51};
  Seq sequence_limit{std::numeric_limits<Seq>::max()};
  topics::Limits registry_limits{};
  // Generic records can occupy 16 bytes. A minimum of 32 is an explicitly
  // enforced workload configuration, never inferred from an input filename.
  bool index_enabled{true};
  index::Config index{};
  PoolPolicy pool_policy{PoolPolicy::ForceEvict};
  std::size_t minimum_record_bytes{16};
  // Explicit initial policy values, not measured or calibrated thresholds.
  std::uint32_t auto_max_partitions{64};
  double auto_max_index_fraction{0.25};
};
struct EngineStats {
  LogPos head_pos{};
  LogPos tail_pos{};
  Seq head_seq{};
  Seq tail_seq{};
};
// Exact traversal work, not hardware events. Bytes include complete DATA/PAD
// spans decoded by the replay loop. Seek metadata/header work is separately
// reported; entries_visited counts postings selected from the merge kernel.
struct ReplayWork {
  std::uint64_t bytes_inspected{};
  std::uint64_t entries_visited{};
  std::uint64_t records_fetched{};
  std::uint64_t delivered{};
  std::uint64_t pads_inspected{};
  std::uint64_t seek_data_examined{};
  std::uint64_t seek_pads_examined{};
  std::uint64_t index_seeks{};
  bool operator==(const ReplayWork &) const = default;
};

namespace detail {
struct EngineLifetime {
  bool alive{true};
  std::size_t active_replays{};
};
} // namespace detail
class Engine;
class Tail;
class Replay {
public:
  Replay(const Replay &) = delete;
  Replay &operator=(const Replay &) = delete;
  ~Replay();
  Replay(Replay &&) noexcept;
  Replay &operator=(Replay &&) noexcept;
  // Outputs borrow ring storage until the next engine mutation. No engine
  // mutation may interleave inside this single-threaded batch operation.
  Status next_batch(std::size_t max, std::vector<Delivered> &out);
  [[nodiscard]] std::optional<ReplayError> error() const noexcept {
    return error_;
  }
  [[nodiscard]] Seq upper_seq() const noexcept { return upper_seq_; }
  [[nodiscard]] LogPos upper_pos() const noexcept { return upper_pos_; }
  [[nodiscard]] Status status() const noexcept { return status_; }
  [[nodiscard]] ReplayMode effective_mode() const noexcept { return mode_; }
  [[nodiscard]] ReplayWork work() const noexcept { return work_; }
  [[nodiscard]] std::size_t selected_partition_count() const noexcept {
    return partitions_.size();
  }
  [[nodiscard]] std::optional<ResumeCheckpoint> checkpoint() const noexcept {
    return checkpoint_;
  }

private:
  friend class Engine;
  friend class Tail;
  Replay(Engine &, const subs::CompiledSubscription &, Seq,
         std::optional<ResumeCheckpoint>, ReplayMode, MergeKernel);
  Status next_batch_into(std::size_t max, std::vector<Delivered> &out);
  void release() noexcept;
  Engine *engine_;
  std::weak_ptr<detail::EngineLifetime> lifetime_;
  subs::CompiledSubscription sub_;
  Seq requested_after_{};
  Seq last_delivered_{};
  Seq upper_seq_{};
  LogPos upper_pos_{};
  Status status_{Status::More};
  std::optional<ReplayError> error_;
  std::optional<ResumeCheckpoint> checkpoint_;
  ReplayMode mode_{ReplayMode::Scan};
  MergeKernel kernel_{MergeKernel::StdPQ};
  std::vector<PartitionId> partitions_;
  ReplayWork work_{};
};

// A live reader is a chain of completed captured ranges. Done means caught up
// at this call; a subsequent positive poll may capture newly published DATA.
class Tail {
public:
  Tail(const Tail &) = delete;
  Tail &operator=(const Tail &) = delete;
  Tail(Tail &&) noexcept = default;
  Tail &operator=(Tail &&) noexcept = default;
  Status poll(std::size_t max, std::vector<Delivered> &out);
  [[nodiscard]] Status status() const noexcept { return status_; }
  [[nodiscard]] std::optional<ReplayError> error() const noexcept { return error_; }
  [[nodiscard]] std::optional<ResumeCheckpoint> checkpoint() const noexcept {
    return checkpoint_;
  }
  [[nodiscard]] Seq upper_seq() const noexcept { return replay_.upper_seq(); }
  [[nodiscard]] LogPos upper_pos() const noexcept { return replay_.upper_pos(); }
  [[nodiscard]] ReplayMode effective_mode() const noexcept {
    return replay_.effective_mode();
  }
private:
  friend class Engine;
  Tail(Engine &, const subs::CompiledSubscription &, Seq, ReplayMode, MergeKernel);
  Engine *engine_;
  std::weak_ptr<detail::EngineLifetime> lifetime_;
  subs::CompiledSubscription sub_;
  ReplayMode mode_;
  MergeKernel kernel_;
  Seq requested_after_;
  Seq last_delivered_;
  Replay replay_;
  Status status_;
  std::optional<ReplayError> error_;
  std::optional<ResumeCheckpoint> checkpoint_;
};

class Engine {
public:
  explicit Engine(const EngineConfig &config = {});
  ~Engine();
  Engine(const Engine &) = delete;
  Engine &operator=(const Engine &) = delete;
  Engine(Engine &&) = delete;
  Engine &operator=(Engine &&) = delete;
  TopicId intern(std::string_view path) { return registry_.intern(path); }
  [[nodiscard]] subs::CompiledSubscription
  compile(const SubscriptionSpec &spec) {
    return subs::compile(registry_, spec);
  }
  Seq publish(TopicId topic, std::span<const std::byte> payload);
  [[nodiscard]] Replay open_replay(const subs::CompiledSubscription &,
                                   Seq after_seq,
                                   ReplayMode mode = ReplayMode::Scan,
                                   MergeKernel kernel = MergeKernel::StdPQ);
  [[nodiscard]] Tail open_tail(const subs::CompiledSubscription &, Seq after_seq,
                              ReplayMode mode = ReplayMode::Scan,
                              MergeKernel kernel = MergeKernel::StdPQ);
  [[nodiscard]] Replay open_replay(const subs::CompiledSubscription &,
                                   ResumeCheckpoint,
                                   ReplayMode mode = ReplayMode::Scan,
                                   MergeKernel kernel = MergeKernel::StdPQ);
  [[nodiscard]] const topics::Registry &registry() const noexcept {
    return registry_;
  }
  [[nodiscard]] const ring::Ring &ring() const noexcept { return ring_; }
  [[nodiscard]] const index::Index *index() const noexcept { return index_.get(); }
  [[nodiscard]] const EngineConfig &config() const noexcept { return config_; }
  [[nodiscard]] EngineStats stats() const noexcept;
  void check_invariants() const;

private:
  friend class Replay;
  friend class Tail;
  EngineConfig config_;
  topics::Registry registry_;
  ring::Ring ring_;
  std::unique_ptr<index::Index> index_;
  std::uint64_t retained_data_count_{};
  std::shared_ptr<detail::EngineLifetime> lifetime_{
      std::make_shared<detail::EngineLifetime>()};
};

} // namespace tiplog
