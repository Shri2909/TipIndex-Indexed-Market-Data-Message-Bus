# P6 Python experiment/oracle source-to-evidence ledger

This is original project implementation. It does not reconstruct unpublished Aria
internals, copy merge/reference code, or add dependencies. The project design and
validation documents are requirements; external articles remain reference data.
Required ST-12 primary-source inspection and the pinned Google Benchmark method
are recorded in `method-review.md` and the earlier P5 method ledger.

| Finding or source inspected | Design/task | File/symbol | Check | Execution status |
|---|---|---|---|---|
| ARCHITECTURE §5.0 trace-v1 header/records/dictionary; P1 accepted trace identity | Independently parse headers, raw paths, timestamps, bounds and padding; no Engine/C++ oracle helpers | `py/tiplog_py/exp/oracle.py:TraceIndex`, `dictionary` | `test_trace_oracle_success_zero_match_expiry_future`; V27 all real T configurations | Small fixture passed; real-matrix V27 pending execution |
| ARCHITECTURE §3.6 and v1.1 replay progress; §5.3 whole-record/PAD capacity | Compute exclusive head and retained first DATA from independent prefix sums plus explicit PAD insertions; compare exact outcome, error and checkpoint, including empty/future ranges | `oracle.py:retained_layout`, `OutcomeOracle.expected`, `validate` | 120 randomized capacity/list cases against a separately coded scalar item queue; exact successful/zero-output/expired/future fixture | Passed locally; instrumented full campaigns handled by root |
| VALIDATION §1 CC-4 and §3 V27 | SHA-256 of little-endian u64 sequence list and raw concatenated payloads; same FNV1a(seqLE+payload) running timing sink; never validate output alone | `oracle.py:digest_selection`, `validate`; `run.py:normalize_actual` | Scalar-vs-C bytes over random payloads, high-bit sequences, empty payloads, chunk sizes 1/7/150; independent Python SHA | Passed locally. No digest is copied from production output |
| Bounded resource requirement for 32,817,244 records | Compact NumPy disk-backed index and mmap; expected results cached per subscription/range; synthetic schedules one at a time | `TraceIndex`; `run.py:prepare` | Exact trace/index hashes validated on cache reuse; cache ignored under `build/` | Small cache reuse passed; actual full preparation pending |
| Routine optimization authorized by root: byte loops must not turn whole-window oracle checks into Python-byte bottleneck | Standalone C byte-copy/FNV primitives only. Python owns parsing, matching, selection, retention and outcomes. No project headers or production symbols linked | `hash_bytes.c`, `hashes.py:build_accelerator`, `ByteAccelerator` | Scalar reference crossvectors and independent SHA after packed-byte concatenation; bounds rejection | Passed. Build captures actual cc path/version/argv/source SHA/binary SHA in ignored build directory |
| VALIDATION §5.3 process-level repetitions and §7 identical states | Batch immutable-state requests with seeded shuffled order, while each workload/round is a new process; one separately saved warm-up, >=10 measured process repetitions; shared paired round key | `matrix.py:arms_for`, `write_requests`; `run.py:execute` | Process/PID distinctness gate, saved warm-up checks; actual argv/request hashes/child PID/round seed in raw command records | Unit guard passed; actual evaluation pending |
| VALIDATION §5.1 AC/CPU2/frequency/noise | Require saved quiescence declaration and visible-process scan; CPU2 children and observer outside2/3; AC monitoring; >=60s between workload blocks; retain noise flags | `run.py:execute`, `perform_process`; `audit.py:frequency_flags` | 10% median-frequency fixture; fresh environment capture per session; per-request sched_getcpu/frequency from C++ | Unit flags passed; actual AC/noise/affinity evidence pending |
| P5 inspected pinned Benchmark1.9.5 method: random interleaving is not a shared process-round proof | Micro repetitions explicitly independent-interleaved; no invented paired rounds from repetition_index; preserve every individual/error and skip aggregates | `normalize.py:normalize_gbench` | GBench M1/M2/M3 unit/denominator/error vectors | Passed. Full campaigns run separately by root |
| VALIDATION T1/T2/T3/T5 complete Tier B grids | C1GiB all backlogs plus C2GiB longest; 14 subscriptions; W2 seeded weighted readers; all27 synthetic P/Zipf/L combinations; k=1/sqrt(P)/P and local selectivity .01/.1/1; all4 kernels, Scan and Auto; both cache treatments; B64/256/1024/4096 at3 anchors | `configs/P6/matrix.toml`; `matrix.py:make_plan`, `consumer`, `w2_readers` | Mandatory grid/default/W2 reproducibility tests; generated case/expected manifest hashes | Defaults and sampler passed; full matrix preparation pending |
| Actual same-partition run mean must equal requested geometric L, while preserving Zipf marginal | Independent SplitMix64 integer generator; force different owner at switch using uniform skip or stationary no-self circle coupling (new documented project method), raw CDF arithmetic matched across implementations | `synthetic.py:SplitMix64`, `schedule`, `schedule_summary`; independent C++ generator in `tiplog_bench` | Fixed SplitMix vectors, deterministic schedule/payload vectors; full owner-count SHA, event counts and run counts checked against C++ before accepting timings | Python vectors passed; C++ crosscheck pending. No external algorithm or novelty claim |
| Auto thresholds were uncalibrated in P5 | Train seed20191230/P10,1000/Zipf0,.8/L1,16; evaluate distinct seed20191231 full27 grid. Freeze a finite K/rho grid by training-only summed median BinHeap/Scan CPU; deterministic ties; compare exact integer estimate/range with long-double threshold multiplication | `auto.py:calibrate`, `configs/P6/matrix.toml` | Held-out sentinel ignored; deterministic candidate/tie fixture; frozen artifact required before evaluation | Passed small fixture; actual calibration pending |
| T2 must include writer index cost without charging1800 seconds of publication to10 seconds of replay | Matched actual trace/window index-on/off publishers, seeded process order per round; keep signed observed delta. CPU per market second = group replayCPU/10 + publisherDeltaCPU/1800 when indexed | `run.py:execute`, `aggregate_t2`; analysis module owned separately | Explicit full/window durations, raw prefill count/sink checks, complete-R reader index coverage, independent signed-amortization analysis tests | Group completeness/sums passed; actual publisher measurements pending |
| V27 failures invalidate measurements, and non-ok rows cannot disappear | Preserve raw_status and explicit oracle_mismatch reporting status; keep errors/crashes/invalid_config; packed k>65535 invalid rows validated as explicit representation rejections | `normalize_actual`, `oracle.py:validate`, `audit.py:acceptance` | Forced mismatch, missing invalid reason, missing reader and duplicate PID tests | Passed locally; actual campaign accounting pending |
| VALIDATION T5 full accounting and separate allocator boundary | Attach exact memory/recount plus actual schedule Index-only glibc allocator observation; no invented universal allocator header cost | `run.py:execute`; C++ `--memory --allocator-replay` | Require recount_equal and stats_equal, preserve signed overhead/scope and raw link | Source integration done, actual measurements pending |

