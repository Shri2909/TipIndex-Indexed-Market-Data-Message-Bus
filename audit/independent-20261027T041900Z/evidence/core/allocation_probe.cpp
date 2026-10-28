#include "tiplog/engine/engine.hpp"

#include <array>
#include <cstdlib>
#include <iostream>
#include <new>

namespace {
long remaining = -1;
void allocation() {
  if (remaining == 0) { remaining = -1; throw std::bad_alloc(); }
  if (remaining > 0) --remaining;
}
void require(bool value, const char* text) { if (!value) throw std::runtime_error(text); }
}
[[gnu::noinline]] void* operator new(std::size_t bytes) {
  allocation();
  if (auto* p = std::malloc(bytes == 0 ? 1 : bytes)) return p;
  throw std::bad_alloc();
}
[[gnu::noinline]] void* operator new(std::size_t bytes, std::align_val_t align) {
  allocation();
  void* p{};
  if (::posix_memalign(&p, static_cast<std::size_t>(align), bytes == 0 ? 1 : bytes) == 0) return p;
  throw std::bad_alloc();
}
[[gnu::noinline]] void* operator new(std::size_t bytes, const std::nothrow_t&) noexcept {
  try { return ::operator new(bytes); } catch (...) { return nullptr; }
}
[[gnu::noinline]] void operator delete(void* p) noexcept { std::free(p); }
[[gnu::noinline]] void operator delete(void* p, std::size_t) noexcept { std::free(p); }
[[gnu::noinline]] void operator delete(void* p, std::align_val_t) noexcept { std::free(p); }
[[gnu::noinline]] void operator delete(void* p, std::size_t, std::align_val_t) noexcept { std::free(p); }
[[gnu::noinline]] void operator delete(void* p, const std::nothrow_t&) noexcept { std::free(p); }

using namespace tiplog;
EngineConfig config() {
  EngineConfig c;
  c.ring_bytes = 512;
  c.max_record_bytes = 256;
  c.index.blocks = 32;
  c.index.entries_per_block = 4;
  c.auto_max_index_fraction = 1;
  return c;
}

void registration() {
  long failures = 0;
  for (long nth = 0; nth != 200; ++nth) {
    Engine e(config());
    const auto old_topic = e.intern("r/s/selected/old");
    const auto sub = e.compile({{{Term::Subtree, "r/s/selected"}}});
    const auto topics = e.registry().topic_count(), parts = e.registry().partition_count();
    bool failed = false;
    remaining = nth;
    try { (void)e.intern("r/s/selected/new/deeper"); }
    catch (const std::bad_alloc&) { failed = true; }
    remaining = -1;
    if (!failed) { std::cout << "registry allocations=" << failures << " rollback/retry=passed\n"; return; }
    ++failures;
    require(e.registry().topic_count() == topics && e.registry().partition_count() == parts, "registry partial membership");
    require(!e.registry().find("r/s/selected/new"), "registry failed path persisted");
    require(sub.matches(old_topic), "registry failed mutation broke prior filter");
    const auto added = e.intern("r/s/selected/new/deeper");
    require(sub.matches(added), "registry retry filter missing");
    e.check_invariants();
  }
  throw std::runtime_error("registration allocation loop bound");
}

void publication() {
  long failures = 0;
  for (long nth = 0; nth != 100; ++nth) {
    auto c = config(); c.index.blocks = 1; c.index.entries_per_block = 1;
    Engine e(c);
    const auto a = e.intern("r/a/one");
    std::array<std::byte, 16> bytes{};
    for (unsigned i = 0; i < bytes.size(); ++i) bytes[i] = static_cast<std::byte>(i * 13 + 7);
    e.publish(a, bytes);
    const auto b = e.intern("r/b/two");
    const auto borrowed = e.ring().at(e.ring().tail_pos()).payload;
    const auto before = e.stats();
    const auto stats = e.ring().stats();
    const auto postings = e.index()->entries();
    const auto gauges = e.index()->stats().gauges;
    bool failed = false;
    remaining = nth;
    try { (void)e.publish(b, borrowed); }
    catch (const std::bad_alloc&) { failed = true; }
    remaining = -1;
    if (failed) {
      ++failures;
      const auto after = e.stats();
      require(before.head_pos == after.head_pos && before.tail_pos == after.tail_pos && before.head_seq == after.head_seq && before.tail_seq == after.tail_seq, "publish failure changed ring range");
      require(e.ring().stats() == stats && e.index()->entries() == postings && e.index()->stats().gauges == gauges, "publish failure changed membership/accounting");
      e.check_invariants();
      e.publish(b, borrowed);
    }
    const auto item = e.ring().at(e.ring().tail_pos());
    require(item.seq == 2 && item.topic == b && std::ranges::equal(item.payload, bytes), "alias/pressure retry lost payload");
    e.check_invariants();
    if (!failed) { std::cout << "pressure+alias publication allocations=" << failures << " rollback/retry=passed\n"; return; }
  }
  throw std::runtime_error("publication allocation loop bound");
}

