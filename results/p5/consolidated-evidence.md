# P1–P5 consolidated evidence — 2026-10-19

**P1–P5 passed every acceptance gate. Execution stopped after P5.** This is an
evidence index for the approved v1.1 / Tier B sequence, not authorization or a
claim that later phases have begun. The user's joint instruction permits automatic
continuation through P5 only. P6–P8, Tier C and roadmap extensions remain outside
scope. [PROGRESS](../../docs/plan/PROGRESS.md) records the authorization and phase
handoffs. Earlier live/pending entries in historical ledgers are superseded only
by a later explicit executed gate.

P0 was reused: [preflight](../p0/preflight.json), [artifact checks](../p0/artifact-checks.json)
and [source/build manifest](../p0/artifact-manifest.json). The managed read-only
`.git` remains preserved; project-local metadata uses `.tiplog-git` through
[`scripts/git.sh`](../../scripts/git.sh). No privileged benchmark setting was changed.

## Acceptance state

Counts below are cumulative suite sizes at each phase boundary, not counts to
add together. Sanitizer acceptance retains ASan leak detection and UBSan halt on
error. Each linked command record contains actual argv, environment, exit status
and log; phase gates enumerate the individual completion criteria.

| Phase | Tasks / criteria | Actual verification | Authoritative evidence |
|---|---|---|---|
| P1 | P1.1–P1.7 **met**; every gate criterion met | 69 Python tests; 14 C++ trace/walker tests in release and ASan/UBSan; V01–V05, exact CC-6, both RC-2 hashes, F1/F2 and real F01–F05 | [Gate](../p1/phase-gate.json), [implementation manifest](../p1/implementation-manifest.json), [data gate / commands](../p1/data-gate.json), [final review](../p1/final-review.md) |
| P2 | P2.1–P2.5 **met**; every gate criterion met | 52/52 C++ cases in release and ASan/UBSan, including 37 P2 cases: 16 topics/subscriptions, 16 oracle, 5 driver | [Gate and exact check records](../p2/phase-gate.json), [manifest](../p2/implementation-manifest.json), [review](../p2/review.md) |
| P3 | P3.1–P3.5 **met**; every gate criterion met | 86/86 cases in each preset; CC-2: 10,000,000 release / 2,000,000 sanitizer operations; fresh scan F3 passed | [Gate](../p3/phase-gate.json), [manifest](../p3/implementation-manifest.json), [fuzz verification](../p3/fuzz-gate-verified.json), [review](../p3/review.md) |
| P4 | P4.1–P4.5 **met**; every gate criterion met | 121/121 cases in each preset; indexed k=1 CC-2: 10,000,000 release / 2,000,000 sanitizer operations; fresh indexed F3, memory recount/sizing and pressure fixtures passed | [Gate](../p4/phase-gate.json), [manifest](../p4/implementation-manifest.json), [fuzz verification](../p4/fuzz-gate-verified.json), [review](../p4/review.md) |
| P5 | P5.1–P5.5 **met**; every gate criterion met | Release **157/157** and ASan/UBSan **157/157**; all-mode CC-2, RC-3 and M1/M1-touch/M2 functional checks passed; final integrated F3 and isolated pilot passed | [Release check](release-tests-integration-20261018T155700.707669Z.json), [sanitizer check](sanitizer-tests-integration-20261018T155840.807045Z.json), [gate](phase-gate.json), [manifest](implementation-manifest.json), [review](review.md) |

## Completed task artifacts