Local validation: `PYTHONPATH=py .venv/bin/python -m pytest -q
py/tests/test_exp_oracle.py py/tests/test_exp_protocol.py`: **12 passed in0.24s**.
An earlier fixture expected oldest-retained seq3 for sizes24,16,24,24/C64;
the independent whole-item calculation correctly retained seq2 at position24.
The fixture expectation was corrected; the source algorithm did not change for
that failure. Actual root-run command/log records supersede this local summary.

No required full experiment, CV response, Auto calibration, acceptance gate or
figure is represented as passed by these unit checks.

## Integration refresh — 2026-10-23

The reduced independent C++/Python comparisons now cover 36 combinations of
P={10,1000}, Zipf={0,.8,1.2}, L={1,16,256}, C={2048,262144}, with 2,048
records each. Every combination checks all four kernels, Scan and Auto, wide
fallbacks, exact/subtree/zero-match subscriptions, wrapped retention, expired
history, a retained suffix and a future checkpoint. Each invokes 108 requests,
for **3,888 independently validated replay outcomes**, plus independently
computed full-input publisher sinks, owner-count SHA, run/event counts and
physical/sequence retention bounds. These are functional checks, not experiment
measurements. Actual saved command/evidence:

`exp-cpp-reduced-functional-20261023T143154.930380Z.json`: passed, 36 cases.

The separately required P=100,000 packed-limit check exposed an existing
subscription compiler scaling problem: O(terms²) normalization and
O(topics·terms) matching exceeded its unchanged 180-second functional timeout.
`exp-cpp-packed-functional-20261023T143229.393594Z.json`: **failed**, timeout;
the production compiler was repaired with raw-path prefix lookup. Root's saved
`python-tests-prefix-final-20261023T143839.412525Z.json` passed the unchanged
packed-limit fixture as part of its 139-test suite. The final dictionary
transport regression also passed, as recorded below.
No performance result was accepted from this test.

Additional implementation decisions and checks:

