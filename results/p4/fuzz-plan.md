# P4 F3 validation plan — 2026-10-18

Planned, not executed. Reuses corrected v1.1 V15–V20/V26/V37. Root independently derived the tiny-pool arithmetic in `results/p3/p4-pressure-fixture-plan.md` before P4 code existed.

`tests/fuzz/pressure_fixture.hpp` compares C64/max32/N1/B1 ForceEvict against fixed starts, heads, tails, DATA/PAD byte losses, generations, allocations/frees and live/slack counts. It also covers an unconsumed stale reader, unmatched candidate expiry and exact-budget completion before expiry. RejectPublish's second insertion has enough physical ring space but no free index block; unchanged ring bytes, seq/positions, metadata, postings, counters and gauges are checked. Preparatory control capacity is reported honestly.

`fuzz_engine_ops` uses `TIPLOG_FUZZ_MODE=indexed` to select k1 subscriptions and a high configuration bit for the true pressure fixture. Its general random branch uses B1/B2/B4 and an ample fixed pool of C/16+64 blocks. This keeps the independent oracle's capacity-only retention valid while exercising block reuse; it does not copy an observed engine tail into the oracle. The narrow nonmatching and future-topic cases remain in the grammar.

Acceptance still requires a fresh clean 1,800 confirmed monotonic seconds, final statistics and source/binary/corpus identities. `pool_pressure_checked.ops` invokes actual pressure assertions; `recycled_block.ops` publishes enough fixed-size DATA to recycle small blocks under capacity eviction. No timed acceptance is claimed by creating these files.
