# VALIDATION PLAN — correctness checks, benchmark protocol, figures, reproducibility

Plan version **v1.1** · 2026-10-17 · **P0 plumbing checks passed; P1–P5 jointly authorized and executing in dependency order.** The original refresh performed document/source review and read-only metadata checks only. Actual checks and gate outcomes are recorded in [PROGRESS](PROGRESS.md); commands below remain planned except where that execution record provides results. P6–P8, Tier C and roadmap validation remain outside this authorization. §13 adds the review's later regression cases.

## 1. Principles

1. **Correctness criteria are fixed now** (§1.1). Performance expectations are **hypotheses** (§1.2), with no predetermined winners or speedups.
2. Every result row traces back to a git SHA, build preset and flags, compiler, environment capture, input SHA-256, configuration, and seed.
3. Every run outcome is recorded, including failed recoveries, `HistoryExpired`/`FellBehind`, invalid configurations, and crashes. Nothing is silently dropped.
4. Throughput is reported as throughput. It is never inverted into a latency claim. Latency distributions come only from the open-loop experiment T4.
5. With no hardware counters, the report makes no hardware-counter claims (§5.6).

### 1.1 Correctness and reproducibility criteria (acceptance thresholds)

| ID | Criterion |
|---|---|
| CC-1 | All V-tests required by the selected tier and authorized milestone pass in `release` and `asan-ubsan`: 0 failures, 0 sanitizer reports; optional/roadmap tests are not silently included or marked passed |
| CC-2 | Randomized differential tests: ≥1,000 seeds × ≥10,000 operations for each (mode, kernel) in `release`; ≥200 seeds in `asan-ubsan` |
| CC-3 | Each fuzz target runs ≥30 min at its phase gate with no unresolved crash; every crash is minimized into a regression test |
| CC-4 | Every configuration matches the independent oracle's expected output **and outcome** for its schedule: full digest on success; correct delivered prefix, checkpoint and explicit error on expiry. A mismatch invalidates its results. |
| CC-5 | MASK-DP = ENUM on ≥10,000 random instances for every k ≤ K (exact integers); 0 mismatches |
| CC-6 | ITCH message counts from the Python converter equal those from the independent C++ framing walker, per type and per locate |
| RC-1 | Every figure regenerates from saved raw results with one command |
| RC-2 | Re-running the converter on the same input gives byte-identical traces (SHA-256 equal) |
| RC-3 | Deterministic engine runs give identical output digests across repeated runs and across GCC/Clang builds |

### 1.2 Hypotheses (to test, not to confirm)

| ID | Hypothesis | Tested by |
|---|---|---|
| H1 | Indexed catch-up does less work than scan when the subscribed partitions hold a small fraction of the range; the crossover depends on k and selectivity | T1, T3 |
| H2 | For narrow subscriptions, record fetches dominate merge cost, so kernel differences shrink end-to-end | M1 vs M1-touch, T1 |
| H3 | Heap early-exit favors bursty, low-interleave inputs; loser trees favor highly interleaved, large-k inputs | M1 |
| H4 | Entry storage, expired entries, open/sealed slack, block metadata, expiry heap, and per-partition lists explain allocated index memory; the open-slack component scales with P·B | T5 |
| H5 | Under H-spec, baseline waste is concentrated in TAPE and STAT consumers | L1, L2 |
| H6 | At equal store counts, adaptive layouts reduce weighted bytes for W1/W2 but can raise stores touched for BOOK/REPLAY | L2, L3 |
| H7 | Some workload-specific partitions fit ENUM or MASK-DP budgets; coverage is measured, and neither method is presumed to cover every remaining instance | L1, L3 |

---

## 2. Correctness strategy

- **Oracles independent of the implementation:**
  - **`ref::ScanOracle` (C++, tests only).** Keeps the full published sequence `(seq, topic path, payload)`. It matches subscriptions by **string-prefix logic on paths**, not by the engine's topic ids or partition filters. It derives retention from an independent restatement of the ARCHITECTURE §3.5/§5.3 rule: item starts with PAD placement, and the tail is the smallest start ≥ end − C.
  - **Python digest oracle.** For end-to-end ITCH runs, it computes, from the trace file alone, the expected (count, SHA-256 of seq list, SHA-256 of payload stream) per subscription and range.
  - **ENUM** is the oracle for the optimizer. Two separate evaluators compute J: the formula, and materializing stores then simulating reads.
- **Levels:**
  - golden unit tests (hand-built ITCH messages from spec offsets; tiny rings with hand-computed states);
  - randomized differential tests (seeded);
  - property checks via `check_invariants()` after every operation in debug and test builds;
  - structure-aware differential fuzzing;
  - end-to-end digest checks;
  - sanitizer builds of everything.

