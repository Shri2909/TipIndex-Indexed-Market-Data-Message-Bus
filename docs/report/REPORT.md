# tiplog — technical report

The measurements and gates below describe the accepted P0–P8 source. Subsequent
audit fixes are recorded in [REMEDIATION.md](REMEDIATION.md); current implementation
changes do not constitute new controlled performance measurements.
The separately approved optional [F-01 polling feature](POLL_BUDGET.md) has its
own current-source correctness evidence and synthetic study. Figures and claims
below remain the historical P0–P8 results.

**A C++20 retained-log market-data bus with indexed catch-up, and an exact storage-layout optimizer**

Plan v1.1, Tier B core · 2026-10-25 (Asia/Kolkata) · Phases P0–P7 have passed their gates; this report is the
P8 deliverable. Acceptance is recorded in the per-phase gates (`results/p<N>/phase-gate.json`) and in
`results/p8/phase-gate.json`. How to rebuild every number is in [REPRODUCE.md](REPRODUCE.md).
The two detailed result reports are [results_tip.md](results_tip.md) (P6 engine experiments) and
[results_layout.md](results_layout.md) (P7 optimizer studies). This report summarizes them and adds
the design and correctness context; where it quotes a number, the linked report or raw file is the authority.

---

## 1. Abstract

tiplog is a deterministic, single-threaded C++20 publish/subscribe log for NASDAQ TotalView-ITCH 5.0.
Subscribers ask for an exact topic or a whole topic subtree. The engine keeps the most recent messages in
a byte-bounded ring (the *tip*) and can serve a lagging subscriber either by **scanning** the retained
stream or by **merging per-partition indexes** kept in a shared block pool. An offline optimizer chooses
how to split each symbol's topics into on-disk stores so that typical readers waste fewer bytes.

On one real 2019-12-30 Nasdaq morning window, on one laptop, indexed recovery of a single-symbol
order-book subscription used **40.6× less CPU than a scan** (median of 20 paired process rounds,
95% CI 39.5–41.7). A broad 1,000-symbol subscription went the other way (**0.585×**, i.e. the index was
slower), and keeping the index costs the publisher measurable CPU. The engine passed 186 C++ tests in
release and ASan/UBSan builds, 108 million randomized differential operations against an independent
oracle, and three 30-minute fuzz campaigns.

For storage layout, the project formalizes store splitting as a budgeted connected-partition problem
and solves it exactly with a class-mask dynamic program (MASK-DP). MASK-DP matched exhaustive
enumeration on 10,000 random trees for every budget with zero mismatches, and reproduced the
article's worked example exactly. Under an assumed four-consumer workload (W1), the exact layout lowers
**modeled** weighted read bytes by 27.9% versus the fixed three-segment split, using no more stores per
symbol. All storage numbers are modeled bytes, not measured disk I/O.

## 2. Background

### 2.1 NASDAQ TotalView-ITCH 5.0

ITCH is Nasdaq's binary market-data feed: add-order, execute, cancel, delete, replace, trade, auction
(NOII) and administrative messages (S05). The historical sample files use *BinaryFILE* framing: each
message is preceded by a 2-byte big-endian length, and a zero length marks the end of the session
(S08). Messages identify instruments by a *stock locate* code; the symbol name appears only in the stock
directory message, so a converter must map locate → symbol before it can route messages to topics.

The only real input is `12302019.NASDAQ_ITCH50.gz` (3,524,013,057 bytes, SHA-256
`ef03df46…6c99c689`), [manifest](../../data/manifest.json). Two independent parsers (Python converter and a
C++ framing walker) counted **268,744,780 messages and 8,251,407,909 decompressed bytes**, with
per-type and per-locate counts in exact agreement ([CC-6](../../results/p1/cc6-reconciliation.json)).
The file **lacks the BinaryFILE terminator**, so it is recorded as `incomplete=true`: the gzip is intact
and every framed message parses, but completeness of the exchange session is not established.

### 2.2 The reference article — what it states versus what this project does

