# P2 independent oracle and deterministic driver

Access date: 2026-10-17. P1's gate passed before this P2 implementation began; the user's joint P1–P5 instruction authorizes this phase. This document records implementation choices and source-reading limits, not an implementation gate by itself.

## Material inspected

- Read the master prompt, INDEX/PROGRESS current authorization and P1 gate, complete joint execution prompt, ARCHITECTURE §§3.1–3.7, 5.0–5.4, 9–10; VALIDATION §§1–4 and §13 V35/V36/V38; relevant P2 tasks and STUDY_PLAN prerequisite map/ST-03's corrected hand example. Consulted the dated review, findings inventory #8–10/#11–21/#45–47 and problem/benchmark brief.
- **S03 primary transcript**, [Patti/Minsky, episode 14, 2022-04-20](https://signalsandthreads.com/state-machine-replication-and-why-you-should-care/): re-inspected 00:37:16–00:44:33, especially proxy filtering, opaque payloads, hierarchical topics and canonical order across topics. These are published descriptions. No Aria implementation was inspected, copied or reconstructed. Our retention, snapshot and error rules are independent project contracts.
- **S61 primary article**, [Maczka, 2026-10-13](https://blog.janestreet.com/flex-model-an-event-driven-feature-engineering-system/): inspected “Why not Incremental?” and “Keeping history in the graph,” including repeated-price/coalescing examples. It motivates preserving distinct sequence-numbered events. No feature graph, strategy or internal code enters this phase.
- The already inspected S11/S13 source limits remain in [P1 source review](../p1/review-sources.md). Oracle arithmetic is an independent restatement of the approved design; no Aeron/Kafka header, retention helper or implementation code is reused.
- Inspected the installed GCC **15.2.0** library's `/usr/include/c++/15/bits/random.tcc`, `mersenne_twister_engine::operator()` (lines 450–470), and declaration/parameters in `bits/random.h`. The driver calls the standard `std::mt19937_64` engine and applies its own explicit modulo budget mapping, avoiding library-specific distribution mapping. No standard library source was copied; no upstream source-code commit is claimed for this installed package.

## Finding → decision → task → symbol → validation

| Finding/source | Independent decision/invariant | Task and implementation | Check / executed evidence |
|---|---|---|---|
| Findings #45–46; VALIDATION §2 | Reference shares only value types, never registry/filter/ring helpers | P2.3 `tests/ref/scan_oracle.*`: `ScanOracle`, direct `matches` string union, copied full history | V09 hand-computed retention, boundary/union and equal-event tests; phase command records will supply actual results |
| ARCH §3.5/5.3; corrected ST-03 exercise | Division alignment; modulo placement; explicit DATA/PAD item starts; tail first start ≥ end−C | P2.3 `ScanOracle::publish`, `tail_pos`, `tail_seq`, `items`, `retained_records` | `OracleRetention.V09HandComputedPadAndWrap`: C64/max32, PAD [56,64), final head128/tail64/tailseq3; exact-fit and rejected-state tests |
| Review: full record vs PAD size, rejected mutation | DATA min16, PAD min8; max_record≤C/2; allocate/check before changing published history | P2.3 `ScanOracle` config/publication preflight | Invalid config/oversize/path/lifetime regression tests; no production ring implemented here |
| Review/findings #16–19; amended V35 | Captured upper, independent last-delivered vs resume progress, conservative unread checkpoint, max0 no progress, terminal check before expiry | P2.3 `OracleReplay` constructor / `next_batch` | Future UINT64_MAX, exact-final-budget then eviction, irrelevant expiry, zero-output advancement/chaining and delivered-prefix/error-field tests |
| S03/S61; findings #9/#20 | Canonical dense sequence, opaque payload copies, union of terms emits each sequence once; equal values remain distinct events | P2.3 matching/replay; P2.4 `driver::drive_trace` | Equal-valued event and overlap tests; ordered sparse-dictionary trace-to-oracle test |
| ARCH §5.0/§3.7; input identity | Driver uses actual dictionary IDs to resolve paths; deterministic tick budgets, pauses, cadence, seed and canonical diagnostic digests | P2.4 `src/tiplog/driver/trace_driver.*`; `tools/tiplog_sim/main.cpp` | Sparse IDs 7/900001; repeated seeds/schedules/digests, changed-seed schedule, zero budget, record limit and rejection tests |
| Module boundary | Production driver and CLI do not link test reference; P2 CLI explicitly identifies its recording backend | P2.4 `cmake/p2_ref.cmake`, `tiplog_sim` | Link inspection and CLI aggregate output; production engine integration belongs to P3 |

All test traces and payloads in tracked files are synthetic. The CLI prints aggregate counts and diagnostic FNV-1a digests, never payload bytes. FNV is not substituted for the P1 cryptographic checksums. Driver schedules are deterministic work controls, not timing/latency evidence or claimed uniform sampling. P2's unit gate does not substitute for P3–P5 CC-2 differential coverage or F3 timed fuzzing.

## Execution status

Implementation is written. Root integration owns centralized release/ASan configure/build/test commands to avoid conflicting builds. Until their command records are linked here, those checks remain **pending**. No standalone driver benchmark or P3 production engine was run by this subtask.

## Executed P2 gate — 2026-10-18

Central final release and ASan/UBSan suites each passed **52/52 cases**, including **37 P2 cases** (16 topics/subscriptions, 16 oracle, 5 driver). Final builds are warning-free. Leak checks remain enabled; no sanitizer report. The real-trace recording-driver smoke published 10,000 events and aggregate digests without payload logging. Exact commands/results are linked in [phase-gate.json](phase-gate.json); this supersedes the earlier pending execution rows. [Implementation snapshot](implementation-manifest.json). P3 differential/fuzz checks remain later gates.