## 3. Correctness matrix

| ID | Property / invariant | Technique and inputs | Phase |
|---|---|---|---|
| V01 | ITCH parsing of all 23 types | Golden bytes built from spec offsets (S05); parse ↔ fields | P1 |
| V02 | Framing edge cases | Zero-length terminator; missing terminator → `incomplete`; truncated length or payload; unknown type; length ≠ spec | P1 |
| V03 | Locate/symbol mapping | Directory build; consistency on messages with both fields; K routed by symbol; unknown locate → `_unmapped` | P1 |
| V04 | Count reconciliation (CC-6) | Full day: Python vs independent C++ walker | P1 |
| V05 | Trace v1 round trip and robustness | Writer/reader round trip; fuzz F1 | P1 |
| V06 | Topic registry | Ancestor creation; partition rule at depths 1, 2, and deeper; local ids | P2 |
| V07 | Subscription normalization and matching | Random paths and terms vs brute-force string matcher | P2 |
| V08 | Topics created after subscribing | Subtree subscription gains later topics; exact pre-interned topics | P2 |
| V09 | Oracle retention model | Hand-computed examples with PAD/wrap; small C | P2–P3 |
| V10 | Ring edge cases | Exact fit at end (no PAD); 8-byte PAD; record = room to end; full ring; zero payload; max payload; oversized → error; capacity not a power of two → config error | P3 |
| V11 | INV-R1…R7 | `check_invariants` after every op (randomized) | P3 |
| V12 | Scan replay differential | Random trees, subscriptions (overlapping, empty, nonexistent, wide), payload sizes, tiny capacities (4–64 KiB), interleaved publish/open/next_batch | P3 |
| V13 | Expiry semantics (INV-Q3, Q4) | HistoryExpired at open; FellBehind between batches; delivered prefix exact; error fields correct | P3, P5 |
| V14 | Upper bound and chaining (INV-Q5, Q6) | Publish during replay; replay at head; chained polls = single replay; replay-to-live transition via `Tail` | P3, P5 |
| V15 | INV-P1…P3 | Pool conservation and generations under random ops; tiny pools | P4 |
| V16 | INV-I1…I3 | Per-partition entries vs brute-force retained-record listing | P4 |
| V17 | INV-I4, I5, P4 | Expiry min-heap order; late partial seals; open-block expiry; open/sealed slack and expired-entry recount | P4 |
| V18 | Reader-safe reclamation | Cursor on a block that gets recycled → FellBehind; recycled entries never read as valid (B = 1, 2; tiny ring) | P4–P5 |
| V19 | Pool pressure | ForceEvict vs RejectPublish; sizing validation; rejected publication preserves observable sequence/retention/index state and no commit-stage resource rejection is possible | P4 |
| V20 | Indexed k = 1 differential | As V12 with indexed mode | P4 |
| V21 | Kernel equivalence (INV-M1, M2) | All kernels vs `std::merge` on random sorted lists: k = 1, 2, large k, empty lists, singletons, extreme skew | P5 |
| V22 | Galloping boundary (INV-M3) | Adversarial runs: alternating; long runs; run ending exactly at a block boundary; competitor key = run end ± 8 | P5 (Tier C) |
| V23 | Indexed multi-partition differential | V12 generators × all kernels | P5 |
| V24 | Output properties (INV-Q1) | Strictly increasing seq; no duplicates with overlapping terms | P5 |
| V25 | Mode independence (INV-Q7) | Scan = Indexed(each kernel) = Auto on the same scenarios | P5 |
| V26 | Structure-aware differential fuzzing | F3 (ops grammar), checked against the oracle in-process | P3–P5 |
| V27 | End-to-end ITCH digests (CC-4) | Every T-experiment configuration | P6 |
| V28 | Evaluator agreement | Formula J vs materialize-and-simulate, random instances | P7 |
| V29 | MASK-DP = ENUM (CC-5) | Random trees \|V\| ≤ 12, b ≤ 4, random α, β, γ, zero volumes, terms at internal nodes and above the root, baskets; every k | P7 |
| V30 | KM exactness for P_T; count(T) monotone | Brute-force minimum count on tiny trees; random T sweeps | P7 |
| V31 | Baseline construction | Topics with < 3 segments, internal-topic volumes | P7 |
| V32 | Worked example | 5,517,460,497 / 39,881,491 / 30,029,491 B (ARCHITECTURE §6.7) | P7 |
| V33 | Converter property tests (optional) | Hypothesis: encode/parse round trip | P1 (Tier C) |
| V34 | Book consistency (optional) | BOOK replays from session start: no unknown order refs, shares ≥ 0 | P6 (Tier C) |