Jane Street's article "Scaling and benchmarking a critical message bus using a new indexing strategy"
(S01) describes Aria, their internal message bus. The research ledger labels its statements A1–A21
([RESEARCH §1](../plan/RESEARCH.md)). In summary, the article **states** that: the recent stream lives
in an in-memory ring buffer and lagging clients recover from it (A3); a linear filtering pass made some
servers hit 100% CPU (A5); they index per *topic partition* (shared two-segment prefix) and rebuild order
with an n-way min-heap merge (A6–A7); index entries live in a shared pool of 1,024-entry blocks (A12);
on disk, an older rule gives each direct child of a partition its own store (A15), which fails when one
topic dwarfs its siblings (A16); and the new splitter is "a greedy clustering algorithm with a binary
search" (A19). Its reported CPU reductions are for their production/staging servers (A2, A21).

This project **independently** designs and implements a comparable engine and optimizer for ITCH.
It does not have or reproduce Aria's code, and it does not transfer Aria's results. The article does not
specify its greedy objective or search variable; tiplog's threshold heuristics (H-KM-min/max) are
labeled independent designs, and the exact methods (ENUM, MASK-DP) are this project's own.

## 3. Problem and semantics

Full contracts are in [ARCHITECTURE §3](../plan/ARCHITECTURE.md). The essentials:

- **Topics.** ITCH messages are routed to a spec-derived hierarchy `itch/<SYM>/{stock,add,modify,trade}/<type>`
  plus `noii`, `rpii`, `dlcr` leaves and `itch/_market` (*H-spec*). A *partition* is a two-segment prefix
  (one symbol, or `_market`). The flat tree `itch/<SYM>/<type>` (*H-flat*) is kept only as a sensitivity
  case, because there the three-segment rule already gives every exact topic its own store.
- **Publication.** One publisher assigns dense global sequence numbers starting at 1 and a never-recycled,
  8-byte-aligned logical byte position to every record.
- **Subscriptions.** A set of `Exact(t)` and `Subtree(p)` terms with union semantics: each matching
  message is delivered at most once per subscription. Distinct events with equal payloads are still
  distinct deliveries.
- **Retention.** A byte-capacity ring with whole-record, oldest-first eviction.
- **Replay.** `open_replay(sub, after_seq, mode)` captures an upper bound at open and delivers matching
  records in `(after_seq, upper_seq]` in sequence order. It ends with `Done`, or with an explicit
  `HistoryExpired`/`FellBehind` error after a correct delivered prefix. **Scan, Indexed and Auto share one
  checkpoint and expiry contract**, so they produce identical outputs and identical outcomes. Live tailing
  is a chain of such snapshots, and chaining is exact.
- **Not guaranteed in the core:** durability, crash recovery, cross-process access, networking and
  concurrent readers ([ARCHITECTURE §3.9](../plan/ARCHITECTURE.md)).

## 4. Tip store design

Public entry points are in [engine.hpp](../../src/tiplog/engine/engine.hpp).

- **Ring** ([ring.hpp](../../src/tiplog/ring/ring.hpp)). An 8-byte-aligned byte ring. A record that would
  straddle the end is preceded by a PAD record, so every record is contiguous. Representation limits are
  checked: maximum record ≤ C/2, minimum DATA record 16 B. Positions are 64-bit and monotonic, so a stale
  reference is detected by comparing positions rather than reused offsets.
- **Partition index** ([index.hpp](../../src/tiplog/index/index.hpp)). One dense posting list per partition,
  storing record positions in blocks drawn from a **shared fixed pool** (A12's idea; block size B is a
  parameter). Sealed blocks are reclaimed through an **expiry min-heap** ordered by their newest entry, so
  a block is freed only once all its records have left the ring. Memory accounting counts live, expired,
  open/sealed slack and free slots exactly.
- **Merge kernels** ([kernels.hpp](../../src/tiplog/merge/kernels.hpp)). Four ways to merge k partition
  cursors back into sequence order: `std::priority_queue` (StdPQ), an early-exit binary heap (BinHeap), a
  4-ary heap (Quad, two padding layouts) and a loser tree (Loser). Keys are packed 64-bit
  (position, cursor), with checked limits.