| Finding | Decision / implementation | Validation / actual status |
|---|---|---|
| T5 is a memory snapshot; requesting seq0 can legitimately expire at later anchors | Capture `after_seq=len(oracle.rows)` independently for the requested snapshot; keep all capacities, B values, anchors and memory/recount/allocator observations. `matrix.make_plan`, `run.digest_requests` | Independent head-capture fixture passed; actual T5 campaign pending |
| A process can be interrupted between append publication and state save | Atomic pending process journal, idempotent replay into append-only files, completed marker compaction, immutable failed sessions and identical-plan/source/threshold guards on `--resume`. `run.publish_commit`, `execute` | Simulated interrupted partial publication recovered once, with no duplicate rows; passed |
| Compiler labels must describe the actual build | Record CMake compile command, fresh environment compiler probe, source/binary/input hash ledger and fresh actual ASLR probe; extend visible-process check to new executables. `run.execute`, `p5_helpers` | Source/CLI integration checked; isolated campaign execution pending |
| Final frequency medians are unavailable while rows are appended | Save session `frequency-flags.json` sidecar and reference; match annotations by config/process/rep/warmup. T2 retains every constituent reader and both writer endpoints. Missing samples remain unknown. `audit.frequency_flags`, `run.aggregate_t2`, `execute` | Outlier, missing-frequency and all-constituent fixtures passed; analysis loader integration separately checked by review agent |
| Declared empirical payload mix must reach both generators | Pass the configured mix explicitly to C++ synthetic invocations. `matrix.make_plan`, `run.command_for` | Reduced independent generator checks passed using the accepted mix |

`exp-integration-unit-final-20261023T143721.799670Z.json`: **14 passed**.
This refresh does not alter the approved experimental matrix, repetitions,
thresholds, error semantics or acceptance criteria. Pilot/training/evaluation
measurements, calibration, figures and the P6 gate remain pending.

The transport dictionary stores each actual UTF-8 subscription string once per
workload, bound to its full SHA-256, and request TSVs use `@<sha256>`. This avoids
repeating multi-megabyte P=100,000 termsets in every arm and process round; it
does not replace the independent oracle terms or change subscription semantics.
The actual dictionary, its SHA, unique count, request TSV SHA and resolved
configuration identities are saved. C++ validates dictionary content hashes
before untimed sorted precompilation. Plain/alias equality and missing, duplicate
and content-mismatch cases are explicit functional checks.

M3 normalization now exposes `seek_ns` and `scan_ns_per_entry` in addition to
per-operation CPU, retaining the raw GBench row and its actual
`operations_per_iteration` denominator.

The final runner also rejects observations after a process/AC-control failure
even if complete valid JSON was emitted: `measurement_command_ok` includes every
on/off process AC snapshot and exit status, is saved per row, participates in
the acceptance gate, and cannot be hidden by a valid output digest.

Final preparation/aggregation corrections:

- A real workload contains 21,006 request arms but only four distinct backlog
  thresholds. `OutcomeOracle.after_timestamp` now memoizes thresholds and uses
  scalar `bisect_left` on the timestamp view. Snapshot anchor selection uses the
  same logarithmic scalar search. This avoids repeatedly passing the full
  strided 32.8M-element field to NumPy search. Past/exact/future/repeated threshold
  results are checked against an independent scalar count. The initial slow
  full-preparation attempt is retained by root; no timing campaign used it.
- T2 sums all readers' counts, payload bytes, CPU/wall and every logical work
  counter. Each individual reader retains its independent SHA/outcome/checkpoint
  in `reader-runs.jsonl`. The cohort has **null** stream digests, sink, checkpoint
  and error, plus an explicit per-reader validation reference/count. It never
  labels one reader's hash as a whole-cohort hash. Effective-mode counts preserve
  mixed Auto cohorts; per-reader-only selection estimates are null at cohort
  scope. A two-reader fixture uses different hashes and effective modes.

Latest actual checks (all are functional/regression work, not measurements):

| Saved command record | Actual result |
|---|---|
| `exp-dictionary-functional-final-20261023T144512.138724Z.json` | 54 passed; all 36 reduced generators/outcomes plus packed100k/dictionary transport and oracle/protocol checks |
| `python-full-dictionary-final-20261023T144637.034036Z.json` | 142 passed; full Python suite, 29.040s command duration |
| `exp-T2-cohort-final-20261023T144755.490627Z.json` | Protocol/T2 plus analysis/statistics/figure regressions passed after final cohort aggregation correction |
| `exp-scalar-threshold-final-20261023T144948.176931Z.json` | 54 passed against final scalar threshold search and dictionary-aware executable; packed timeout remains 180s |

The full-suite check preceded the final scalar-search optimization; its affected
oracle/protocol/executable comparisons were rerun in the last row. No current
functional failure remains. Actual P6 pilot/training/evaluation, frozen Auto
selection, raw audit, figures and the phase gate remain pending. Python source
is ready for root's preparation/measurement barrier; no agent measurement was
started.