**Roadmap tests (not authorized):**
- V40: WAL recovery is a prefix under random truncation and corruption of the last segment.
- V41: CRC detection, including garbage appended to the file.
- V42: Mid-sealed-segment corruption is fail-stop.
- V43: Manifest atomicity at injected crash points.
- V44: Orphan pack GC.
- V45: Compaction equivalence (INV-D6).
- V46: Disk→tip handoff with no gap or duplicate under concurrent publishing.
- V47: Fuzz WAL, pack, and manifest parsers.
- V48: TSan stress for R4.
- V49: Immediate pre-run residency snapshot and eviction-attempt outcome before D1; no device-cache guarantee.

## 4. Sanitizers and fuzzing

**Presets (planned):**

| Preset | Compiler and flags | Purpose |
|---|---|---|
| `debug` | GCC 15.2 `-O0 -g -D_GLIBCXX_ASSERTIONS` | Development; checked iterators |
| `release` | GCC 15.2 `-O2 -g -march=x86-64-v3` (flags recorded with every run) | Tests and benchmarks |
| `asan-ubsan` | Clang 21 `-O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer`; `ASAN_OPTIONS=detect_leaks=1:abort_on_error=1`, `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1` | Full suite with reduced iteration counts (CC-2) |
| `fuzz` | Clang 21 `-fsanitize=fuzzer,address,undefined` | libFuzzer targets |
| `tsan` | Clang 21 `-fsanitize=thread` | R4 only |

The `release` preset is also built with Clang to check RC-3.

**Fuzz targets (libFuzzer: maintenance mode but bug-fixed, S45):**

| Target | Input | Asserts | Seed corpus |
|---|---|---|---|
| F1 `fuzz_trace_reader` | Arbitrary bytes as a trace v1 file | No crash or UB; errors for every malformed header, length, or offset; round trip for valid prefixes | Golden traces; dictionary of magic and version values |
| F2 `fuzz_itch_walker` | Arbitrary bytes as a BinaryFILE stream | No crash; framing errors reported; lengths checked against the spec table | First 64 KiB of real data (local only, not committed) and golden messages |
| F3 `fuzz_engine_ops` | A byte grammar of ops: publish(topic idx, len), open(sub idx, after offset, mode, kernel), next_batch(n), close | INV-* after each op; every delivered batch equals the oracle; errors justified | Hand-written scenarios: wrap, PAD = 8, pool pressure, recycled block |
| F4–F6 (roadmap) | WAL segment, pack directory, manifest | Recovery never crashes and yields a valid prefix; parsers reject corruption | — |

**Fuzzing protocol:**
- Run each target for **≥30 min per phase gate**, optionally on E-cores (`taskset -c 4-11`), **outside benchmark measurement blocks**. E/P cores share package resources; affinity alone does not prevent interference.
- Keep corpora under `tests/fuzz/corpus/` (synthetic inputs only; no NASDAQ bytes in git).
- Record libFuzzer final statistics. Fix every crash and add it as a regression test.

---

## 5. Benchmark protocol (hybrid laptop: i5-1235U)

### 5.1 Environment control

**Recorded in every run:** CPU model, kernel, governor, `no_turbo`, SMT state, `perf_event_paranoid`, ASLR mode, power source, compiler versions, preset, flags, git SHA (+ dirty flag), RAM, free disk, load average.

1. **Pinning.** Run on **CPU 2** (P-core, max 4.4 GHz) with `taskset -c 2`. Keep its SMT sibling (CPU 3) idle (offline it only if DEC-2 allows). Verify `sched_getcpu()` at the start and end of each run. Never let benchmarks run on E-cores (4–11), which are a different microarchitecture.
2. **ASLR.** Attempt per-process `setarch x86_64 -R` only if allowed. Sandboxes may reject personality changes; record failure and retain a documented ASLR-on regime rather than requiring a system setting change.
3. **Frequency.** If DEC-2 allows, set the `performance` governor on CPUs 2–3 and optionally `no_turbo=1` for the session. Otherwise record `powersave` and accept the extra variance, which is then reported.
4. **Noise detection.** Sample `scaling_cur_freq` of CPU 2 before and after every run. Flag runs deviating >10% from the session median; **flagged runs are kept and reported**, not deleted. Require AC power. Idle 60 s between blocks.
5. **Pilot (P6.2).** Run 30 repetitions of one M1 and one T1 configuration and compute the coefficient of variation. If CV > 3% (M1) or > 5% (T1), raise repetitions or fix the environment, and record the decision.