| Tasks | Files / symbols and evidence |
|---|---|
| P1.1 acquisition | [`data/manifest.json`](../../data/manifest.json); [range request commands](../p1/range-acquisition-commands.json); approved raw gzip remains local/ignored |
| P1.2 full-stream measurements / RK-01 | [`ItchWalker`](../../src/tiplog/trace/itch_walker.cpp), [`tiplog_walk`](../../tools/tiplog_walk/main.cpp), [`Statistics`](../../py/tiplog_py/itch/characterize.py); [independent gzip/C++ consistency](../p1/cpp-full-day-consistency.json), [converter decision](../p1/rk01-converter-decision.json) |
| P1.3 converter / both hierarchies | [`protocol.py`](../../py/tiplog_py/itch/protocol.py), [`routing.py`](../../py/tiplog_py/itch/routing.py), [`convert` CLI](../../py/tiplog_py/itch/__main__.py), [`TraceWriter` / `TraceReader`](../../py/tiplog_py/trace/format.py); [data gate](../p1/data-gate.json) links full/repeat runs |
| P1.4 golden tests | [`py/tests`](../../py/tests/); final [69-test command](../p1/python-final-metadata-check-20261017T142615.823401Z.json) covers protocol/routing/framing/trace/CLI cases |
| P1.5 independent counts | [`ItchWalker`](../../src/tiplog/trace/itch_walker.cpp) shares no Python framing/length helper; [CC-6 reconciliation](../p1/cc6-reconciliation.json) checks every observed type and locate |
| P1.6 reader / V05 / F1 / F2 | [`trace::Reader`](../../src/tiplog/trace/reader.cpp), [`trace_test.cpp`](../../tests/unit/trace_test.cpp), [`tests/fuzz`](../../tests/fuzz/); [verified timed gates](../p1/fuzz-gate-verified.json) |
| P1.7 L1 characterization | [`results/data`](../data/) aggregate CSV/JSON, [`figures/build.py`](../../py/tiplog_py/figures/build.py), [`results/figures`](../figures/) F01–F05 PNG/PDF; [41 artifact checks](../p1/real-data-artifact-checks.json), [visual review](../p1/figure-visual-review.json) |
| P2.1 registry | [`topics::Registry`](../../src/tiplog/topics/registry.cpp), [`topics_subs_test.cpp`](../../tests/unit/topics_subs_test.cpp); ancestors, segment paths, partitions and u16 local-ID rejection |
| P2.2 subscriptions | [`subs::normalize` / `compile`](../../src/tiplog/subs/compiled.cpp); deduplication, overlap, wide terms, future-topic hooks and lifetime/transaction tests |
| P2.3 independent oracle | [`ref::ScanOracle`](../../tests/ref/scan_oracle.cpp), [`oracle_test.cpp`](../../tests/unit/oracle_test.cpp); raw path matching and separately calculated item retention; only value types shared with production |
| P2.4 deterministic driver | [`driver::drive_trace`](../../src/tiplog/driver/trace_driver.cpp), [`tiplog_sim`](../../tools/tiplog_sim/main.cpp), [`driver_test.cpp`](../../tests/unit/driver_test.cpp); [10,000-record real smoke](../p2/driver-real-smoke-20261018T032735.845004Z.json) |
| P2.5 V06–V09 / V38 | [Phase gate](../p2/phase-gate.json) links final warning-free builds and release/sanitizer suites; production driver does not link the test oracle |
| P3.1 ring | [`ring::Ring`](../../src/tiplog/ring/ring.cpp); DATA/PAD codecs, checked plan/commit, append/eviction, positions and 8-byte sparse checkpoints |
| P3.2 scan replay | [`Engine` / `Replay`](../../src/tiplog/engine/engine.cpp); captured upper, explicit expiry, common progress/checkpoint ordering and borrowed-output lifetime |
| P3.3 invariants | `Ring::check_invariants`, `Engine::check_invariants`; capacity retention and separately counted pressure, checked arithmetic and unchanged rejected state |
| P3.4 V10–V14 / v1.1 cases | [`ring_test.cpp`](../../tests/unit/ring_test.cpp), [`engine_test.cpp`](../../tests/unit/engine_test.cpp), [`campaign.cpp`](../../tests/differential/campaign.cpp); [gate](../p3/phase-gate.json) links full CC-2 commands |
| P3.5 scan F3 | [`fuzz_engine_ops.cpp`](../../tests/fuzz/targets/fuzz_engine_ops.cpp), [`run_fuzz_gate.py`](../../scripts/run_fuzz_gate.py); [verified fresh gate](../p3/fuzz-gate-verified.json) |
| P4.1 pool | [`index::Index` / `BlockMeta`](../../src/tiplog/index/index.hpp), [`index.cpp`](../../src/tiplog/index/index.cpp); fixed 32-byte metadata, u32 deltas, free list and generations |
| P4.2 expiry / pressure | `Index::prepare_append`, `commit`, `reclaim`, `sweep_open`; `Engine::publish`; ordered sealed expiry, wide-before-narrow deltas, cold-open expiry, explicit ForceEvict/RejectPublish and generic16/enforced32 sizing |
| P4.3 cursors / k=1 replay | `Index::seek`, `validate_cursor`, `advance`; `Replay::next_batch_into`; guard unread retention before index access and reacquire filters after registry growth |
| P4.4 accounting | `Index::{memory,stats,recount,check_invariants}`; exact live/stale/open/sealed/free slot identity and requested/reserved capacities; separate [`tiplog_index_memory`](../../tools/tiplog_index_memory.cpp) observation |
| P4.5 V15–V20 / V37 / F3 | [`index_test.cpp`](../../tests/unit/index_test.cpp), [`engine_index_test.cpp`](../../tests/unit/engine_index_test.cpp); [gate](../p4/phase-gate.json) links all acceptance commands, sizing, allocator observations, real-driver comparison and data-exclusion audit |