- **Auto policy.** Chooses Scan or Indexed per request from the number of partitions and their share of the
  range. Its thresholds (`max_partitions=64`, `max_fraction=1.0`) were selected on separate training data
  and frozen before evaluation ([policy](../../results/p6/auto-thresholds.json)). Wide terms that can span
  partitions created later always use Scan.

## 5. Correctness evidence

The plan fixed the correctness and reproducibility criteria before implementation
([VALIDATION §1.1](../plan/VALIDATION_PLAN.md)). Every one is met by executed evidence:

| ID | Criterion | Executed evidence |
|---|---|---|
| CC-1 | All V-tests pass in release and ASan/UBSan, 0 sanitizer reports | Final source: **186/186** C++ tests in each build (166 engine + 20 optimizer), 0 sanitizer reports ([release](../../results/p7/final-release-tests-20261025T155552.324180Z.json), [ASan/UBSan](../../results/p7/final-asan-ubsan-tests-20261025T155555.617470Z.json)); **151** Python tests ([pytest](../../results/p7/final-python-p7-20261025T155605.212269Z.json)) |
| CC-2 | Randomized differential tests: ≥1,000 seeds × ≥10,000 ops per (mode, kernel) in release; ≥200 seeds in ASan/UBSan | All 9 mode/kernel configurations: 1,000 seeds × 10,000 ops in release (90 M ops) and 200 seeds in ASan/UBSan (18 M ops), 0 failures ([CC-2](../../results/p6/CC2-all-configurations.json)) |
| CC-3 | Every fuzz target ≥30 min at its last gate | F1 trace reader 1,801.9 s (53.1 M executions) and F2 ITCH walker with real seeds 1,801.8 s (2.04 M executions) ([F1/F2](../../results/p1/fuzz-gate-verified.json)); F3 structure-aware engine fuzzer 1,802.6 s (39,231 executions), no unresolved crash ([F3](../../results/p6/fuzz-prefix-final-verified.json)) |
| CC-4 | Every configuration matches the independent oracle's output **and outcome** | The P6 saved-output audit passed **10,295,181 checks, 0 failures** over every measured configuration ([P6 gate](../../results/p6/phase-gate.json)) |
| CC-5 | MASK-DP = ENUM on ≥10,000 random instances for every k ≤ K, 0 mismatches | 10,000 instances in each build: 57,461 exact-count and 57,461 at-most comparisons, 96,322 reconstructed layouts, 0 mismatches; release and sanitizer results hash-identical ([release](../../results/p7/cc5-release.json), [ASan/UBSan](../../results/p7/cc5-asan-ubsan.json)) |
| CC-6 | Python converter counts = independent C++ walker counts, per type and per locate | 18 type keys and 8,907 locate keys, 0 mismatches ([CC-6](../../results/p1/cc6-reconciliation.json)) |
| RC-1 | Every figure regenerates from saved raw results with one command | `python -m tiplog_py.figures.build --all` rebuilt F01–F18 ([command record](../../results/p7/figures-all-final-20261025T154953.610882Z.json)); P1/P6 figures checked unchanged apart from PDF timestamps ([compatibility](../../results/p7/figure-extension-compatibility.json)) |
| RC-2 | Re-running the converter gives byte-identical traces | Both hierarchies converted twice with equal SHA-256 (H-spec `6062bdb9…`, H-flat `89cc31ac…`) ([data gate](../../results/p1/data-gate.json)) |
| RC-3 | Deterministic runs give identical digests across repeats and GCC/Clang builds | 180 child runs over all 9 mode/kernel configurations, GCC and Clang release builds, 2 repeats per compiler; 170 output equalities checked, 0 failures ([RC-3](../../results/p6/rc3-final-verified.json)) |

**How the oracles stay independent.** `ref::ScanOracle` (tests only) keeps the whole published sequence and
matches subscriptions by string-prefix logic on topic paths, not by the engine's topic ids or partitions.
The Python digest oracle computes expected outputs from the trace file alone. For the optimizer, ENUM is
the oracle for MASK-DP. Two cost evaluators (a formula and a store materializer that simulates reads) and
a third raw-path test oracle share no optimized solver logic ([P7 source map](../../results/p7/p7-source-map.md)).