### 5.2 Builds and data
- Benchmarks use the `release` preset only; flags go into every result row.
- Inputs are identified by SHA-256: the source gzip, the trace, and the `.meta.json`.
- Synthetic generators take explicit seeds, which are stored.

### 5.3 Repetitions, warm-up, interleaving
- **Microbenchmarks (Google Benchmark v1.9.5, S42):**
  - `--benchmark_repetitions=15 --benchmark_enable_random_interleaving=true --benchmark_min_warmup_time=0.2 --benchmark_min_time=0.5s`;
  - JSON output; `DoNotOptimize` on a running output hash.
- **End-to-end:**
  - ≥10 measured **process-level** repetitions per configuration, with configuration order shuffled per round (seeded);
  - one additional declared warm-up is excluded from statistics but **kept in the raw data**.
- **Cache regimes for tip experiments:**
  - *scratch-thrashed*: touch a 64 MiB scratch buffer before each measured replay, recording access order/size; this treatment does not prove every target CPU-cache line is cold;
  - *repeat-warm*: the same replay run twice, with the second measured.
  - Both are reported and labeled.

### 5.4 Statistics and uncertainty
- Report median, IQR, min/max, and n, plus a 95% percentile-bootstrap CI of the median (10,000 resamples, seeded).
- Ratios (e.g., scan/indexed) are ratios of medians with bootstrap CIs. For matched rounds/traces, resample whole paired blocks; independently resample arms only for a declared independent design. Preserve time/run dependence in T4 rather than treating all requests as independent. No p-value hunting.
- **Percentiles appear only in T4.** p50/p90/p99 require n ≥ 1,000 samples per configuration. **No p99.9** unless n ≥ 100,000. HdrHistogram at 3 significant digits.
- Optional robustness check for measurement bias (S44), Tier C: two link orders and environment-variable padding sizes for one M1 configuration.

### 5.5 Failure accounting

| Status | Meaning |
|---|---|
| `ok` | Completed |
| `history_expired` | Start of range already evicted |
| `fell_behind` | Evicted during the replay |
| `invalid_config` | Configuration rejected (e.g., ring too small for the requested backlog) |
| `crash` | Process failure |

Every table includes non-`ok` counts. A configuration whose requested backlog exceeds retention is reported as `history_expired`, not removed.

### 5.6 Hardware counters and fallback (DEC-2)
- **Counters available only after a successful event probe:** upstream level 2 permits per-process user-space counting; it is neither universally necessary nor sufficient. CAP_PERFMON, distro/security policy, PMU support, and event scheduling also matter (S32, S56). The default is no system-setting changes, with the fallback below. Any explicit change is separately authorized.
  - Events (names checked with `perf list` in P0.4): `cpu_core/cycles/u`, `cpu_core/instructions/u`, `cpu_core/branch-misses/u`, `cpu_core/L1-dcache-load-misses/u`, `cpu_core/LLC-load-misses/u`.
  - Measurement region: `perf stat --delay=-1 --control=fifo:…` with an acknowledgment channel, or a justified in-process `perf_event_open` group. Wait for enable/disable acknowledgments and measure boundary overhead. P0.4 chooses only after a successful probe.
  - Record PMU/event names, `time_enabled`, `time_running`, scaling, errors and unsupported events. Split unschedulable groups or explicitly label multiplexed results; never substitute zero for a missing counter.
- **No counters:** wall-clock and `getrusage` user/system time only, plus **Cachegrind** instruction counts and *simulated* cache misses on reduced configurations, labeled "simulated". The report then makes **no hardware-counter claims**.

---

## 6. Experiment matrix

### 6.1 Microbenchmarks

| ID | Question | Independent variables | Fixed | Metrics | Phase / tier |
|---|---|---|---|---|---|
| M1 | Merge-kernel cost | k ∈ {1, 2, 4, 8, 16, 64, 256, 1024, 4096, 16384}; owner pattern: uniform random, runs with geometric mean L ∈ {1, 4, 16, 64, 256}, Zipf owners s ∈ {0, 0.8, 1.1}; kernels StdPQ, BinHeap, Quad, Loser (± gallop) | 2²² outputs, in-memory lists | ns/output; instructions, branch-misses, L1D misses per output (if counters) | P5 / B (gallop: C) |
| M1-touch | Merge plus a record fetch | As M1, each output reading 8 B at its position in a 1 GiB array | — | ns/output | P5 / B |
| M2 | Publish cost and index overhead | Payload size: ITCH empirical mix and fixed {12, 32, 64, 256}; P ∈ {1, 100, 10⁴} (uniform/Zipf); index on/off; B ∈ {256, 1024} | C = 1 GiB | ns/publish, evictions/publish, block alloc/free rate, pool high-water | P5 / B |
| M3 | Block size | B ∈ {64, 256, 1024, 4096} | ITCH partition sizes | Seek ns, scan ns/entry, memory | P6 / B |

