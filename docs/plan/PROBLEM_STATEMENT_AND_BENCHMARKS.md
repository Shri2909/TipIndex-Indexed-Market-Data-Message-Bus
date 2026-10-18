# Final problem statement and expected benchmark outputs

Consolidated brief for the **v1.1 / Tier B** plan, 2026-10-17. The user approved this scope, separately authorized the now-complete P0 tooling phase, then jointly authorized P1–P5 in dependency order. P6–P8, Tier C and roadmap work remain outside this authorization. This brief restates the existing scope and protocol; it does not itself grant approval, authorize implementation, add performance targets, or report benchmark measurements. [VALIDATION_PLAN.md](VALIDATION_PLAN.md) remains authoritative for benchmark details; actual execution evidence is in [PROGRESS](PROGRESS.md).

## 1. Project title

**tiplog: bounded market-data replay with partition indexes and workload-aware storage-layout optimization.**

## 2. Problem statement

Build and evaluate a C++20 retained-log pub/sub engine for historical NASDAQ TotalView-ITCH 5.0 events. Consumers subscribe to exact topics or topic subtrees and resume from a sequence checkpoint. A bounded byte ring retains recent events; if the requested range expires, recovery must report that explicitly. Every successful replay must return exactly the matching retained events in original global sequence order, once each.

The engineering problem is to reduce the CPU work of selective catch-up while controlling index memory and publisher maintenance cost. Compare a tuned sequential scan with shared-block partition indexes and several k-way merge implementations. Determine the workload region where each approach is effective rather than assuming that indexing or one merge kernel always wins.

The optimization problem is to group a topic tree into connected stores under a store-count budget, minimizing an explicit workload-weighted model of recovery cost. Compare a fixed-depth baseline and independent greedy heuristics with exhaustive enumeration and class-mask DP on instances within exact-solver limits. Report exactness coverage and the CPU/memory cost of solving the model.

The core produces a deterministic single-process, single-threaded replay engine, an offline layout optimizer, and a reproducible report. R1–R4 extend this into durable physical storage, disk recovery and concurrent access. Tier C T4 adds scheduled-arrival overload/latency measurements.

## 3. Inputs and deliverables

- Primary source: `12302019.NASDAQ_ITCH50.gz`, downloaded and verified in authorized P1. Characterize the full stream; use declared trace windows for retained-log experiments.
- Primary topics: `itch/<SYM>/<family>/<type>`, with specified market-wide and exceptional routing; symbol-level index partitions. H-flat is a hierarchy sensitivity case.
- Consumer workloads: BOOK, TAPE, AUCT, STAT and REPLAY, composed into W0–W3 as specified in ARCHITECTURE §2. These are declared workloads, not measured production subscription demand.
- Executables/libraries: trace reader, deterministic driver, ring/scan engine, pooled indexes, StdPQ/BinHeap/Quad/Loser kernels, Auto mode, layout solver, independent reference checks.
- Evidence: dataset manifest, environment/configuration records, raw runs, summaries, regenerable figures, technical report and reproduction guide. Resume numbers come from this evidence only.

## 4. Expected benchmark matrix

| Experiment | Workload/settings already in the plan | Comparison | Output and hypothesis |
|---|---|---|---|
| T1 — retained catch-up | 1 GiB ring; 2 GiB for longer backlogs; 1/10/60/300 s of market-time backlog at a 10:00 anchor; single symbols and baskets of 10/100/1,000; BOOK/TAPE/all-trades/full-stream | Scan versus indexed kernels, with the declared wide-subscription fallback | Replay wall/CPU time, entries visited, records fetched, logical bytes inspected, delivered events and status. Hypothesis: selected partitions containing little traffic favor indexing. |
| T2 — aggregate reader cost | 1/10/100/1,000 readers, each recovering a 10 s backlog sequentially on one core | Scan versus indexed, including amortized index-maintenance cost | CPU-seconds per second of market data served; total recovery cost and failures. This is not concurrent-reader scaling. |
| T3 — crossover and Auto | 10/1,000/100,000 partitions; Zipf s=0/0.8/1.2; mean same-partition run length 1/16/256; breadth/selectivity sweeps | Scan, indexed and calibrated Auto, with evaluation separate from calibration | Crossover map. Hypothesis: candidate fraction, breadth and interleaving determine the useful operating region. |
| M1 — merge cost | k=1/2/4/8/16/64/256/1,024/4,096/16,384; 2^22 outputs; uniform, bursty and skewed owners | StdPQ, BinHeap, Quad and Loser | ns/output, plus instructions/branch/cache counters only when available. Hypothesis: bursty inputs favor early-exit heaps; large interleaved inputs may favor loser trees. |
| M1-touch — fetching effect | M1 with an 8-byte record touch in a 1 GiB array | The same kernels | ns/output; how kernel differences change when fetching records is included. |
| M2 — publisher overhead | Index on/off; empirical payload mix and fixed 12/32/64/256-byte payloads; 1/100/10,000 partitions; block entries 256/1,024 | Identical publication workloads with and without index maintenance | ns/publish, evictions, allocation/reclamation rates and high-water memory. Quantifies the cost paid to accelerate recovery. |
| M3 / T5 — memory and block size | 64/256/1,024/4,096 entries per block; real partition sizes and time-of-day snapshots | Different block sizes and analytical accounting | Seek time, scan time/entry, total index bytes/retained record, live/stale entries, open/sealed slack, metadata and high-water memory. |
| L1 — characterize the input | Full-day counts/bytes and declared windows | Measured distributions | Symbol concentration, message mix, run lengths, bursts, tree sizes and workload-mask sizes. Skew is a measurement, not a starting result. |
| L2 / L3 — layout quality | W0–W3; same per-partition store budget; fixed-read-cost sensitivity beta/alpha=0/64 KiB/1 MiB; synthetic trees for scaling | Fixed depth, greedy min/max, ENUM and MASK-DP where solvable | Modeled bytes/cost, amplification, stores touched, exact optimality gaps, solver time/memory and exact coverage. No predetermined reduction percentage. |
| L4 / L5 — model checks | Article worked example and H-spec versus H-flat | All applicable methods on identical inputs | Reproduce the defined example; show where hierarchy alone makes fixed-depth exact-topic filtering waste zero. |