void poll(bool live, ReplayMode mode, MergeKernel kernel, unsigned form) {
  long failures = 0;
  for (long nth = 0; nth != 100; ++nth) {
    Engine e(config());
    const auto a = e.intern("r/a/match"), b = e.intern("r/b/match"), reject = e.intern("r/a/reject");
    const auto sub = e.compile({{{Term::Exact, "r/a/match"}, {Term::Exact, "r/b/match"}}});
    e.publish(a, {}); e.publish(reject, {}); e.publish(b, {});
    std::vector<Seq> actual;
    bool failed = false;
    const auto collect = [&](const std::vector<Delivered>& out) { for (const auto& item : out) actual.push_back(item.seq); };
    const auto execute = [&](auto& reader) {
      std::vector<Delivered> out;
      remaining = nth;
      try {
        if constexpr (std::is_same_v<std::remove_cvref_t<decltype(reader)>, Tail>) {
          if (form == 0) (void)reader.poll(100, out);
          else (void)reader.poll(PollLimits{100, form == 1 ? std::nullopt : std::optional<std::uint64_t>{100}}, out);
        } else {
          if (form == 0) (void)reader.next_batch(100, out);
          else (void)reader.next_batch(PollLimits{100, form == 1 ? std::nullopt : std::optional<std::uint64_t>{100}}, out);
        }
      } catch (const std::bad_alloc&) { failed = true; }
      remaining = -1;
      collect(out);
      for (unsigned retry = 0; retry < 5 && (failed || reader.status() == Status::More); ++retry) {
        Status status;
        if constexpr (std::is_same_v<std::remove_cvref_t<decltype(reader)>, Tail>) status = reader.poll(100, out);
        else status = reader.next_batch(100, out);
        collect(out);
        if (status == Status::Done) break;
        require(status != Status::Error, "allocation retry latched unexpected error");
      }
      require(reader.status() == Status::Done, "allocation retry did not complete");
    };
    if (live) {
      auto reader = e.open_tail(sub, 0, mode, kernel);
      e.publish(a, {}); e.publish(reject, {}); e.publish(b, {});
      execute(reader);
      require(actual == std::vector<Seq>({1,3,4,6}), "Tail retry output mismatch");
    } else {
      auto reader = e.open_replay(sub, 0, mode, kernel);
      execute(reader);
      require(actual == std::vector<Seq>({1,3}), "Replay retry output mismatch");
    }
    e.check_invariants();
    if (!failed) {
      std::cout << (live ? "Tail" : "Replay") << " mode=" << static_cast<unsigned>(mode)
                << " kernel=" << static_cast<unsigned>(kernel) << " api=" << form
                << " allocations=" << failures << " prefix/retry=passed\n";
      return;
    }
    ++failures;
  }
  throw std::runtime_error("poll allocation loop bound");
}

int main() {
  registration(); publication();
  for (bool live : {false, true})
    for (auto mode : {ReplayMode::Scan, ReplayMode::Indexed, ReplayMode::Auto})
      for (auto kernel : {MergeKernel::StdPQ, MergeKernel::BinHeap, MergeKernel::Quad, MergeKernel::Loser})
        for (unsigned form : {0U, 1U, 2U}) poll(live, mode, kernel, form);
}