### 6.2 Tip-recovery experiments (ITCH trace window, deterministic engine)

**T1: catch-up cost vs breadth (P6, tiers A/B).**
- Ring C = 1 GiB (2 GiB for long backlogs).
- The engine replays the window up to anchor t₀ (10:00:00.000; a 15:59 anchor in Tier C). Not timed.
- Then open a replay with backlog ∈ {1 s, 10 s, 60 s, 300 s} of market time.
- Subscriptions:
  - BOOK(top-1), BOOK(median-activity symbol);
  - BOOK baskets of N ∈ {10, 100, 1000} (top-N and random-N);
  - TAPE(top-N);
  - all-trades (every symbol's `trade` subtree);
  - full stream (`itch/**`, wide).
- Modes: Scan; Indexed × {StdPQ, BinHeap, Quad, Loser}.
- Metrics:
  - **work**: entries visited, records fetched, bytes inspected, delivered;
  - **time**: wall, CPU;
  - throughput; counters; status.

**T2: many slow readers (P6, B).**
- R ∈ {1, 10, 100, 1000} readers. Subscriptions are drawn (seeded) from W2's class mix; each recovers a 10 s backlog sequentially on one core.
- Metric: CPU-seconds per second of market data served, with and without amortized index maintenance (publish of the same window with index on vs off).
- This is the analogue of the article's server-load scenario.

**T3: synthetic sweeps (P6, B).**
- Generator: P ∈ {10, 10³, 10⁵}, Zipf s ∈ {0, 0.8, 1.2}, mean same-partition run L ∈ {1, 16, 256}, sizes from the ITCH mix.
- Subscription breadth k and selectivity are swept.
- Output: a crossover map of scan vs indexed (H1) and calibration of the Auto thresholds.

**T4: open-loop "reboot storm" (P6, Tier C).**
- One thread interleaves publishing the trace at real-time ×{1, 4} with serving catch-up requests.
- Requests arrive on a seeded schedule: a burst of R within 1 s, or Poisson.
- **Latency is measured from the scheduled arrival** (no coordinated omission, S43). Also reported: FellBehind counts and publisher lag (offered vs achieved rate).
- Scan and indexed run with identical schedules and seeds.

**T5: memory (P6, A/B).**
- Index bytes per retained record, pool slack, and high-water vs B and over time-of-day snapshots.
- Compared with the ARCHITECTURE §5.5 formula (H4).

**Binance variants of T1, T3, and T5 (Tier C, R7):** same protocol with the `bnc/...` topics. The constructed cross-symbol order is stated with the results.

### 6.3 Optimizer studies (offline; topic-volume tables from P1)

| ID | Question | Inputs | Methods | Outputs | Tier |
|---|---|---|---|---|---|
| L1 | Workload characterization (skew is measured, not assumed) | Full-day counts and bytes | — | Message mix; per-symbol CCDF and Lorenz, Gini, top-1%/10% shares; family composition per symbol (incl. executions' share of `modify` bytes); same-partition run-length distribution; per-second bursts; per-partition \|V\| and b histograms | A |
| L2 | Layout quality per workload | H-spec trees; W0–W3; β/α ∈ {0, 64 KiB, 1 MiB} | H-BASE, H-KM-min, H-KM-max, ENUM/MASK-DP at the baseline's per-partition budget, plus a γ sweep | Σ f·bytes, waste, per-class amplification, stores touched, max waste, worst ratio (with and without a 4 KiB useful-bytes floor) | A: ENUM only; B: + DP |
| L3 | Optimality gap | Same plus synthetic trees (\|V\| up to 1,000, Zipf volumes) | Heuristics vs exact on **identical J and budgets** | Gap distribution; DP runtime scaling | B |
| L4 | Article example | §6.7 tree | All | Table and figure; regression test V32 | A |
| L5 | Hierarchy sensitivity | H-flat vs H-spec | All | Waste vs stores; explicitly shows H-flat baseline waste = 0 for exact reads | B |
| L6 | Robustness to drift | Layout from window 1, tested on frozen window 2; separately vary data skew and subscription weights (S50) | Selected methods within fixed resource budgets | Regret only where the test-window optimum is available; otherwise cost and coverage | C |

### 6.4 Disk experiments (roadmap R3; not authorized)
- **D1:** page-cache treatment versus repeat-warm. After successful synchronization, request page-aligned `POSIX_FADV_DONTNEED` over measured files/ranges and record immediate `mincore` resident/total pages and errors. Label successful cases **page-cache-cold at the pre-run snapshot**, not cold devices. Keep failed eviction attempts as separate statuses. Report Δ`read_bytes`, logical bytes, time, CPU; device-sector deltas include unrelated traffic and are supporting observations (S56).
- **D2:** WAL recovery time vs tail size.
- **D3:** compaction throughput, CPU and bytes written per layout; distinguish WAL bytes, pack bytes, rewrite bytes, and temporary peak disk use. Count application-layer write amplification against a stated logical-payload denominator (S52); do not transfer XLL's gains or architecture.

## 7. Fairness and measurement boundaries

- **Same state, same resources.** Scan and indexed runs use the **same engine state** (identical ring contents), the same core, build, trace, subscription, and output sink (a running 64-bit hash of seq and payload), in interleaved order. Readers do not compete with the publisher in T1–T3 (publisher paused; stated). T4 shares one thread on purpose.
- **Index cost is not hidden.** The index exists in both modes (one engine). Its maintenance cost is reported separately (M2), and **added** to indexed totals in T2.
- **No strawman baselines.** The scan loop is tuned (topic check via a per-subscription bitset over global topic ids; no virtual calls). Heap baselines are inlined (avoiding the Prometheus confound, S22).
- **Boundaries:**
  - M1: the merge loop only;
  - T1–T3: `open_replay` → `Done`, including seek, excluding trace load and ring prefill;
  - T4: scheduled arrival → completion;
  - D1: request → last byte delivered, cache state verified before start.
- **Offered load** (T4): the schedule and publish rate are identical across modes. Achieved rates are reported. Overload is flagged when publisher lag exceeds 100 ms.

## 8. Metric definitions

| Metric | Definition |
|---|---|
| `bytes_inspected` | Scan: Σ sizes of items traversed (logical, from the ring; never "physical") |
| `entries_visited` | Indexed: index entries read |
| `records_fetched` | Records whose header was read (= `entries_visited` for untagged entries) |
| `delivered`, `selectivity` | Delivered records; delivered / records in range |
| `filter_waste` | `records_fetched − delivered` |
| `ns_per_delivered`, `delivered_per_s` | Throughput measures (not latencies) |
| `index_bytes` | Allocated entry/meta storage + expiry heap + per-partition structures + measured allocator overhead; report the breakdown |
| `slack_entries`, `live_entries` | Per ARCHITECTURE §5.5 |
| `pool_high_water` | Maximum allocated blocks |
| Layout metrics | J; R_j, U_j, waste_j; amplification R_j/U_j; stores; stores touched per class; max waste; worst ratio (raw and floored) |
| Physical I/O (R3) | Process storage-layer Δ`read_bytes`; device-sector deltas ×512 are system-level supporting measurements, including unrelated/readahead activity |

## 9. Expected figures and tables

| Fig | Content | Source |
|---|---|---|
| F01 | ITCH message-type mix (counts, bytes) | L1 |
| F02 | Per-symbol volume CCDF and Lorenz (messages, bytes) | L1 |
| F03 | Family composition per symbol; executions' share of `modify` | L1 |
| F04 | Same-partition run lengths; per-second rate profile | L1 |
| F05 | Partition tree size and class-count histograms | L1 |
| F06 | M1 ns/output vs k per kernel and pattern (CIs) | M1 |
| F07 | M1 effect of run length and galloping | M1 |
| F08 | M2 publish cost vs P and size, index on/off | M2 |
| F09 | T1 catch-up time vs breadth (log-log), scan vs kernels | T1 |
| F10 | T1 work counters (entries, fetches, bytes) | T1 |
| F11 | T2 CPU per market-second vs number of readers | T2 |
| F12 | T3 crossover map (k × selectivity) | T3 |
| F13 | T5 index memory and slack vs B | T5 |
| F14 | L2 per-class read amplification by method | L2 |
| F15 | L2/L3 trade-off: total stores vs weighted bytes (exact hull + heuristic points) | L2, L3 |
| F16 | L3 optimality-gap distribution | L3 |
| F17 | L4 article example layouts | L4 |
| F18 | L5 hierarchy sensitivity | L5 |
| F19 | T4 completion-latency CCDF (Tier C) | T4 |
| F20 | L6 regret under drift (Tier C) | L6 |
| F21–F23 | D1–D3 (roadmap) | R3 |

**Tables:**
- environment;
- datasets with checksums;
- claims table: claim, experiment, configuration, statistic, CI, n, caveats.

## 10. Raw outputs and layout (planned)

```
data/manifest.json                      # tracked: URL, size, Last-Modified, SHA-256, download date
data/raw/, data/traces/                 # NOT tracked (license/size)
results/env/<run_id>.json               # environment capture
results/raw/<EXP>/<run_id>/config.toml
results/raw/<EXP>/<run_id>/runs.jsonl   # one row per repetition
results/raw/<EXP>/<run_id>/stdout.log, perf.csv (optional), gbench.json (micro)
results/derived/<EXP>/summary.csv       # produced only by scripts
results/figures/Fxx_*.pdf|png
run_id = <UTC timestamp>_<git short SHA>[-dirty]_<host>
```

Each `runs.jsonl` row records:
```
exp, run_id, rep, seed, warmup, trace_sha256, preset, compiler, flags, cpu,
freq_before/after, config{…}, status, wall_ns, cpu_user_ns, cpu_sys_ns,
work{…}, counters{…} | null, out_count, out_digest, oracle_digest
```

Raw files are append-only. Large raw files stay untracked; summaries and figures are tracked.

## 11. Reproduction commands (P0 executed; later phases PLANNED)

P0's four preset pipelines, Python tests, environment capture and supplementary fallback/Clang plumbing checks passed; see [actual commands and evidence](PROGRESS.md#phase-0-execution--2026-10-17-asiakolkata). LeakSanitizer in this workspace requires running outside sandbox tracing; its checks remain enabled. No V/M/T/L experiment is represented as passed by these plumbing checks.

```bash
# P0 — environment and build
scripts/env_capture.sh > results/env/$(date -u +%Y%m%dT%H%M%SZ).json
cmake --preset release && cmake --build --preset release -j8 && ctest --preset release
cmake --preset asan-ubsan && cmake --build --preset asan-ubsan -j8 && ctest --preset asan-ubsan
scripts/check_all.sh                                   # every preset + tests

# P1 — data (requires network; about 3.5 GB download)
.venv/bin/python -m tiplog_py.data.fetch --source nasdaq --file 12302019.NASDAQ_ITCH50.gz --dest data/raw/
gzip -t data/raw/12302019.NASDAQ_ITCH50.gz && sha256sum data/raw/12302019.NASDAQ_ITCH50.gz
set -o pipefail  # bash: propagate decompressor failures
gzip -dc data/raw/12302019.NASDAQ_ITCH50.gz | wc -c    # exact full-stream bytes only if pipeline succeeds
.venv/bin/python -m tiplog_py.itch.measure data/raw/12302019.NASDAQ_ITCH50.gz --out results/data/itch_20191230_counts.json
./build/release/tools/tiplog_walk data/raw/12302019.NASDAQ_ITCH50.gz --out results/data/itch_20191230_counts_cpp.json
.venv/bin/python -m tiplog_py.itch.convert data/raw/12302019.NASDAQ_ITCH50.gz --hierarchy spec \
       --window 09:30:00-10:00:00 --out data/traces/itch_20191230_0930_1000_spec.mdt

# P3–P5 — fuzzing on E-cores
taskset -c 4-11 ./build/fuzz/fuzz_engine_ops -max_total_time=1800 -print_final_stats=1 tests/fuzz/corpus/ops

# P5–P6 — benchmarks on one P-core
taskset -c 2 setarch x86_64 -R ./build/release/bench/merge_bench \
  --benchmark_repetitions=15 --benchmark_enable_random_interleaving=true \
  --benchmark_min_warmup_time=0.2 --benchmark_out=results/raw/M1/<run_id>/gbench.json
.venv/bin/python -m tiplog_py.exp.run configs/T1.toml --reps 10 --cpu 2
.venv/bin/python -m tiplog_py.exp.run configs/T2.toml --reps 10 --cpu 2

# P7 — optimizer
./build/release/tools/tiplog_layout --volumes results/data/itch_20191230_volumes.csv \
  --workload configs/W2.toml --methods base,km-min,km-max,dp --budget baseline --out results/raw/L2/<run_id>/
# P6–P8 — figures
.venv/bin/python -m tiplog_py.figures.build --all
```

## 12. Claims discipline

- A claim appears in the report only with a row in the claims table that points to raw files.
- Wording follows the data: "on this laptop, P-core 2, trace X, n = 10, median [CI]".
- **No generalization** to Aria, to servers, or to other days without data.
- Modeled bytes (L-studies) are always labeled **modeled**. Measured I/O exists only after R3.

## 13. Refresh additions — planned acceptance cases, 2026-10-17

These additions fix specification gaps found by document review. **They have not been implemented or run.** They supplement the existing matrix without replacing independent oracles.

| ID | Planned case / acceptance condition | Phase |
|---|---|---|
| V35 | Subscribe to B in snapshot A(seq1),B(seq2), evict only A before a batch: every mode returns the same conservative expiry. Check positive budgets, `max=0`, exact-budget `More/Done`, long filtered gaps, zero-output snapshots, and resume from completed upper rather than last output. | P3/P5 |
| V36 | Reject max_record>C/2 before mutation; C=64/head=32/need=48 is an invalid configuration, not an eviction loop. Check 8-byte PAD vs 16-byte zero-payload DATA, checked alignment/length arithmetic, PAD-aware sparse seeks, and pressure versus capacity-only retention. | P3 |
| V37 | Reduce the configurable **test-only** delta width to exercise a late partial seal after a newer full seal. Expiry heap order and all memory gauges must match independent recounts; validate wide-before-narrow arithmetic, stale open-block sweep, generic r_min16 and ITCH-specific r_min32 sizing. | P4 |
| V38 | Synthetic near-limit packed positions and reserved sentinel, k/id bounds and local-topic-id exhaustion; reject limits without mutation. Check k=0/1 and exhausted/re-armed cursors. No petabyte trace or >32-GiB traffic is needed to exercise representation boundaries. | P2/P5 |
| V39 | Rational cost normalization and overflow rejection; finite one-store threshold plateau; empty tree/K=0; deterministic equal-weight ties; γ′≥0 supported-budget theorem and bounds at unsupported budgets; state/time caps and heuristic-only status outside exact coverage. | P7 |

Existing V12/V23/V24 also include distinct sequence-numbered equal-payload events and offsetting updates with unchanged final state: every matching event must survive replay (S61). For R2/V46, add repeated live→replay→live fallback, moving tip boundaries and overlap-memory accounting (S59). If R5 is later selected, test cancellation after timeouts, bounded outstanding reconnect attempts, and stable resource counts after repeated outages (S60). None of these roadmap cases has run.

**Optimizer coverage:** L2/L3 must include counts and fractions of partitions, bytes and workload weight covered by each exact method, plus timeout/state-limit outcomes. Only solved same-objective/same-budget instances receive exact-gap values. Stop comparing a timed-out incumbent as if it were OPT. Shared arithmetic overflow is not made valid by two solvers agreeing on it. Global Lagrangian certificates require valid minima/lower bounds for every partition term; incomplete curves cannot be substituted.

V35 additionally covers a batch consuming the final snapshot record exactly at its output limit, followed by eviction and another batch call: the result must be `Done`, not `FellBehind`. Extreme `after_seq` inputs must be checked for empty range before any `+1` arithmetic.

Future-start snapshot queries return no reusable checkpoint; future-start tails return `InvalidRange` rather than lowering their requested floor. Include both in V35. Pool preflight rejection/commit-resource guarantees belong to V19; no post-eviction `RejectPublish` path may leave a partially changed log.

**Optional drift protocol (L6, Tier C unchanged):** use seeded no-drift, data-skew-only, subscription-popularity-only, and combined cases with a declared change point/transition shape (S50). Freeze the pre-change layout and Auto thresholds before evaluating post-change inputs. Plot degradation/recovery separately; changes to Auto are evaluated on held-out traces rather than their calibration traces. This adopts a methodology, not the DriftBench package.

**Later disk validation:** compare modeled layout ranking against measured recovery ranking at matched budgets (S53); report mismatches. Charge re-layout bytes/time and a stated amortization horizon (S39/S51). General storage-error recovery is outside R1's crash-only guarantees unless a separate fault model is added; retry or process restart after EIO is not a passed durability check (S29/S55).

**Protocol qualifications:** percentile sample cutoffs in §5.4 are minimum reporting heuristics, not guarantees of accurate extreme tails. Report uncertainty and run dependence. Per-core affinity does not isolate shared caches, memory bandwidth, package power or thermal limits. No fuzzing, conversion, or research workload should run concurrently with measurement blocks.

## P4 accounting measurement boundary — execution clarification, 2026-10-18

The index's requested/reserved structure subtotal and independent slot recount are exact. The required allocator contribution is measured separately with `tiplog_index_memory` in fresh single-thread glibc release processes: raw before/after mallinfo2 fields, Δ(uordblks+hblkhd), Δ(arena+hblkhd), exact Index subtotal and signed difference are preserved. [Source, commands, results and limitations](../../results/p4/memory-sources.md). This process boundary covers the heap-owned Index and its allocation history, including rounding/retained allocation effects; it is not RSS or an assertion about individual allocation headers. ASan/alternate allocators are excluded from this diagnostic, while the full required sanitizer correctness checks remain enabled and separate. No acceptance threshold is reduced.
