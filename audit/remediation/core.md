# Core audit remediation

All assigned core fixes are implemented. This work covers AUD-001, AUD-002,
AUD-003, AUD-004, AUD-008, AUD-012, AUD-020 and AUD-021. F-01, work-budgeted
replay/tail polling, is deferred as requested; replay/poll output budgets and
completion semantics have not changed.

## Changes and decisions

| Finding | Implementation | Regression coverage |
| --- | --- | --- |
| AUD-001 | Shared `tiplog::max_topic_path_bytes = 4096` and `tiplog::max_topic_depth = 128` in `types.hpp`. Registry validation checks bounds before ancestor allocations, observer preparation or mutation, throwing `topics::RepresentationLimit`. Subscription normalization validates every term before interning any term. Empty subtree-root sets now skip prefix hashing. Trace/Python enforcement is coordinated with the other remediation changes. | Accept exact byte/depth limits; reject depth 129 and byte 4097; reject an excessive later subscription term without registering earlier valid terms; verify topics, partitions, observers and compiled matching after rejection. Existing randomized segment-matcher and 100,000-term tests still pass. |
| AUD-002 | `Registry::intern` uses hash sets to deduplicate observer pointers and previously visited ancestor IDs. Each hooked ancestor's slot list is visited once; each observer prepares one update even if registered on several roots. Update order follows the original deterministic encounter order. All allocations remain before topic commit. | 8,000 distinct observers, each registered on two overlapping roots, each receives exactly one preparation/commit containing all three pending topics. Existing observer-allocation rollback test still passes. |
| AUD-003 | Adopted all four audit checker negative controls into `tests/unit/checker_test.cpp`, registered in normal project CTest via `p3_engine.cmake`. Ring fill/sequence, Index block count and Engine partition-cover corruptions must throw. | All four controls pass. Separately replacing each of Ring/Index/Engine `check_invariants` with an empty body kills all three mutations; each mutated checker executable exits 1. |
| AUD-004 | Differential payloads now mix random nonuniform bytes with deliberate repeated-byte events. Resume selection includes the retained interval while retaining expired/future/empty cases. Most batch selections prefer an available live reader, with arbitrary/stale-handle sampling retained. Successful nonuniform publications are counted; the CLI reports `nonuniform_payload_publications`. | New deterministic coverage test runs all 12 mode/kernel combinations and requires useful execution/delivery, nonuniform payloads, multicursor Indexed reads, expired opens, fell-behind batches and rejected empty specs. All output bytes remain compared with the independent oracle. |
| AUD-008 | Retained `Ring::at` as O(1) access with an explicit proven-boundary precondition. Alignment/range validity alone does not establish that precondition, in any build. Added public `Ring::at_checked` for arbitrary locators: it proves boundary membership by walking from the retained tail before decoding. Both contracts and complexity are documented in `ring.hpp`. This is the approved safe-API resolution rather than introducing a full retained-log scan into every engine read. | A payload containing a plausible forged header at an aligned interior offset is rejected by `at_checked`. Exact DATA/PAD boundaries after wrapping are accepted; head, expired and unaligned positions are rejected. |
| AUD-012 | Fixed pressure fixtures run once per fuzzer process, including all four kernels in integrated mode. Subscriptions compile lazily when used. Retention/oracle/output comparisons remain per operation; expensive full invariant recounts run every 32 operations and at final state. Fuzz payload bytes vary within a record while preserving the existing byte-stream operation framing. | Fresh ASan/UBSan target; identical-input before/after measurement and a separate 10,000-execution integrated mutation smoke, with no crash/UB. Pressure fixtures still run on every new integrated/indexed fuzzer process. |
| AUD-020 | `Index::estimate_count` clamps the lower bound to the index's retained tail, uses metadata for wholly covered blocks, and binary-searches encoded deltas at partial range boundaries. The result is exact for retained postings in the half-open range; Auto's existing fraction policy is unchanged. | Exhaustive lower/upper boundary comparisons against independently retained history across full, partial, expired and delta-sealed blocks, including a single shared boundary block and reversed/empty ranges. The 1,023-old-A / 4,000-B / one-new-A reproduction now selects Indexed in Auto, returns the same result/checkpoint as Scan, and fetches one record versus Scan's 4,001. |
| AUD-021 | A Registry mutation guard spans the entire `intern` prepare/commit transaction. Nested `intern` and `observe` throw `logic_error` before changing state. Callback reads and handle reset remain permitted; the observer contract documents this. RAII resets the guard on rollback. | A prepare callback catches or propagates nested mutation rejection; both branches verify path↔ID round trips, unique topic/local IDs, partition counts and compiled subscription matches. A commit callback reads committed state, rejects nested intern/observe, unregisters itself safely, and subsequent interning succeeds. |

## Validation

Fresh focused Release and ASan/UBSan CTest runs each passed **83/83 tests**,
including the full topic/subscription, ring, index, indexed-engine and checker
targets, plus the new differential coverage target. Logs:
[Release](core/release-tests.log), [ASan/UBSan](core/sanitized-tests.log).
The sanitizer run also has libFuzzer coverage instrumentation; AddressSanitizer
and UndefinedBehaviorSanitizer remain active. Leak detection was disabled because
this execution environment's ptrace restrictions cause LeakSanitizer to fail even
on CMake's independent feature probes. This is not a claim of a leak-free run.

