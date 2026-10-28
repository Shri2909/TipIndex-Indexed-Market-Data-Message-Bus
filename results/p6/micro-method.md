# P6 microbenchmark execution contract — 2026-10-23

This is a method/source ledger, not a completed campaign or timing result.
Actual sessions and their terminal audits must be linked after execution.

The inspected pinned Google Benchmark1.9.5 material/revision and source-reading
boundaries are recorded in the P5 method ledger and
[P6 ST-12 review](method-review.md). No external implementation is copied here.
The harnesses and auditors are independent project implementations. Published
article statements do not establish a kernel winner or an Aria implementation.

| Source/finding | Decision/invariant/task | Code | Validation and executed status |
|---|---|---|---|
| VALIDATION §§5–7: complete Tier B matrix, identical inputs and sinks | M1/M1-touch:10 k values ×9 owner patterns ×5 arms, including both required Quad padding layouts =900 cases. M2:5 payloads ×3 P ×2 distributions ×2 B ×2 index arms =120 cases. M3:4 B ×2 operations =8 cases. | `scripts/run_p6_micro.py:plan`, `expected_names`; existing `merge_bench`, `publish_bench`, new `index_bench` | Actual `--benchmark_list_tests=true` matched all900/120 cases and the one pilot case exactly; `micro-declared-matrix-20261023T143317.235527Z.json`. M3 full-window functional check passed in35.19s, `M3-full-functional-20261023T143340.431190Z.json`; this duration is diagnostic, not a microbenchmark observation. |
| Benchmark repetitions/interleaving do not establish paired process rounds | At least15 measured repetitions, random interleaving,0.2s warm-up,0.5s minimum; pilot30. Preserve adaptive invocations/calibration/warm-up separately. Micro ratios use an explicitly independent interleaved design. | `run_p6_micro:main`; `exp.normalize.normalize_gbench`; pinned P5 block helper | Plan audit passed, `micro-plan-audit-20261023T143211.877342Z.json`. Actual campaigns pending. |
| CC-4: output checks must remain independent of the optimized path | Every M1 invocation must match its independently sorted union and full2²² count; M1-touch fully initializes1GiB. M2 checks every adaptive sequence prefix with a closed-form reference, exact count and no pressure evictions. M3 checks its independent chronological/per-partition arrays and `lower_bound` queries. | `run_p6_micro:verify_block`; `check_p5_pilot.sequence_digest`; C++ harness independent references | Auditor accepted untouched historical P5 M2 observations and detected an intentionally corrupted digest in temporary storage; `micro-invocation-auditor-regression-20261023T143408.847649Z.json`. Historical observations are not relabeled P6 results. C++ M3 fixture audit passed193 checks/build, see `cpp-final-check.json`. |
| Noise flags cannot be selected after inspecting a preferred result | Require fresh AC, CPU2/P-core/affinity,60s monotonic settling per block and quiescence. Preserve every endpoint and flag >10% from session median. Mapping a repetition to an adaptive invocation is unexposed; analysis conservatively flags the complete matched block/attempt. Missing observations remain unknown. | P5 block helpers; `run_p6_micro:frequency_flags`; `analysis.summarize:hydrate_noise` | Sidecar exact-join and unknown-frequency regressions passed; actual campaign flags pending. No exclusive-host or constant-clock claim. |
| Interrupted and failed runs are evidence | Immutable raw attempt directories, append/fsync rows, exact source/binary freeze, resumable completed blocks; explicit process-failure record if GBench output is absent. Failed commands/audits cannot contribute timings. | `run_p6_micro:append_observations`, `main`; `analysis.summarize:report_status` | Plan/auditor checks passed; real campaign interruption recovery remains unexercised. No failure is silently converted to a successful observation. |

All actual rows record the real compile command, Git SHA/dirty state, input,
source and binary identities, fresh environment reference, CLI flags, seed,
requested profile, repetition and raw command/output references. Hardware
counters remain unavailable unless a fresh successful probe establishes access;
missing counters are null. The previously saved reduced Cachegrind diagnostic
is simulated and has its own historical build/process boundary.

No full P6 measurement, CV response, calibration, figure or P6 acceptance gate is
represented as passed by these implementation/functional checks.