P5 artifacts currently include [`merge::StdPQ/BinHeap/Quad/Loser`](../../src/tiplog/merge/kernels.hpp),
[`merge_test.cpp`](../../tests/unit/merge_test.cpp), [`engine_merge_test.cpp`](../../tests/unit/engine_merge_test.cpp),
[`Tail`](../../src/tiplog/engine/engine.cpp), [`oracle_tail_test.cpp`](../../tests/unit/oracle_tail_test.cpp),
[`merge_bench`](../../bench/micro/merge_bench.cpp), [`publish_bench`](../../bench/micro/publish_bench.cpp),
the [empirical payload mix](../../configs/m2_payload_mix.csv), and
[`run_p5_pilot.py`](../../scripts/run_p5_pilot.py) / [`check_p5_pilot.py`](../../scripts/check_p5_pilot.py).
Their executed acceptance is recorded in [the final gate](phase-gate.json); the
[pilot audit](pilot-audit.json) checks the actual raw measurements.

## Measured P1 data and accepted fuzz gates

The approved compressed source is **3,524,013,057 bytes**, SHA-256
`ef03df46a27e6bda4dead017f84c2e3979df7211f02c7868b51d53fceb99c689`.
Complete decompression counted **8,251,407,909 bytes**, **268,744,780 messages**
and **7,713,918,349 payload bytes**: 18 observed types, 8,907 locates and zero
timestamp inversions. Python/C++ type and locate counts reconcile exactly.
The intact gzip has **no BinaryFILE terminator**; `incomplete=true` remains
explicit. Complete framing is not a claim of session completeness.

Full-day routing produced **111,997 topics / 8,907 partitions / 8,906 symbols**,
with zero unknown locates, symbol mismatches or directory conflicts. Symbol
message Gini is **0.77837**, and the top 1% carries **21.7987%** of messages.
Trees have 4–21 nodes; saved class histograms are descriptive, not P7 exactness
coverage. The selected 09:30-inclusive–10:00-exclusive window contains
**32,817,244 records / 947,677,397 payload bytes / 62,964 topics**.

Both full-source repeat conversions satisfy RC-2:

| Trace | Bytes | Repeated SHA-256 |
|---|---:|---|
| H-spec | 1,616,858,987 | `6062bdb96ec8354ecf650cdfb979574530b2120aa06047fa48d14a78e5936f70` |
| H-flat | 1,616,161,552 | `89cc31ac0c8907cf9552e85a60f04a221f4f2f9bc012769d0ab4de96376cbba2` |

The isolated first-2-GiB combined converter/characterizer pilot took **294.553 s**;
the measured-size projection was **1,131.778 s**, below the 2,700 s switch
threshold, so RK-01 retained Python. Full conversion took **867.479 s** internally.
These are scoped conversion diagnostics, not message-bus benchmark results.