The publisher is paused during T1–T3 recovery measurement. T1–T3 time `open_replay` through completion, excluding trace loading and ring prefill. M2 separately measures the writer cost, and T2 charges it to indexed recovery totals. Auto evaluation uses choices frozen before the evaluation workload.

## 5. A numerical expectation that follows from the design

Let N be the number of DATA records in a replay range, and q the fraction belonging to selected index partitions. Let D be matching delivered records. A tuned scan traverses approximately N DATA records; indexed replay traverses approximately qN candidates, plus seek/boundary work and merging. D can be much smaller than qN because event-type filtering occurs inside a symbol partition.

For an illustrative range with N=10,000,000:

| Candidate partition fraction q | Scan DATA records traversed | Indexed candidate records, approximately | Ideal candidate-traversal ratio |
|---|---:|---:|---:|
| 1% | 10,000,000 | 100,000 | 100x |
| 10% | 10,000,000 | 1,000,000 | 10x |
| 100% | 10,000,000 | 10,000,000 | 1x |

These are arithmetic illustrations, not measured timings or speedup targets. Seek/merge costs, memory locality, output hashing, record sizes and index maintenance determine the actual time ratio. A 1% output selectivity D/N does not establish q=1%. The full-stream implementation can select its scan fallback.

Likewise, compact index entries use 4 bytes each, but that is not total allocated bytes per retained record. Pool slack, stale entries, block metadata, expiry structures, partition lists and allocator overhead must be measured. No fixed total-memory target is asserted.

## 6. Numerical commitments and measurement protocol

These are the existing correctness/reproducibility thresholds, not new performance promises:

| Commitment | Required evidence |
|---|---|
| Correctness | Zero failures in required release/ASan-UBSan tests; zero unresolved sanitizer reports |
| Differential testing | At least 1,000 seeds x 10,000 operations per selected mode/kernel in release; at least 200 seeds under sanitizers |
| Fuzz gates | At least 30 minutes per target at the relevant gate; every discovered crash fixed and regressed |
| Optimizer cross-check | DP=ENUM on at least 10,000 random instances, for every tested k<=K; zero mismatches |
| Dataset and replay identity | Independent per-type/per-locate counts agree; repeated conversion hashes agree; output and outcome agree with the oracle |
| Timing evidence | 30-repetition pilot; 15 microbenchmark repetitions; at least 10 measured process repetitions for end-to-end configurations |
| Reporting | Median, variability, n and 95% bootstrap confidence intervals; paired resampling for matched rounds; all non-ok outcomes retained |
| Reproduction | Every reported figure regenerates from saved raw results; commands, hashes and build/environment metadata retained |

Pin timing runs to a verified P-core, preserve identical inputs/builds/output sinks, and run no fuzzing/conversion workloads concurrently with measurements. Hardware counters require successful event probes; fallback data is time/CPU plus explicitly simulated Cachegrind results on reduced cases. There is no required privileged setting change.

Recovery-duration measurements in the core do not establish trading/message latency distributions. Tier C T4 measures scheduled-arrival completion latency and publisher lag under overload. Physical disk reads and disk-recovery improvements require R1–R3; L2/L3 output modeled costs only.

## 7. How final results will be presented

Every result row will contain the workload/configuration, baseline measurement, candidate measurement, ratio/difference with uncertainty, repetition count, correctness status and raw-evidence link. Values stay unfilled until the authorized experiments run.

Final plots include recovery cost versus breadth/backlog, scan/index crossover, merge cost versus k/interleaving, publisher overhead, index memory versus block size, and layout cost versus store count with exact-gap/coverage plots.

Success means a correct bounded replay engine and reproducible answers to the tradeoffs above. Improvements may be workload-dependent; a demonstrated crossover or a merge-only gain disappearing end-to-end is a valid result. The plan sets no minimum speedup, greedy-gap percentage, throughput floor or guaranteed kernel winner.
