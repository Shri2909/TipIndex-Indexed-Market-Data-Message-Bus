#include "tiplog/engine/engine.hpp"
#include "tiplog_bench/contracts.hpp"
#include <array>
#include <gtest/gtest.h>
#include <string>
#include <sstream>

namespace {
using namespace tiplog;
std::span<const std::byte> bytes(const std::string &text) {
  return std::as_bytes(std::span(text));
}
TEST(BenchDigest, Sha256EmptyAbcAndMillionA) {
  bench::Sha256 empty;
  EXPECT_EQ(empty.hex(),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  bench::Sha256 abc;
  abc.update(bytes(std::string("abc")));
  EXPECT_EQ(abc.hex(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  bench::Sha256 million;
  const std::string block(1000, 'a');
  for (unsigned i = 0; i < 1000; ++i)
    million.update(bytes(block));
  EXPECT_EQ(million.hex(),
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
}
TEST(BenchDigest, Sha256PaddingBoundariesAndIncrementalCopies) {
  for (const auto size :
       std::array<std::size_t, 8>{55, 56, 63, 64, 65, 119, 120, 128}) {
    const std::string text(size, 'z');
    bench::Sha256 whole, parts;
    whole.update(bytes(text));
    for (const auto byte : bytes(text))
      parts.update(std::span(&byte, 1));
    EXPECT_EQ(whole.hex(), parts.hex());
    const auto digest = whole.hex();
    whole.update(bytes(std::string("!")));
    EXPECT_NE(whole.hex(), digest);
  }
}
TEST(BenchDigest, SequenceEndianAndPayloadSink) {
  bench::Sha256 hash;
  hash.little_u64(1);
  EXPECT_EQ(hash.hex(),
            "7c9fa136d4413fa6173637e883b6998d32e1d675f88cddff9dcbcf331820f4b8");
  auto sink = bench::fnv_basis;
  const std::string payload = "abc";
  bench::sink_delivery(sink, Delivered{1, 99, 2, bytes(payload)});
  EXPECT_EQ(sink, 13117744247869397868ULL);
}
TEST(BenchPayloadMix, RejectsOverflowAndMalformedRowsBeforeSampling) {
  for (const auto& text : {
      "wrong\nA,12,1\n",
      "type,payload_bytes,count\n",
      "type,payload_bytes,count\nAA,12,1\n",
      "type,payload_bytes,count\nA,11,1\n",
      "type,payload_bytes,count\nA,257,1\n",
      "type,payload_bytes,count\nA,12,0\n",
      "type,payload_bytes,count\nA,12,1\nA,64,1\n",
      "type,payload_bytes,count\nA,12,9223372036854775809\nB,64,9223372036854775809\n",
      "type,payload_bytes,count\nA,12,1\nB,bad,1\n"}) {
    std::istringstream input(text);
    EXPECT_THROW(bench::read_payload_mix(input), std::invalid_argument) << text;
  }
  std::istringstream boundary("type,payload_bytes,count\r\nA,12,1\r\nB,256,18446744073709551614\r\n");
  const auto mix = bench::read_payload_mix(boundary);
  ASSERT_EQ(mix.size(), 2);
  EXPECT_EQ(mix.back().second, UINT64_MAX);
  // Boundary total remains a valid monotone distribution and RNG bound.
  bench::Random random{42};
  for (unsigned draw = 0; draw < 100; ++draw) {
    const auto chosen = std::upper_bound(mix.begin(), mix.end(), random.bounded(mix.back().second),
        [](auto value, const auto& row) { return value < row.second; });
    ASSERT_NE(chosen, mix.end());
  }
}

TEST(BenchValidation, InjectedReplayDisagreementHasDistinctFailureType) {
  struct Result {
    std::uint64_t sink{}, count{}, bytes{};
    Status status{Status::Done};
    std::optional<ReplayError> error;
    std::optional<ResumeCheckpoint> checkpoint;
    ReplayWork work;
  };
  const Result timed;
  auto untimed = timed;
  EXPECT_NO_THROW(bench::verify_replay(timed, untimed));
  ++untimed.sink;
  try { bench::verify_replay(timed, untimed); FAIL(); }
  catch (const std::exception& error) {
    EXPECT_EQ(bench::execution_failure_status(error), "validation_failure");
  }
  EXPECT_EQ(bench::execution_failure_status(std::bad_alloc{}), "runtime_error");
  EXPECT_EQ(bench::execution_failure_status(std::invalid_argument("unexpected during execution")), "runtime_error");
  untimed = timed;
  ++untimed.work.records_fetched;
  EXPECT_THROW(bench::verify_replay(timed, untimed), bench::ValidationFailure);
  untimed = timed;
  untimed.checkpoint = ResumeCheckpoint{1, 24};
  EXPECT_THROW(bench::verify_replay(timed, untimed), bench::ValidationFailure);
}

TEST(BenchReplayWork, ScanAndAllIndexedKernelsHaveExactTraversalCounts) {
  EngineConfig config;
  config.ring_bytes = 512;
  config.max_record_bytes = 128;
  Engine engine(config);
  const auto a = engine.intern("x/a/event"), b = engine.intern("x/b/event");
  const std::string payload = "abc";
  for (unsigned i = 0; i < 8; ++i)
    engine.publish(i % 2 ? a : b, bytes(payload));
  const auto sub = engine.compile({{{Term::Subtree, "x/a"}}});
  for (const auto mode : {ReplayMode::Scan, ReplayMode::Indexed})
    for (const auto kernel : {MergeKernel::StdPQ, MergeKernel::BinHeap,
                              MergeKernel::Quad, MergeKernel::Loser}) {
      auto replay = engine.open_replay(sub, 0, mode, kernel);
      std::vector<Delivered> out;
      EXPECT_EQ(replay.next_batch(0, out), Status::More);
      EXPECT_EQ(replay.work().records_fetched, 0);
      EXPECT_EQ(replay.next_batch(99, out), Status::Done);
      EXPECT_EQ(out.size(), 4);
      const auto work = replay.work();
      EXPECT_EQ(work.delivered, 4);
      EXPECT_EQ(work.records_fetched, mode == ReplayMode::Scan ? 8 : 4);
      EXPECT_EQ(work.bytes_inspected, mode == ReplayMode::Scan ? 192 : 96);
      EXPECT_EQ(work.entries_visited, mode == ReplayMode::Scan ? 0 : 4);
      EXPECT_EQ(work.index_seeks, mode == ReplayMode::Scan ? 0 : 1);
      EXPECT_EQ(work.pads_inspected, 0);
      auto moved = std::move(replay);
      EXPECT_EQ(moved.work(), work);
      EXPECT_EQ(moved.next_batch(99, out), Status::Done);
      EXPECT_EQ(moved.work(), work);
    }
}
TEST(BenchReplayWork, ExpiredAndWideFallbackHaveHonestCounts) {
  EngineConfig config;
  config.ring_bytes = 64;
  config.max_record_bytes = 32;
  Engine engine(config);
  const auto a = engine.intern("x/a/event");
  const std::string payload = "abc";
  for (unsigned i = 0; i < 8; ++i)
    engine.publish(a, bytes(payload));
  const auto sub = engine.compile({{{Term::Subtree, "x"}}});
  auto expired = engine.open_replay(sub, 0, ReplayMode::Indexed);
  EXPECT_EQ(expired.status(), Status::Error);
  EXPECT_EQ(expired.work(), ReplayWork{});
  auto replay =
      engine.open_replay(sub, engine.stats().tail_seq - 1, ReplayMode::Indexed);
  EXPECT_EQ(replay.effective_mode(), ReplayMode::Scan);
  std::vector<Delivered> out;
  EXPECT_EQ(replay.next_batch(99, out), Status::Done);
  EXPECT_EQ(replay.work().entries_visited, 0);
  EXPECT_EQ(replay.work().delivered, out.size());
}
TEST(BenchReplayWork, WrappedPadCountsOnlyInScanTraversal) {
  EngineConfig config;
  config.ring_bytes = 64;
  config.max_record_bytes = 32;
  Engine engine(config);
  const auto topic = engine.intern("x/a/event");
  const std::string payload = "abcdefgh";
  for (unsigned i = 0; i < 3; ++i)
    engine.publish(topic, bytes(payload));
  const auto sub = engine.compile({{{Term::Subtree, "x/a"}}});
  for (const auto mode : {ReplayMode::Scan, ReplayMode::Indexed}) {
    auto replay = engine.open_replay(sub, 1, mode);
    std::vector<Delivered> out;
    EXPECT_EQ(replay.next_batch(99, out), Status::Done);
    ASSERT_EQ(out.size(), 2);
    EXPECT_EQ(replay.work().records_fetched, 2);
    EXPECT_EQ(replay.work().pads_inspected, mode == ReplayMode::Scan ? 1 : 0);
    EXPECT_EQ(replay.work().bytes_inspected,
              mode == ReplayMode::Scan ? 64 : 48);
  }
}
} // namespace