| Accepted timed gate | Confirmed monotonic seconds | Executions | Verified evidence |
|---|---:|---:|---|
| P1 F1 trace | 1,801.8978 | 53,139,553 | [F1/F2 verification](../p1/fuzz-gate-verified.json) |
| P1 F2 framing, real prefix plus synthetic inputs | 1,801.7637 | 2,043,899 | [F1/F2 verification](../p1/fuzz-gate-verified.json) |
| P3 F3 scan | 1,801.2918 | 216,843 | [Verification](../p3/fuzz-gate-verified.json) |
| P4 F3 indexed | 1,801.3472 | 81,399 | [Verification](../p4/fuzz-gate-verified.json) |
| P5 F3 integrated | 1,805.0595 | 104,457 | [Terminal verification](fuzz-gate-verified.json), [independent review](F3-independent-review.json) |

Each accepted gate has 15 successful segments and verified final statistics,
log/binary/runner/corpus identities and no unresolved sanitizer/crash report.
Earlier wall-clock-discontinuous or interrupted attempts are retained and
excluded from accepted duration. [Protocol and original-source details](../p1/fuzz-segmented-notes.md).

## Findings that affected implementation and reading boundaries

Each ledger below records source/finding → invariant/decision → task → code
symbol → validation → executed evidence. Historical pending handoff wording
must be read alongside the authoritative later gate linked above.

| Source / actual reading boundary | Applied decision and validation | Traceability ledger |
|---|---|---|
| S05 Nasdaq ITCH 5.0: Overview/Architecture/Data Types, all 23 message tables §§1.1–1.8, latest revision entry 2023-04-28, relevant symbol convention; S06 BinaryFILE: complete two pages; S54 RFC1952 §§2.2–2.3.1 | Exact lengths/fields, symbol/locate routing, distinct transport/project framing, complete stream count and propagated gzip failures; V01–V05, CC-6, RC-2 | [Python](../p1/python-sources.md), [independent C++](../p1/cpp-sources.md), [final traceability](../p1/traceability.md) |
| S01 Jane Street article's filtering/block-pool sections; S03 transcript 00:41:26–00:42:43 | Published hierarchy/order/two-segment partition and block-pool motivation; independent topic normalization/hooks/filter implementation; V06–V09/V38 | [Topics](../p2/topics-sources.md), [oracle/driver](../p2/oracle-driver-sources.md), [index](../p4/index-sources.md) |
| S11 Aeron wiki: terminology, headers/alignment, padding and SHM-writing sections, displayed edit 2025-03-12; S13 short Kafka log note, moving trunk documentation | Logical positions and in-band PAD motivate independent single-thread ring; explicit expiry; no imported concurrent guarantee or copied layout; V10–V14/V36 | [Primary review](../p1/review-sources.md), [ring](../p3/ring-sources.md), [scan replay](../p3/engine-sources.md) |
| Approved v1.1 analytical corrections; S61 event/history distinction retained from saved reading | Common max0/full-budget/exhausted-upper/error ordering; preserve distinct equal-valued events; late seals use expiry min-heap; checked limits and transactional rejection; V35–V38 | [P3 replay](../p3/engine-sources.md), [P4 integration](../p4/engine-sources.md), [P5 integration](engine-sources.md), [integrated fuzz](fuzz-sources.md) |
| S18 Sanders: §2 loser-tree paragraph, Appendix A.2 and complete A.5; S23 complete short original messages; S49 prior original follow-up, no newly available ACM full text | Four independent kernels, fair inlined early-exit heap baseline, sentinel/bounds and adversarial cases; V21/V35/V38; actual generated-code inspection qualifies machine-code claims | [Merge ledger](merge-sources.md), [revision identities](merge-source-identities.json), [assembly evidence](assembly-review.json) |
| S42 Google Benchmark v1.9.5, commit `192ef10025eb2c4cdd392bc502f0c852196baa48`: targeted original guide/API/timing/shuffle sections and complete random-interleaving note | Exclude setup, protect every output, preserve individual repetitions and actual invocation order; library entropy seed is not exposed; P5 functional harness checks and accepted isolated pilot | [Pinned reading record](../p4/p5-method-reading.json), [merge](merge-sources.md), [publisher](publisher-sources.md), [pilot protocol](pilot-method.md) |
| Installed GCC 15.2.0 libstdc++ sections with file hashes; glibc2.43 malloc header and official manual page | Check actual reserve/heap behavior and scope allocator observations; do not call requested capacities RSS; V17/V19 and separate P4 diagnostic | [Registry](../p2/topics-sources.md), [index](../p4/index-sources.md), [allocator](../p4/memory-sources.md) |