**Applicability.** P7 changed no engine, parser, oracle or fuzz source: the 19 core binaries and their
dependencies are byte-identical to the accepted pre-P7 baseline ([P7 gate checks](../../results/p7/gate-checks.json)),
so the long P1–P6 campaigns above still describe the final engine.

## 6. Experimental method (P6)

Full protocol: [results_tip.md, "Measurement and statistics"](results_tip.md).

- **Machine.** 12th Gen Intel Core i5-1235U laptop. GCC 15.2 release build (`-O2 -g -march=x86-64-v3
  -DNDEBUG`, C++20). Timed work pinned to CPU 2 (a P-core); the CPU was checked at both ends of each run.
- **Controls without privileges.** AC power, per-process ASLR disabled, ≥60 s settling per block, and CPU
  frequency sampled at the measurement boundaries. No governor, turbo, SMT or kernel setting was changed
  (approved decision DEC-2). Hardware counters were unavailable (`perf_event_paranoid=4`), so no
  hardware-counter claims are made.
- **Repetition.** Pilots measured noise (M1 CV 1.85%, T1 CPU CV 9.87%). Micro benchmarks used 15
  repetitions per configuration. Recovery and memory workloads used **20 fresh-process rounds** per
  configuration plus one saved, excluded warm-up.
- **Fairness.** Every mode replays the same trace, prefill and subscription and writes to the same output
  sink. Recovery timing covers `open_replay` through completion: seek, filtering, merging and output.
  It excludes trace loading and ring prefill.
- **Statistics.** Medians with seeded 10,000-resample percentile-bootstrap 95% CIs. Speedup ratios
  resample whole matched process rounds. Frequency deviations over 10% are flagged and kept.
- **Held-out policy.** Auto was trained on seed 20191230 and evaluated on seed 20191231.

## 7. Results (P6)

All numbers are conditional on the stated configuration; complete tables, every configuration's IQR and
raw links are in [results_tip.md](results_tip.md), [tip-summary.json](../../results/derived/tip-summary.json)
and figures F06–F13.

- **M1 — merge kernels depend on input shape.** At k=64 streams, the loser tree was cheapest for
  uniformly interleaved owners (11.3 ns/output vs BinHeap 19.9), while the early-exit BinHeap was cheapest
  with long same-owner bursts (4.5 ns/output vs Loser 9.5). No kernel wins everywhere
  ([F06](../../results/figures/F06_merge_cost_vs_k.png), [F07](../../results/figures/F07_merge_run_length.png)).
- **M2 — the index costs the publisher.** With 10,000 uniformly chosen partitions and B=256,
  publishing cost 124.4 ns/message with the index versus 62.3 without; with 1 or 100 partitions the index
  added about 13–14 ns ([F08](../../results/figures/F08_publish_index_cost.png)).
- **M3 — block size trades seek against scan.** On all 32.8 M real-window postings, scanning cost fell from
  5.60 ns/entry at B=64 to 3.64 at B=4,096, while seeking was cheapest around B=256–1,024.
- **T1 — selective recovery wins, broad recovery loses.** At 10:00, 1 GiB ring, B=1,024, 10 s backlog,
  repeat-warm: BOOK-top1 recovery took 3.92 ms by Scan and 0.096 ms Indexed, a **Scan/Indexed ratio of
  40.62 [39.45, 41.69]**, because the index fetched 1,573 candidates instead of scanning 184,550 records.
  BOOK-top1000 reversed it: **0.585 [0.581, 0.593]**. Auto chose Scan there (Scan/Auto 0.983 [0.976, 0.999]).
  Full-stream Indexed falls back to Scan by contract ([F09](../../results/figures/F09_catchup_breadth.png),
  [F10](../../results/figures/F10_replay_work.png)).
- **T2 — many readers.** Charging the publisher's index-maintenance delta once to the whole cohort, a single
  reader whose subscription matched nothing lost (Scan/Indexed 0.616), while cohorts of 10, 100 and 1,000
  sequential readers gained 6.3×, 59.7× and 369× (repeat-warm). This is for the assumed sparse W2 reader
  mix and sequential readers, not concurrent scaling ([F11](../../results/figures/F11_many_readers_cpu.png)).
