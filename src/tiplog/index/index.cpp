#include "tiplog/index/index.hpp"

#include <algorithm>
#include <bit>
#include <cassert>
#include <exception>
#include <tuple>

namespace tiplog::index {
namespace {
[[noreturn]] void broken(const char *text) { throw std::logic_error(text); }
void require(bool condition, const char *text) {
  if (!condition)
    broken(text);
}
std::size_t checked_entries(const Config &c) {
  if (c.blocks == 0 || !std::has_single_bit(c.entries_per_block) ||
      c.delta_bits == 0 || c.delta_bits > 32) {
    throw std::invalid_argument("invalid index block/delta configuration");
  }
  const auto count = static_cast<std::uint64_t>(c.blocks) * c.entries_per_block;
  if (count > std::vector<std::uint32_t>{}.max_size() ||
      c.blocks > std::vector<BlockMeta>{}.max_size()) {
    throw std::length_error("index allocation size overflow");
  }
  return static_cast<std::size_t>(count);
}
std::uint64_t saturated_add(std::uint64_t a, std::uint64_t b) noexcept {
  return b > std::numeric_limits<std::uint64_t>::max() - a
             ? std::numeric_limits<std::uint64_t>::max()
             : a + b;
}
} // namespace

Index::Index(const Config &config) : config_(config) {
  const auto count = checked_entries(config);
  meta_.resize(config.blocks);
  deltas_.resize(count);
  sealed_.resize(config.blocks);
  heap_.reserve(config.blocks);
  for (std::uint32_t b = 0; b < config.blocks; ++b) {
    meta_[b].next = b + 1 < config.blocks ? b + 1 : none;
  }
  free_head_ = 0;
  gauges_.free_blocks = config.blocks;
  gauges_.free_block_slots = count;
  near_generation_limit_ = config.generation_limit == 0;
}
bool Index::heap_greater(const HeapNode &a, const HeapNode &b) noexcept {
  return std::tie(a.last, a.block, a.generation) >
         std::tie(b.last, b.block, b.generation);
}
std::uint32_t Index::last_block(PartitionId p) const noexcept {
  if (p >= partitions_.size() || partitions_[p].ids.empty())
    return none;
  return partitions_[p].ids.back();
}
LogPos Index::decode(std::uint32_t b, std::uint32_t e) const noexcept {
  return meta_[b].base_pos +
         (static_cast<LogPos>(
              deltas_[static_cast<std::size_t>(b) * config_.entries_per_block +
                      e])
          << 3U);
}
bool Index::has_expired_open(PartitionId p, LogPos tail) const noexcept {
  const auto b = last_block(p);
  return b != none && !sealed_[b] && meta_[b].last_pos < tail;
}
bool Index::needs_new_block(PartitionId p, LogPos pos,
                            LogPos tail) const noexcept {
  const auto b = last_block(p);
  if (b == none || meta_[b].last_pos < tail || sealed_[b])
    return true;
  const auto delta = (pos - meta_[b].base_pos) >> 3U;
  return delta >= (std::uint64_t{1} << config_.delta_bits);
}
void Index::reserve_partition_append(PartitionId p) {
  auto &state = partitions_[p];
  if (state.ids.size() == state.ids.capacity()) {
    // A dead prefix is compacted without allocation during commit. Reserving
    // now is deliberately conservative; no logical chain is modified here.
    const auto maximum = state.ids.max_size();
    if (state.ids.size() == maximum)
      throw std::length_error("partition list full");
    const auto grown = state.ids.capacity() > maximum / 2
                           ? maximum
                           : std::max<std::size_t>(4, state.ids.capacity() * 2);
    state.ids.reserve(std::max(state.ids.size() + 1, grown));
  }
}
void Index::preflight_generations(LogPos tail, PartitionId target, bool sweep) {
  if (!near_generation_limit_)
    return;
  ++counters_.generation_preflight_scans;
  for (std::uint32_t b = 0; b < meta_.size(); ++b) {
    const auto &m = meta_[b];
    if (m.partition == none || m.last_pos >= tail)
      continue;
    if ((sealed_[b] || sweep || m.partition == target) &&
        m.gen == config_.generation_limit) {
      throw RepresentationLimit(
          "index generation exhausted before publication");
    }
  }
}
Preparation Index::prepare_append(PartitionId partition, LogPos pos,
                                  LogPos prospective_tail,
                                  std::size_t partition_count,
                                  std::uint64_t data_evictions) {
  if (partition == none || partition >= partition_count ||
      partition_count > none || (pos & 7U) != 0 ||
      (prospective_tail & 7U) != 0 || prospective_tail < tail_ ||
      prospective_tail > pos || (has_appended_ && pos <= last_appended_)) {
    throw std::invalid_argument("invalid index append range/partition");
  }
  // New empty control states are preparatory backing storage, not block
  // membership. A later exception may leave honest extra reserved capacity.
  if (partition_count > partitions_.size())
    partitions_.resize(partition_count);
  const bool needs_block = needs_new_block(partition, pos, prospective_tail);
  bool sweep = config_.sweep_evictions != 0 &&
               saturated_add(evictions_since_sweep_, data_evictions) >=
                   config_.sweep_evictions;
  bool available = gauges_.free_blocks != 0 ||
                   (!heap_.empty() && heap_.front().last < prospective_tail) ||
                   has_expired_open(partition, prospective_tail);
  if (needs_block && !available) {
    // Pressure includes a complete expired-open sweep before any retention
    // shortening. Only the pressure/cadence path scans partition controls.
    sweep = true;
    LogPos minimum_last =
        heap_.empty() ? std::numeric_limits<LogPos>::max() : heap_.front().last;
    for (PartitionId p = 0; p < partitions_.size(); ++p) {
      const auto b = last_block(p);
      if (b == none || sealed_[b])
        continue;
      if (meta_[b].last_pos < prospective_tail)
        available = true;
      minimum_last = std::min(minimum_last, meta_[b].last_pos);
    }
    if (!available) {
      require(minimum_last != std::numeric_limits<LogPos>::max(),
              "nonempty pool has no pressure candidate");
      return NeedTailThrough{minimum_last};
    }
  }
  preflight_generations(prospective_tail, partition, sweep);
  if (needs_block)
    reserve_partition_append(partition);
  PreparedAppend prepared;
  prepared.owner_ = this;
  prepared.version_ = version_;
  prepared.partition_ = partition;
  prepared.pos_ = pos;
  prepared.tail_ = prospective_tail;
  prepared.evictions_ = data_evictions;
  prepared.sweep_ = sweep;
  prepared.needs_block_ = needs_block;
  return prepared;
}

void Index::free_front(PartitionId p) noexcept {
  auto &state = partitions_[p];
  assert(state.first < state.ids.size());
  const auto b = state.ids[state.first];
  auto &m = meta_[b];
  assert(m.partition == p && m.gen < config_.generation_limit);
  const auto slack = config_.entries_per_block - m.count;
  if (sealed_[b]) {
    --gauges_.sealed_blocks;
    gauges_.sealed_partial_slack -= slack;
  } else {
    gauges_.open_slack -= slack;
  }
  gauges_.allocated_entries -= m.count;
  --gauges_.allocated_blocks;
  ++gauges_.free_blocks;
  gauges_.free_block_slots += config_.entries_per_block;
  ++counters_.frees;
  ++m.gen;
  near_generation_limit_ =
      near_generation_limit_ || m.gen == config_.generation_limit;
  m.partition = none;
  m.count = 0;
  m.base_pos = 0;
  m.last_pos = 0;
  m.next = free_head_;
  free_head_ = b;
  sealed_[b] = 0;
  ++state.first;
  if (state.first == state.ids.size()) {
    state.ids.clear();
    state.first = 0;
  }
}
void Index::reclaim(LogPos tail) noexcept {
  while (!heap_.empty() && heap_.front().last < tail) {
    const auto node = heap_.front();
    std::pop_heap(heap_.begin(), heap_.end(), heap_greater);
    heap_.pop_back();
    ++counters_.heap_pops;
    assert(node.block < meta_.size());
    const auto &m = meta_[node.block];
    assert(m.gen == node.generation && m.last_pos == node.last &&
           sealed_[node.block]);
    assert(partitions_[m.partition].ids[partitions_[m.partition].first] ==
           node.block);
    free_front(m.partition);
  }
}
void Index::sweep_open(LogPos tail) noexcept {
  ++counters_.sweeps;
  counters_.swept_partitions += partitions_.size();
  for (PartitionId p = 0; p < partitions_.size(); ++p) {
    if (!has_expired_open(p, tail))
      continue;
    assert(partitions_[p].ids.size() - partitions_[p].first == 1);
    free_front(p);
  }
}
void Index::seal(std::uint32_t b) noexcept {
  assert(!sealed_[b] && heap_.size() < heap_.capacity());
  const auto &m = meta_[b];
  const auto slack = config_.entries_per_block - m.count;
  gauges_.open_slack -= slack;
  gauges_.sealed_partial_slack += slack;
  ++gauges_.sealed_blocks;
  ++counters_.seals;
  ++counters_.heap_pushes;
  sealed_[b] = 1;
  heap_.push_back({m.last_pos, b, m.gen});
  std::push_heap(heap_.begin(), heap_.end(), heap_greater);
}
std::uint32_t Index::allocate(PartitionId p, LogPos pos) noexcept {
  assert(free_head_ != none);
  const auto b = free_head_;
  auto &m = meta_[b];
  free_head_ = m.next;
  m.base_pos = pos;
  m.last_pos = pos;
  m.count = 0;
  m.partition = p;
  m.next = none;
  auto &state = partitions_[p];
  if (!state.ids.empty())
    meta_[state.ids.back()].next = b;
  // Drop a dead prefix only when useful; ids/generations in cursors remain
  // stable because no cursor stores vector offsets or iterators.
  if (state.first != 0 && state.first >= state.ids.size() / 2) {
    std::move(state.ids.begin() + static_cast<std::ptrdiff_t>(state.first),
              state.ids.end(), state.ids.begin());
    state.ids.resize(state.ids.size() - state.first);
    state.first = 0;
  }
  assert(state.ids.size() < state.ids.capacity());
  state.ids.push_back(b);
  --gauges_.free_blocks;
  gauges_.free_block_slots -= config_.entries_per_block;
  ++gauges_.allocated_blocks;
  gauges_.open_slack += config_.entries_per_block;
  ++counters_.allocations;
  high_water_ = std::max(high_water_, gauges_.allocated_blocks);
  return b;
}
void Index::commit(PreparedAppend &&prepared,
                   std::uint64_t retained_data_count) noexcept {
  if (prepared.owner_ != this || prepared.version_ != version_)
    std::terminate();
  const auto p = prepared.partition_;
  reclaim(prepared.tail_);
  if (prepared.sweep_) {
    sweep_open(prepared.tail_);
    evictions_since_sweep_ = 0;
  } else {
    evictions_since_sweep_ =
        saturated_add(evictions_since_sweep_, prepared.evictions_);
    if (has_expired_open(p, prepared.tail_)) {
      assert(partitions_[p].ids.size() - partitions_[p].first == 1);
      free_front(p);
    }
  }
  auto b = last_block(p);
  if (prepared.needs_block_) {
    if (b != none && !sealed_[b])
      seal(b);
    b = allocate(p, prepared.pos_);
  }
  assert(b != none && !sealed_[b]);
  auto &m = meta_[b];
  const auto delta = (prepared.pos_ - m.base_pos) >> 3U;
  assert(delta < (std::uint64_t{1} << config_.delta_bits));
  assert(m.count < config_.entries_per_block);
  deltas_[static_cast<std::size_t>(b) * config_.entries_per_block + m.count] =
      static_cast<std::uint32_t>(delta);
  ++m.count;
  m.last_pos = prepared.pos_;
  ++gauges_.allocated_entries;
  --gauges_.open_slack;
  if (m.count == config_.entries_per_block)
    seal(b);
  gauges_.live_entries = retained_data_count;
  assert(gauges_.allocated_entries >= retained_data_count);
  gauges_.expired_allocated_entries =
      gauges_.allocated_entries - retained_data_count;
  tail_ = prepared.tail_;
  last_appended_ = prepared.pos_;
  has_appended_ = true;
  ++version_;
  prepared.owner_ = nullptr;
}

Cursor Index::seek(PartitionId p, LogPos lower_pos) const {
  if (p >= partitions_.size())
    return {};
  lower_pos = std::max(lower_pos, tail_);
  const auto &state = partitions_[p];
  auto first = state.first;
  auto end = state.ids.size();
  while (first < end) {
    const auto mid = first + (end - first) / 2;
    if (meta_[state.ids[mid]].last_pos < lower_pos)
      first = mid + 1;
    else
      end = mid;
  }
  if (first == state.ids.size())
    return {};
  const auto b = state.ids[first];
  std::uint32_t lo = 0;
  auto hi = meta_[b].count;
  while (lo < hi) {
    const auto mid = lo + (hi - lo) / 2;
    if (decode(b, mid) < lower_pos)
      lo = mid + 1;
    else
      hi = mid;
  }
  assert(lo < meta_[b].count);
  return {b, meta_[b].gen, lo, decode(b, lo)};
}
void Index::validate_cursor(const Cursor &c, LogPos tail) const {
  // The cached-position guard deliberately precedes every metadata access.
  if (!c.valid() || c.pos < tail)
    throw StaleCursor("expired index cursor position");
  if (c.block >= meta_.size())
    throw StaleCursor("invalid index cursor block");
  const auto &m = meta_[c.block];
  if (m.partition == none || m.gen != c.generation || c.entry >= m.count ||
      decode(c.block, c.entry) != c.pos)
    throw StaleCursor("recycled index cursor");
}
bool Index::advance(Cursor &c, LogPos current_tail) const {
  validate_cursor(c, std::max(current_tail, tail_));
  const auto &m = meta_[c.block];
  if (c.entry + 1 < m.count) {
    ++c.entry;
    c.pos = decode(c.block, c.entry);
    return true;
  }
  if (m.next == none) {
    c = {};
    return false;
  }
  const auto b = m.next;
  assert(b < meta_.size() && meta_[b].partition == m.partition &&
         meta_[b].count != 0);
  c = {b, meta_[b].gen, 0, decode(b, 0)};
  return true;
}
std::uint64_t Index::estimate_count(PartitionId p, LogPos lower,
                                    LogPos upper) const noexcept {
  lower = std::max(lower, tail_);
  if (p >= partitions_.size() || lower >= upper)
    return 0;
  const auto &state = partitions_[p];
  const auto begin =
      state.ids.begin() + static_cast<std::ptrdiff_t>(state.first);
  const auto first = std::lower_bound(
      begin, state.ids.end(), lower,
      [this](std::uint32_t b, LogPos pos) { return meta_[b].last_pos < pos; });
  const auto end = std::lower_bound(
      first, state.ids.end(), upper,
      [this](std::uint32_t b, LogPos pos) { return meta_[b].base_pos < pos; });
  std::uint64_t result = 0;
  for (auto it = first; it != end; ++it) {
    const auto block = *it;
    const auto& meta = meta_[block];
    auto lower_entry = [this, block, &meta](LogPos position) {
      std::uint32_t left = 0, right = meta.count;
      while (left < right) {
        const auto middle = left + (right - left) / 2;
        if (decode(block, middle) < position) left = middle + 1;
        else right = middle;
      }
      return left;
    };
    const auto start = meta.base_pos < lower ? lower_entry(lower) : 0;
    const auto stop = meta.last_pos >= upper ? lower_entry(upper) : meta.count;
    result += stop - start;
  }
  return result;
}
Memory Index::memory() const {
  Memory result;
  result.metadata_reserved_bytes = meta_.capacity() * sizeof(BlockMeta);
  result.entries_reserved_bytes = deltas_.capacity() * sizeof(std::uint32_t);
  result.sealed_flags_reserved_bytes =
      sealed_.capacity() * sizeof(std::uint8_t);
  result.heap_used_bytes = heap_.size() * sizeof(HeapNode);
  result.heap_reserved_bytes = heap_.capacity() * sizeof(HeapNode);
  result.partition_state_used_bytes = partitions_.size() * sizeof(Partition);
  result.partition_state_reserved_bytes =
      partitions_.capacity() * sizeof(Partition);
  for (const auto &state : partitions_) {
    result.partition_list_used_bytes +=
        (state.ids.size() - state.first) * sizeof(std::uint32_t);
    result.partition_list_reserved_bytes +=
        state.ids.capacity() * sizeof(std::uint32_t);
  }
  result.control_bytes = sizeof(Index);
  result.reserved_bytes =
      result.metadata_reserved_bytes + result.entries_reserved_bytes +
      result.sealed_flags_reserved_bytes + result.heap_reserved_bytes +
      result.partition_state_reserved_bytes +
      result.partition_list_reserved_bytes + result.control_bytes;
  return result;
}
Stats Index::stats() const {
  return {gauges_, memory(), counters_, high_water_, tail_};
}
std::vector<Posting> Index::entries() const {
  std::vector<Posting> result;
  result.reserve(static_cast<std::size_t>(gauges_.allocated_entries));
  for (PartitionId p = 0; p < partitions_.size(); ++p) {
    const auto &state = partitions_[p];
    for (auto i = state.first; i < state.ids.size(); ++i) {
      const auto b = state.ids[i];
      for (std::uint32_t e = 0; e < meta_[b].count; ++e)
        result.push_back({p, decode(b, e), b, meta_[b].gen});
    }
  }
  return result;
}
std::vector<Posting> Index::retained_entries(LogPos tail) const {
  auto result = entries();
  std::erase_if(result,
                [tail](const Posting &posting) { return posting.pos < tail; });
  return result;
}

Recount Index::recount(LogPos tail) const {
  Recount result;
  auto &g = result.gauges;
  std::vector<std::uint8_t> visited(meta_.size());
  for (auto b = free_head_; b != none; b = meta_[b].next) {
    require(b < meta_.size(), "free-list block out of range");
    require(!visited[b] && meta_[b].partition == none,
            "duplicate/owned free block");
    visited[b] = 1;
    require(meta_[b].count == 0 && !sealed_[b],
            "free block retains membership");
    ++g.free_blocks;
    g.free_block_slots += config_.entries_per_block;
  }
  std::vector<std::uint8_t> heap_members(meta_.size());
  for (std::size_t i = 0; i < heap_.size(); ++i) {
    const auto &node = heap_[i];
    require(node.block < meta_.size(), "heap block out of range");
    const auto &m = meta_[node.block];
    require(!heap_members[node.block] && sealed_[node.block] &&
                m.partition != none && node.generation == m.gen &&
                node.last == m.last_pos,
            "heap identity/generation mismatch");
    require(node.last >= tail, "expired sealed block survived reclaim");
    heap_members[node.block] = 1;
    if (i != 0)
      require(!heap_greater(heap_[(i - 1) / 2], node), "expiry heap order");
  }
  for (PartitionId p = 0; p < partitions_.size(); ++p) {
    const auto &state = partitions_[p];
    require(state.first <= state.ids.size(), "partition live offset");
    bool have_previous = false;
    LogPos previous = 0;
    for (auto i = state.first; i < state.ids.size(); ++i) {
      const auto b = state.ids[i];
      require(b < meta_.size() && !visited[b],
              "duplicate/out-of-range owned block");
      visited[b] = 1;
      const auto &m = meta_[b];
      require(m.partition == p && m.count > 0 &&
                  m.count <= config_.entries_per_block,
              "block ownership/count");
      require(m.next == (i + 1 < state.ids.size() ? state.ids[i + 1] : none),
              "chain and seek-list disagree");
      const bool expected_sealed =
          m.count == config_.entries_per_block || i + 1 < state.ids.size();
      require(static_cast<bool>(sealed_[b]) == expected_sealed &&
                  static_cast<bool>(heap_members[b]) == expected_sealed,
              "sealed membership");
      if (!expected_sealed && m.last_pos < tail)
        require(state.ids.size() - state.first == 1,
                "expired open is not sole block");
      ++g.allocated_blocks;
      if (expected_sealed) {
        ++g.sealed_blocks;
        g.sealed_partial_slack += config_.entries_per_block - m.count;
      } else {
        g.open_slack += config_.entries_per_block - m.count;
      }
      for (std::uint32_t e = 0; e < m.count; ++e) {
        const auto delta =
            deltas_[static_cast<std::size_t>(b) * config_.entries_per_block +
                    e];
        require(delta < (std::uint64_t{1} << config_.delta_bits),
                "entry delta range");
        require(e != 0 || delta == 0, "first entry is not block base");
        require(m.base_pos <= std::numeric_limits<LogPos>::max() -
                                  (static_cast<LogPos>(delta) << 3U),
                "entry decode overflow");
        const auto pos = m.base_pos + (static_cast<LogPos>(delta) << 3U);
        require(pos >= m.base_pos && pos <= m.last_pos && (pos & 7U) == 0,
                "entry outside block range");
        require(!have_previous || previous < pos,
                "partition positions not increasing");
        require(!has_appended_ || pos <= last_appended_,
                "entry above published position");
        have_previous = true;
        previous = pos;
        ++g.allocated_entries;
        if (pos >= tail)
          ++g.live_entries;
        else
          ++g.expired_allocated_entries;
        if (e + 1 == m.count)
          require(pos == m.last_pos, "last entry metadata mismatch");
      }
    }
  }
  require(std::all_of(visited.begin(), visited.end(),
                      [](auto v) { return v != 0; }),
          "unreachable pool block");
  require(g.allocated_blocks + g.free_blocks == config_.blocks,
          "pool conservation");
  require(g.live_entries + g.expired_allocated_entries + g.open_slack +
                  g.sealed_partial_slack + g.free_block_slots ==
              deltas_.size(),
          "slot conservation");
  // Deliberately recompute backing capacities here rather than calling the
  // incremental memory() helper used by stats(). Used list bytes exclude dead
  // prefixes; their full allocation remains in reserved bytes.
  auto &memory = result.memory;
  memory.metadata_reserved_bytes = meta_.capacity() * 32;
  memory.entries_reserved_bytes = deltas_.capacity() * 4;
  memory.sealed_flags_reserved_bytes = sealed_.capacity();
  memory.heap_used_bytes = heap_.size() * 16;
  memory.heap_reserved_bytes = heap_.capacity() * 16;
  memory.partition_state_used_bytes = partitions_.size() * sizeof(Partition);
  memory.partition_state_reserved_bytes =
      partitions_.capacity() * sizeof(Partition);
  for (const auto &state : partitions_) {
    memory.partition_list_used_bytes += (state.ids.size() - state.first) * 4;
    memory.partition_list_reserved_bytes += state.ids.capacity() * 4;
  }
  memory.control_bytes = sizeof(Index);
  memory.reserved_bytes =
      memory.metadata_reserved_bytes + memory.entries_reserved_bytes +
      memory.sealed_flags_reserved_bytes + memory.heap_reserved_bytes +
      memory.partition_state_reserved_bytes +
      memory.partition_list_reserved_bytes + memory.control_bytes;
  return result;
}
void Index::check_invariants(LogPos tail) const {
  require(tail == tail_, "index/ring tail disagreement");
  const auto counted = recount(tail);
  require(counted.gauges == gauges_,
          "incremental index gauges differ from recount");
  require(counted.memory == memory(),
          "incremental memory differs from recount");
  require(high_water_ >= gauges_.allocated_blocks &&
              high_water_ <= config_.blocks,
          "allocation high-water out of range");
  require(counters_.allocations - counters_.frees == gauges_.allocated_blocks,
          "allocation/free counters disagree");
  require(counters_.heap_pushes - counters_.heap_pops == gauges_.sealed_blocks,
          "heap counters disagree");
}
std::uint32_t Index::sizing_blocks(std::uint64_t ring_bytes,
                                   std::uint32_t minimum_record_bytes,
                                   std::uint32_t block_entries,
                                   std::uint64_t partition_bound) {
  if ((minimum_record_bytes != 16 && minimum_record_bytes != 32) ||
      !std::has_single_bit(block_entries) ||
      ring_bytes >= (std::uint64_t{1} << 35U))
    throw std::invalid_argument(
        "sizing requires generic16/enforced32 and production span");
  const auto records = ring_bytes / minimum_record_bytes;
  const auto packed =
      records / block_entries + (records % block_entries != 0 ? 1U : 0U);
  if (partition_bound > (static_cast<std::uint64_t>(none) - 1U) / 2U ||
      packed > static_cast<std::uint64_t>(none) - (2 * partition_bound + 1))
    throw RepresentationLimit("sizing block count exceeds u32");
  return static_cast<std::uint32_t>(packed + 2 * partition_bound + 1);
}
} // namespace tiplog::index
