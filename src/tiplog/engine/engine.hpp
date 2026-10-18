#pragma once

#include "tiplog/ring/ring.hpp"
#include "tiplog/subs/compiled.hpp"
#include "tiplog/index/index.hpp"

#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>

namespace tiplog {

class PoolExhausted : public std::runtime_error {
public:
  PoolExhausted() : std::runtime_error("index block pool exhausted") {}
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
};
struct EngineStats {
  LogPos head_pos{};
  LogPos tail_pos{};
  Seq head_seq{};
  Seq tail_seq{};
};

namespace detail {
struct EngineLifetime {
  bool alive{true};
  std::size_t active_replays{};
};
} // namespace detail
class Engine;
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
  [[nodiscard]] std::optional<ResumeCheckpoint> checkpoint() const noexcept {
    return checkpoint_;
  }

private:
  friend class Engine;
  Replay(Engine &, const subs::CompiledSubscription &, Seq,
         std::optional<ResumeCheckpoint>, ReplayMode);
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
  std::optional<PartitionId> partition_;
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
  EngineConfig config_;
  topics::Registry registry_;
  ring::Ring ring_;
  std::unique_ptr<index::Index> index_;
  std::uint64_t retained_data_count_{};
  std::shared_ptr<detail::EngineLifetime> lifetime_{
      std::make_shared<detail::EngineLifetime>()};
};

} // namespace tiplog