- **T3 — held-out crossover.** Over 486 synthetic comparison cells, Indexed/BinHeap's CI was entirely in
  favor of the index in 368 of 432 valid cells and against it in 50; Auto/BinHeap reduced cells clearly
  favoring Scan to 10 of 486, but 171 were indistinguishable. 54 cells per direct kernel exceed the packed
  cursor limit and are reported as `invalid_config` ([F12](../../results/figures/F12_scan_index_crossover.png)).
- **T5 — memory.** With 21,979,412 live postings at 10:00, the requested index reserve ranged from 7.3 to
  19.5 bytes per live posting across B=64–4,096. Four-byte postings are therefore not four bytes per record
  once blocks, slack, metadata and the expiry heap are counted ([F13](../../results/figures/F13_index_memory_slack.png)).
- **Outcome accounting.** 125,700 `ok`, 4,320 `invalid_config` (the packed-limit cells) and 1 externally
  interrupted micro attempt; no oracle mismatch, `history_expired` or `fell_behind` among measured rows.

## 8. Storage-layout optimization (P7)

Full results: [results_layout.md](results_layout.md). Model: [ARCHITECTURE §6](../plan/ARCHITECTURE.md).

### 8.1 Model M-store

Within each partition (one symbol's topic tree), a layout cuts tree edges, producing **connected
components**; each component is one store. A store holds every message of its topics, including messages
published on internal topics. Data is never replicated, and stores never span partitions. A consumer
class reads a set of topics (an exact topic, a subtree, or a multi-symbol *basket*) over the whole window
and pays each touched store once per request. The objective per partition is

`J = α · Σ_classes f·(bytes read) + β · Σ_classes f·(stores touched) + γ · (stores materialized)`,

with workload frequencies f, a byte cost α=1, a per-store-read sensitivity cost β ∈ {0, 64 KiB, 1 MiB}
(not a measured disk cost), and a store budget. A record's modeled size is `align8(16 + ITCH payload)`.
All costs use exact rationals or checked scaled integers; ties and representation limits are deterministic.

**Workloads (assumed, not measured).** W0: every topic read exactly, equally weighted. W1: four consumer
roles — order book (BOOK), trade tape (TAPE), auction (AUCT) and statistics (STAT). W2: W1 reweighted by
symbol activity rank. W3: W1 plus multi-symbol replay baskets at weight 1/10.

### 8.2 Methods

| Method | What it is | Exact for J? |
|---|---|---|
| H-BASE | The article's old rule (A15): one store per direct child of the partition root | No (baseline) |
| H-KM-min / H-KM-max | Threshold greedy with hot-topic isolation, binary search over an integer threshold in [0, W_total]; min/max ends of the feasible threshold plateau | No; heuristics |
| ENUM | Gray-code enumeration of all edge-cut subsets | Yes, where it finishes |
| MASK-DP | Tree DP over (subtree, store count, open class mask, materialization state) with reconstruction; O(\|V\|·K·2^b) for b classes | Yes, where it finishes |
| Global sweep | Nonnegative multiplier λ on store count across all partitions | Certifies only *supported* budgets, and only when every partition's curve is complete |

Resource caps were frozen **before** any study: ENUM ≤22 edges, DP ≤16 classes, 2,000,000 states,
2,000,000 work units, 500 ms per call ([protocol](../../results/p7/protocol.json)). A capped run is never
treated as optimal and contributes no exact gap.

### 8.3 Worked example (L4)

The article's figure (two partitions L and R, joint budget of four stores) reproduces exactly
([worked example](../../results/p7/worked-example.json), [F17](../../results/figures/F17_layout_worked_example.png)):

| Layout | Waste (bytes) |
|---|---:|
| H-BASE | 5,517,460,497 |
| H-KM-max (= the article's "after" figure) | 39,881,491 |
| H-KM-min = ENUM = MASK-DP optimum | **30,029,491** |

So the article's published layout is the largest-threshold end of the plateau, not the minimum for this
objective; the article's exact procedure cannot be identified from the figure.

### 8.4 Results (L2, L3, L5)

The full study attempted **214,668 cases** (2 hierarchies × 4 workloads × 3 β × 8,907 partitions, plus
900 synthetic trees) and recorded **1,073,340 method results**, with no audit failures
([summary](../../results/derived/layout-summary.json), [gate checks](../../results/p7/gate-checks.json)).

- **Exact coverage (L3).** DP solved every partition for W1, W2 and W3 under both hierarchies. W0 is much
  harder: under H-spec, ENUM solved 3,873/8,907 partitions and DP 2,034/8,907; the rest hit the frozen
  state/work limit. Coverage is also reported by bytes and by workload weight.
- **Cost at matched budgets (L2).** Each method gets at most the H-BASE store count of every partition.
  H-spec, β=0, all 8,907 partitions:

  | Workload | H-BASE J | KM-min J | Exact J | Exact vs H-BASE | KM-min vs exact |
  |---|---:|---:|---:|---:|---:|
  | W1 | 19,367,265,136 | 14,312,697,608 | 13,964,962,856 | −27.9% | +2.5% |
  | W2 | 53,063,664,304 | 37,453,911,320 | 37,046,713,312 | −30.2% | +1.1% |

  For W0 only a common solved cohort of 3,873 partitions has exact results, and they are not extrapolated.
- **Per-partition gaps (L3).** Aggregates hide spread: for W1 the median per-partition KM-min gap is
  188/2,715 (6.9%) with a maximum of 764/1,191 (64%); for W2 the median gap is 333/64 because many quiet
  partitions carry only STAT weight while the threshold rule uses volume ([F16](../../results/figures/F16_layout_gaps_scaling.png)).
  No threshold endpoint is best in every workload.
- **Trade-offs.** Raising β (a fixed charge per store read) makes the exact layouts merge stores: for W1
  the exact weighted stores touched fall from 81,202 to 51,072 between β=0 and β=1 MiB, while waste rises
  ([F14](../../results/figures/F14_layout_class_amplification.png)).
- **Global budgets.** The audited multiplier sweep (3,652,966 checks) certified 126 supported points in the
  18 strata with complete curves (W1–W3). W0 strata are incomplete and carry no global bound. At the H-spec
  W1 baseline forest budget of 44,504 stores, the best feasible point and the certified lower bound still
  differ by 307,754,907 modeled bytes, so that budget is not declared solved ([F15](../../results/figures/F15_layout_tradeoff.png)).
- **Hierarchy sensitivity (L5).** Under H-flat, the baseline already gives zero exact-read waste for W0
  (checked on all partitions and all β), so no waste-reduction claim is made for that hierarchy
  ([F18](../../results/figures/F18_layout_hierarchy.png)).
- **DP runtime (L3).** Under a controlled protocol (10 fresh-process rounds per input, quiescence rule
  passed for every round), MASK-DP solved 885/900 synthetic inputs in all rounds. For 4 classes and
  budget 4, the median solve time grew from 12.2 µs at 5 nodes to 1.63 ms at 1,000 nodes, roughly
  proportional to node count. The 15 inputs with 1,000 nodes, 4 classes and K=64 exceed the frozen
  state guard ([runtime campaign](../../results/p7/runtime-campaign.json),
  [quiescence](../../results/p7/runtime-quiescence.json)).

## 9. Limitations and threats to validity

- **One laptop, one day, one window.** A hybrid-CPU laptop, a single historical Nasdaq day and one morning
  window for timing. Results are not generalized across days, venues or hardware.
- **Nonexclusive host.** Background desktop and service activity was present; frequency was not fixed and
  flagged rows are retained. CIs describe repeat variation on this host, not host-independent truth.
- **No hardware counters.** `perf_event_paranoid=4`; no cache/branch causal claims.
- **Input incompleteness.** The source lacks its session terminator (`incomplete=true`).
- **Assumed workloads.** Subscriber mixes (P6 W2 cohorts; P7 W0–W3) and β values are assumptions and
  sensitivities, not measured demand or disk costs.
- **Throughput, not latency.** Recovery times are CPU/throughput measurements with the publisher paused and
  readers sequential. No latency distribution, p99 or p99.9 is reported; the open-loop T4 is Tier C.
- **Modeled storage.** P7 bytes are modeled from record volumes. No store packs exist, no disk reads were
  measured, and durability/crash recovery (R1–R3) are roadmap items.
- **Exactness scope.** "Exact" means optimal for model M-store, the stated workload, costs and budget, per
  partition, and only where a solver finished. W0 coverage is incomplete. Other layout models (replication,
  cross-partition bundling) are excluded.
- **Auto policy.** Trained on a finite grid; residual losses remain in held-out cells.
- **Execution history.** One P6 micro attempt was externally interrupted, and two P7 controlled-runtime
  attempts were discarded (host contamination; quiescence-rule rejection); their readings are not used.
  See Appendix E.

## 10. Related work

Read depth matters, so each source below is listed with what was actually read
([RESEARCH ledger](../plan/RESEARCH.md)).

- **The reference article** (S01, full text and figures) motivates the tip ring, partition indexes, the
  shared block pool and subtree stores; this report separates its statements (§2.2).
- **Merging.** LaMarca & Ladner on cache-aware heaps (S20, bibliographic); loser-tree results in an external
  sort (S21, abstract and conclusions), Prometheus postings (S22) and PostgreSQL discussion (S23, S49).
  These motivated testing four kernels without presuming a winner — and M1 found none.
- **Tree partitioning.** Kundu & Misra's linear minimum-count tree partition (S33, bibliographic/secondary)
  and Buchin & Selbach (S34, abstract and §1.1) underlie the threshold heuristic's own-problem contract.
  Tree-DP techniques (S35, bibliographic) and Everett's Lagrange-multiplier result (S36, abstract) inform
  MASK-DP and the nonnegative global sweep. No theorem from these is borrowed for M-store.
- **Workload-aware layouts.** Qd-tree (S37) and fine-grained partitioning (S38), abstracts only; drift-aware
  benchmarking (S50) informs the optional L6 study.
- **Durable pub/sub and logs.** Durable subscriptions that persist filtering information (S40, abstract),
  LevelDB/RocksDB log and manifest formats (S26, S27) and fsync/file-system studies (S28, S29, S55) inform
  the roadmap disk design only.
- **Measurement.** LLVM benchmarking guidance (S41), Google Benchmark (S42), measurement-bias studies (S44),
  coordinated omission (S43) and libFuzzer/sanitizers (S45).

## 11. Conclusion and roadmap

Indexed catch-up is worthwhile when a reader's partitions are a small share of the retained range, and it
is not free: broad subscriptions are better served by a scan, and the publisher pays to keep the index.
An Auto policy captures much of that crossover. For storage, a workload-aware exact layout substantially
reduces modeled read bytes relative to the fixed split under assumed W1/W2 consumers, simple threshold
greedy comes within a few percent in aggregate but can be far off on individual partitions, and exact
coverage is complete for W1–W3 but not for exact-topic-everything W0.

The full system remains a roadmap that is **not authorized**: a WAL with crash recovery, compaction into
store packs with a disk→tip handoff and measured α/β, a concurrent bus, and Tier C items such as open-loop
latency tests and drift studies ([IMPLEMENTATION_PLAN §7](../plan/IMPLEMENTATION_PLAN.md)).

## Resume bullets (measured numbers only)

These replace the placeholders in IMPLEMENTATION_PLAN §12. Each number is scoped as in the sections above.

- Built a C++20 retained-log pub/sub engine for NASDAQ TotalView-ITCH 5.0 (268.7 M messages in the
  2019-12-30 sample) with hierarchical exact/subtree subscriptions and a shared block-pool partition index.
  For a single-symbol order-book subscription, indexed catch-up used 40.6× less replay CPU than a linear
  scan (median of 20 paired runs, 95% CI 39.5–41.7), while broad subscriptions favored scanning; verified
  against an independent oracle with 108 M randomized differential operations, ASan/UBSan and three
  30-minute libFuzzer campaigns.
- Formalized topic-store splitting as a budgeted connected-partition problem and implemented an exact
  O(|V|·K·2^b) class-mask DP that matched exhaustive enumeration on 10,000 random trees for every budget
  (0 mismatches). On ITCH volumes under an assumed four-consumer workload, the optimal layout cut modeled
  read bytes by 27.9% versus the fixed three-segment split at no more stores per symbol; threshold greedy
  came within 2.5% in aggregate.

---

## Appendix A — Reproduction

Commands, dependencies, seeds, local-data requirements and the one-command figure build are in
[REPRODUCE.md](REPRODUCE.md).

## Appendix B — Checksums

| Artifact | SHA-256 |
|---|---|
| Source `data/raw/12302019.NASDAQ_ITCH50.gz` | `ef03df46a27e6bda4dead017f84c2e3979df7211f02c7868b51d53fceb99c689` |
| H-spec trace `data/traces/itch_20191230_0930_1000_spec.mdt` | `6062bdb96ec8354ecf650cdfb979574530b2120aa06047fa48d14a78e5936f70` |
| H-flat trace `data/traces/itch_20191230_0930_1000_flat.mdt` | `89cc31ac0c8907cf9552e85a60f04a221f4f2f9bc012769d0ab4de96376cbba2` |

Every figure, summary and raw output is hashed in its manifest: [p6-figures.json](../../results/figures/p6-figures.json),
[p7-figures.json](../../results/figures/p7-figures.json), [P7 gate](../../results/p7/phase-gate.json) and the
P8 artifact manifest `results/p8/artifact-manifest.json`.

## Appendix C — Configurations

- P6 experiment matrices and frozen protocol: [configs/P6](../../configs/P6/), [protocol freeze](../../results/p6/protocol-freeze.json), [Auto thresholds](../../results/p6/auto-thresholds.json).
- P7 study protocol and caps: [protocol.json](../../results/p7/protocol.json); inputs: [input manifest](../../results/p7/input-manifest.json); runtime protocol: [runtime-supplement.json](../../results/p7/runtime-supplement.json).
- Seeds: P6 training 20191230, held-out evaluation 20191231; P7 synthetic inputs, shuffles and bootstraps 20191230.

## Appendix D — Environment

12th Gen Intel Core i5-1235U (hybrid), Linux; GCC 15.2.0 and Clang 21.1.8; CMake 4.4.0; Python 3.14.4 in an
isolated venv with pinned packages ([requirements](../../py/requirements.txt)); Google Benchmark 1.9.5 and
GoogleTest 1.17.0. Captured environments: [P0](../../results/env/p0-environment.json),
[P6 closeout](../../results/env/p6-closeout-20261025.json), [P7](../../results/env/p7.json).

## Appendix E — Failures, deviations and repairs

Recorded so that nothing is silently dropped; details are in [PROGRESS](../plan/PROGRESS.md).

- **P6.** One M1-k256 attempt was externally terminated (replaced); one memory attempt was interrupted by a
  user-requested pause (accepted rounds resumed); the saved-output auditor needed path and T5 comparison
  repairs, with original audits preserved ([results_tip.md](results_tip.md)).
- **P7 studies.** The first study invocation was interrupted after two batches; it was resumed from the
  accepted batches and the partial output kept unaccepted. The first analysis attempt failed while
  serializing an optional exact mean; that field was removed and the case CSVs were shown byte-identical.
- **P7 controlled runtime.** The first attempt was contaminated by another project's CPU-bound processes on
  the solver CPU; the second was rejected by the pre-declared quiescence rule. At the user's instruction
  both were deleted and only the third, clean campaign is reported ([rule](../../results/p7/runtime-quiescence-rule.json)).
- **P8 closeout repairs.** (1) The managed empty `.git` directory's mode had changed from the recorded 0555 to
  0755 during P7, at the same moment empty `.agents`/`.aws`/`.codex` directories appeared (most likely
  the Codex sandbox, not project code); it was restored to 0555. (2) A
  no-op verification build rewrote five CMake `compiler_depend.make` bookkeeping files from CMake's
  placeholder text; nothing was compiled or linked, and the placeholders were restored byte-for-byte. (3)
  The closeout checker compared a start-of-run source snapshot against the bench tool that RC-3's own
  scope excludes; it now checks RC-3's declared dependencies and binds the bench tool to the accepted P6
  campaign provenance.