The [dated research refresh and its limitations](../../docs/plan/RESEARCH.md),
[review](../../docs/plan/REVIEW_2026-10-17.md) and
[findings inventory](../../docs/plan/FINDINGS_TO_IMPLEMENTATION.md) remain the
approved context. Knuth, LaMarca–Ladner full text, abstract-only papers and
inaccessible ACM text are not silently promoted to fully inspected sources.
S22's PR/API fetch was unavailable during P5; no new PR-code claim is made.
Original source-code references carry installed-version/file hashes or immutable
dependency revisions in their ledgers. Custom algorithms/parsers are original
project code; no Aria implementation or copied external algorithm source is
claimed. Published Jane Street statements, our inferences, independent designs
and performance hypotheses remain distinct.

## P5 executed acceptance checks

| Check | Status and actual evidence |
|---|---|
| Release / sanitizer unit integration | **Passed: 157/157 each**; [release](release-tests-integration-20261018T155700.707669Z.json), [ASan/UBSan](sanitizer-tests-integration-20261018T155840.807045Z.json) |
| RC-3 repeated GCC/Clang functional reproduction | **Passed:** 180 child runs and 170 equality checks, actual GCC15.2.0 / Clang21.1.8, 144 real-trace success/expiry checks plus 36 independent synthetic runs; [summary](rc3-summary.json), [integrity audit](rc3-integrity.json), [scope and results](rc3-evidence.md) |
| M1 / M1-touch full-size pilot-profile functional verification | **Passed, untimed:** [`--profile=pilot --verify-only --quad-padding-both`](M1-full-pilot-functional-20261018T160201.375404Z.json); all kernels/padding variants match independent expected hashes, including N=2^22 and fully initialized 1-GiB touch array; this is no timing result |
| M2 matrix functional verification | **Passed, reduced capacity:** [60 profiles](M2-full-matrix-functional-20261018T160504.287611Z.json), 65,536 publications/profile, index-off/on equality and invariants; timed matrix uses different declared 1-GiB capacity and is not established by this check |
| Generated-code review | **Passed as inspection:** [actual release binary/compiler/flags/symbol evidence](assembly-review.json); no kernel winner, branch-free or cache-speedup conclusion follows |
| Pilot runner / digest checker | **Passed as synthetic guard/algebra checks:** [runner validation](pilot-runner-validation.json), [747-case digest self-test](pilot-digest-self-test.json); these contain no benchmark measurements |
| Full CC-2 nine configurations per preset | **Passed and independently reviewed:** [all-configuration record](CC2-all-configurations.json), 90,000,000 release / 18,000,000 sanitizer operations, identical canonical outputs and outcomes across Scan plus Indexed/Auto × four kernels; [review](review.md). No CC-2 timing is a benchmark |
| Integrated F3 ≥1,800 confirmed monotonic seconds plus final identity/statistics review | **Passed:1,805.0595 confirmed seconds /104,457 executions:** [atomic gate](F3-integrated-segmented-gate-20261018T160110.829382Z.json), [source freeze](fuzz-source-freeze.json), [named corpus](named-corpus.json) |
| Isolated M1/M1-touch/M2 timed pilot and reduced simulated Cachegrind | **Passed:** [pilot results](pilot-results.md), [3821-check audit](pilot-audit.json), [independent review](pilot-independent-review.json), [simulated diagnostic](cachegrind-summary.json). Three isolated blocks,285 measured rows/19cases×15reps,369 invocations, zero non-ok rows, ≥60s settling/block and no concurrent project workloads |
| Final P5 criteria, PROGRESS and stop boundary | **Met:** [all criteria](phase-gate.json), [current implementation manifest](implementation-manifest.json), [final PROGRESS](../../docs/plan/PROGRESS.md). Stopped before P6 |