The checker controls killed the three vacuous-checker mutations. See the
[summary](core/mutation-summary.json) and the individual
[Ring](core/mutation-ring.log), [Index](core/mutation-index.log) and
[Engine](core/mutation-engine.log) failure logs. Mutants were compiled from
temporary source copies and linked into the checker executable; production
sources were never replaced.

A separate differential sample ran **10 seeds × 10,000 operations in each of
12 mode/kernel combinations = 1,200,000 operations**. It produced 79,308 execution
batches out of 235,716 batches (**33.6%**), 177,144 delivered records
(**0.148 per operation**) and 497,100 successful nonuniform-payload publications.
All 12 result digests agree. The audit's historical generator measurements were
4.0% execution batches and 0.023 delivered records per operation. This is new
generator evidence, not a replacement for the historical CC-2 evidence or its
digests. See [the sample results](core/campaign-summary.json).

Local performance observations, deliberately excluded from pass/fail tests:

| Probe | Baseline | Current | Evidence |
| --- | --- | --- | --- |
| New-topic notification, 2,000 live subscriptions | 0.880 ms/intern | 0.345 ms/intern | [baseline](core/fanout-baseline.jsonl), [current](core/fanout-current.jsonl), [probe](core/fanout.cpp) |
| New-topic notification, 8,000 live subscriptions | 10.643 ms/intern | 1.463 ms/intern | Same probe; the 4×-fanout ratio falls from 12.1× to 4.24×. |
| Full-block posting count, one million calls | 8.64 ns/call | 7.96 ns/call | [baseline](core/estimate-baseline.jsonl), [current](core/estimate-current.jsonl), [probe](core/estimate.cpp) |
| Partial boundary count, one million calls | 8.44 ns/call, incorrectly estimates 1,024 | 27.35 ns/call, correctly counts 1 | Same probe; this extra planning cost avoids the demonstrated 4,001-record scan. |
| Fuzzer harness, identical 2,615-byte publishing/replay input, 250 repetitions | 14.75 executions/s | 121.61 executions/s | [summary](core/fixed-throughput.json), [baseline log](core/baseline-fixed.log), [current log](core/current-fixed.log), [input](core/publication_replay.ops). The baseline is the preexisting untouched `build/fuzz/fuzz_engine_ops`; current was freshly built with matching sanitizer/optimization settings. |

The fixed-input fuzzer observation is a harness-cost comparison, not mutation
fuzzing. A separate **10,000-run integrated mutation smoke passed**, recording
1,666 executions/s on this local sample; see [the log](core/current-smoke.log).
These short measurements do not replace the project's longer historical gates.

The final integrated full build/test matrix is recorded separately by the main
remediation pass. Historical results/gates and the original audit evidence have
not been overwritten. Resource limits intentionally reject previously accepted
paths over 4,096 bytes or 128 segments. `Ring::at_checked` intentionally costs
O(retained items); callers with proven boundaries retain O(1) `Ring::at` access.

## Final independent functional gate

The final binaries passed the complete remediation-only differential gate:

| Build | Supported mode/kernel pairs | Seeds per pair | Operations per seed | Total operations | Shared digest within cohort |
| --- | --- | --- | --- | --- | --- |
| Release | 9 | 1,000 | 10,000 | 90,000,000 | 13453666401178898262 |
| ASan/UBSan/LSan | 9 | 200 | 10,000 | 18,000,000 | 13990326321313093666 |

The nine pairs are Scan/StdPQ, Indexed with each of the four merge kernels, and
Auto with each of the four merge kernels. Digests agree across all modes/kernels
within each cohort; the cohorts have different seed counts and therefore their
final cumulative digests are not compared with each other.

The final `fuzz_trace_reader`, `fuzz_itch_walker` and `fuzz_engine_ops` binaries
also each passed 10,000 mutation executions using copied original seed corpora.
Integrated engine fuzzing used `TIPLOG_FUZZ_MODE=all`. AddressSanitizer leak checks
and UndefinedBehaviorSanitizer halt/stack traces were enabled for these final
runs outside the sandbox, avoiding the sandbox's LeakSanitizer/ptrace limitation.
All three artifact directories remained empty.

The reusable runner limits tested subprocesses to two and writes only under
`audit/remediation/core/final-validation`; it does not alter original corpora or
historical results. This is a functional gate, with no quiet-host performance
claim. Exact arguments, exit status, results, source hashes and before/after
binary hashes are in [the final summary](core/final-validation/summary.json)
and its individual job records. The selected source snapshot was unchanged
throughout the run and every tested binary's before/after hash agrees.
The runner itself is [run_final_validation.py](core/run_final_validation.py).

Independent review also exposed two Python remediation defects: a valid-JSON
journal tail with a corrupted row identity was silently accepted, and an output
could replace a directory symlink that was an ancestor of the source path.
Both were corrected by the Python remediation pass and independently reproduced
again: each now rejects before changing the source/evidence. See
[the closure record](core/review-confirmation.json). The runtime engine source
and header remain byte-identical to the original remediation baseline, confirming
that the deferred F-01 replay/tail feature was not introduced; see
[the scope record](core/scope-confirmation.json).