## Limitations and continuation

- Source-session completeness remains unproved because the BinaryFILE terminator
  is absent. Data/sample scope is one approved Nasdaq day and one selected window.
- Raw input, message traces, real fuzz seeds and payload-derived F2 logs remain
  local/ignored. [P1 privacy audit](../p1/privacy-audit.json) and
  [P4 Git exclusion audit](../p4/git-data-audit.json) state their checked scope;
  publication/distribution terms are not resolved by these checks.
- The core is a single-thread bounded retained log. Durability, concurrent
  readers, network service, tagged indexes and other roadmap features are absent.
- Portable memory capacities are exact within their named boundary. The separate
  glibc allocator observation includes rounding/reuse effects and proves neither
  universal per-object overhead nor RSS.
- Hardware counters remain unavailable under the nonprivileged fallback. The reduced
  Cachegrind output is labeled whole-program simulated counts. Selected pilot
  medians provide no generalized speedup, throughput-to-latency or calibrated-Auto claim.
- Early commands honestly retain source manifests/unborn HEAD status. The later
  [local snapshot](../p4/source-revision.json) is not retroactive provenance;
  RC-3 records its actual commit and dirty flag. The pilot captured its own
  actual revision, build/input hashes and fresh environment.
- P5 is complete and execution has stopped. **P6 is the next sequential phase
  available for separate explicit authorization**; it has not begun.
- All128 of744 frequency endpoints flagged by the10% rule were retained.
  AC/CPU endpoint and visible-process observations prove neither a fixed hot-loop
  frequency nor exclusive host access. Fresh per-process ASLR disable succeeded
  without a system setting change. Full P6 noise studies and confidence intervals
  remain unrun.


## P5 task completion and source-to-evidence continuation

| Task | Code / accepted evidence | Completion |
|---|---|---|
| P5.1 k-cursor set / packed limits | `Replay::next_batch_into`, `merge::pack`; V21/V23/V38 unit+all-mode CC2+F3 | Met |
| P5.2 StdPQ / BinHeap | `merge::StdPQ`, `BinHeap`; independent std::merge tests, real pop/push baseline and generated-code record | Met |
| P5.2b Loser / Quad | `merge::Loser`, `Quad`; padding/move/exhaustion/adversarial tests and all-kernel equivalence | Met |
| P5.3 Indexed / Auto / Tail | `Engine`, `Replay`, `Tail`; independent raw-path/Tail references, V35 progress/expiry/rearm, RC3 and fresh integrated F3 | Met |
| P5.4 V21/V23–V26/V35/V38 |157/157 each preset;90M+18M CC2;180 RC3 children;1805.0595s integrated F3 | Met |
| P5.5 M1 / M1-touch / M2 | Full matrices exposed,15 full-size M1 checks,60 M2 functional profiles,285 isolated pilot rows,3821-check audit and simulated fallback | Met |

The [sixteen-item P5 criterion record](phase-gate.json) marks every requirement
met and identifies exact commands/artifacts. V22/galloping is Tier C and remains
excluded. Current source snapshot `aa13c1824ba5a7a3593a0f63c6f455cac851e822`
matches all94 implementation/build/configuration/test files; runtime dirty state
is retained honestly. No publication or managed-metadata modification occurred.

[Final artifact/provenance audit](final-artifact-checks.json) passed: all five phase gates, all16 P5 criteria,94 source files,38 binaries,11 accepted evidence identities,285 per-repetition build/run records and preserved master/managed metadata. [Document checks](document-checks.json) passed. No required P1–P5 work remains.
