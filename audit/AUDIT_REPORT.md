# tiplog — Stage 1 forensic audit report

| | |
|---|---|
| Audited tree | `/home/abc/Desktop/Jane Street` (git metadata in `.tiplog-git`; HEAD `aa13c18`, plus 281 uncommitted/untracked entries = the P6–P8 work) |
| Audit dates | 2026-10-25 → 2026-10-26 |
| Mode | **Stage 1, read-only.** Every build and test ran in a scratch copy. The only files written in the project are under `audit/`. |
| Evidence | `audit/evidence/<stage>/` (logs, JSON, JUnit XML, per-step exit codes in `steps.tsv`) |
| Reproduce | `audit/tools/run_stage1.sh <scratch-dir> A B C D E` (stages described in §2.3) |

Status labels: `PASS | FAIL | PARTIALLY VERIFIED | NOT APPLICABLE | NOT VERIFIED`.
Finding labels: `CONFIRMED` (reproduced by an executed test or command), `SUSPECTED` (code reading only),
`TOOL WARNING` (static tool output not confirmed). Tests are labelled `EXECUTED` or `PROPOSED`.

---

## 1. Executive summary

**Health score: 8.0 / 10.**

Justification. Every correctness and reproducibility criterion that could be re-executed on this host was
re-executed and passed, several of them with stronger inputs than the project used (§8). The core engine
held up under independent models the project does not have: a pool-pressure model (≈170k ForceEvict
events, ≈290k RejectPublish rejections), random-payload mode/kernel equivalence, larger rational
optimizer instances, and cross-language parser differentials. No crash, sanitizer report, oracle mismatch
or data-integrity defect was found in the engine, index, merge kernels, layout solvers or parsers.

The score is not higher because of: one MEDIUM resource-exhaustion weakness reachable from a valid input
file (AUD-001), one MEDIUM test-architecture gap that mutation testing exposed (AUD-003: the invariant
checkers the whole suite relies on are never shown to fail), a quadratic hot path (AUD-002), thin
delivery coverage behind the headline "108 M differential operations" (AUD-004), and a handful of LOW
contract/documentation deviations. Performance claims were traced to recorded data but not re-measured
(the project's own rules require a quiet machine; §15).

**Verdict: CONDITIONAL PASS.** Conditions: (1) decide and implement a bound or an efficient path for topic
depth/length before any untrusted topic names reach the engine (AUD-001); (2) add negative tests for the
invariant checkers (AUD-003). All other items are LOW/INFO.

### Top 10 risks

| # | ID | Severity | Risk |
|---|---|---|---|
| 1 | AUD-001 | MEDIUM | A valid 128 KB trace with deep topic paths drives `tiplog_sim` to ~2 GB RSS; `compile()` cost grows ~cubically with path depth (20.8 s at depth 8,000). No depth/length limit exists. |
| 2 | AUD-003 | MEDIUM | Making `Ring`/`Index`/`Engine::check_invariants()` a no-op passes the entire project suite (mutants M01–M03 survive). The randomized and fuzz tests use these checkers as their main oracle. |
| 3 | AUD-002 | LOW | New-topic notification deduplicates subtree observers with a linear search: ~N² in live subscriptions on one root (0.53 ms → 7.7 ms per topic, 2k → 8k subscriptions). |
| 4 | AUD-004 | LOW | The CC-2 campaign meets "1,000 seeds × 10,000 ops" but only 4.0% of its batches execute replay work, 48.4% of opens are `HistoryExpired`, and 0.023 records are delivered per operation; payloads are single repeated bytes. |
| 5 | AUD-005 | LOW | A malformed ITCH symbol (all spaces) aborts conversion with a plain `ValueError` and no byte offset, contrary to ARCHITECTURE §12. |
| 6 | AUD-012 | LOW | The F3 engine fuzzer's recorded 30-minute gate ran 39,231 executions (~22 exec/s; the audit's 600 s run: 21 exec/s); per-input cost is dominated by fixed fixtures and O(N) checks. |
| 7 | AUD-007 | LOW | `pytest==9.0.2` is affected by CVE-2025-71176 (insecure `/tmp/pytest-of-{user}` handling); fixed in 9.0.3. Dev-only. |
| 8 | AUD-006 | LOW | A project test reads `configs/P6/matrix.toml` relative to the CWD; running the suite from `py/` fails. |
| 9 | AUD-008 | LOW | `Ring::at()` (public via `Engine::ring()`) accepts an aligned interior position and returns a fabricated record decoded from payload bytes. |
| 10 | AUD-009 | LOW (SUSPECTED) | Re-acquiring the Nasdaq file never compares the new SHA-256 with the recorded one; the manifest is overwritten (trust on first use). |

---

## 2. Scope and inventory

### 2.1 What was inspected

| Area | Files | Inspection |
|---|---|---|
| C++ core library | 24 files, 4,686 lines (`src/tiplog/**`) | Every file read in full |
| C++ tools/benchmarks | 14 files, 4,237 lines (`tools/**`, `bench/micro/**`) | `tiplog_sim`, `tiplog_layout`, `tiplog_walk`, `tiplog_trace_check`, `tiplog_differential` read in full; `tiplog_bench`, `runtime_main`, `index_bench`/`merge_bench`/`publish_bench` scanned + static analysis |
| C++ tests | 24 files, 5,627 lines | Oracle, differential campaign, fuzz targets, pressure fixture read in full; unit tests scanned |
| Python package | 31 modules (`py/tiplog_py/**`) | Parsers, router, trace format, converter, fetch, P6 oracle, stats, P7 input generator read in full; analysis/figure/experiment runners scanned |
| Scripts | 31 files (`scripts/**`) | Scanned; security grep (no `shell=True`, no `eval`, all subprocess argv lists) |
| Documentation | README, 10 plan docs, 4 report docs, 6 prompt templates (≈6,000 lines) | INDEX, PROBLEM_STATEMENT, ARCHITECTURE, VALIDATION_PLAN, REPORT read in full; others scanned for claims |
| Build/config | `CMakeLists.txt`, 12 `cmake/*.cmake`, `CMakePresets.json`, `py/requirements.txt`, `configs/**` | Read |
| Git history | 2 commits (`d4e5b83`, `aa13c18`) + working tree | Secrets scan over full history and tree; tracked-blob size and fuzz-corpus content check |

Not inspected line by line: the 1,250 + 806 + 95 + 74 fuzz-corpus files (checked for ASCII content only),
`results/**` raw data (7.0 GB, read only where a reproduction needed it), figure PDFs/PNGs.

### 2.2 Counts

| Item | Count |
|---|---|
| Requirements traced | 56 rows (§4) |
| Existing tests executed | 186 CTest × 4 presets = 744 passes; 151 pytest (documented invocation) |
| New audit tests | 7 C++ binaries (27 test cases), 2 Python files (1,075 test cases incl. parametrized) |
| New audit tests executed | all; **4 intentionally failing red specifications** (RED-01..RED-04), everything else passes |
| Reproductions executed | CC-2 (9 configs), CC-5, CC-6 (full day + live prefix), RC-3 (18 runs), V32, P7 headline recomputation, RC-1 figures |
| Mutants executed | 25 (20 killed by project tests, 2 equivalent, 3 real survivors) |
| Confirmed issues | 2 MEDIUM, 7 LOW (+1 SUSPECTED LOW, 3 INFO) |
| Blocked / not verified | performance re-measurement, 30-minute fuzz gates, P6 saved-output audit re-run, Python full-day count re-run (§15) |

### 2.3 Method and environment

Host: 12th Gen Intel Core i5-1235U, 10 logical CPUs, 14 GiB RAM, Linux 7.0.0-38; GCC 15.2.0, Clang 21.1.8,
CMake 4.4.0, Python 3.14.4 (project `.venv`, read-only use). Exact versions: `audit/evidence/A_baseline/environment.log`.

Isolation. `audit/tools/run_stage1.sh` copies the repository (excluding `build/`, `.venv`, `.tiplog-git`,
`data/raw`, `data/traces`, `results/raw`, `results/derived`) into a scratch tmpfs directory and builds there.
Raw data and traces are read in place. Python bytecode for project modules is written only in the copy.
Stages: **A** baseline builds/tests; **B** audit tests (release, ASan/UBSan, coverage) and red-team probes;
**C** reproductions (CC-2, CC-5, V32, CC-6, RC-3); **D** static analysis, mutation, dependency audit, fuzzing;
**E** P7 headline recomputation. RC-1 was run separately (`audit/evidence/F_rc1_figures/`).

Process deviations, disclosed:
- The host rebooted between sessions and the tmpfs scratch directory (and the first round of raw logs) was
  lost. Every number in this report comes from the second, persisted run in `audit/evidence/`.
- During the first session, a coverage-instrumented CMake feature probe (Google Benchmark's `try_run`) wrote a
  160-byte `default.profraw` into the project root at 2026-10-25 22:31:05. It contained no project data and was
  deleted; the pipeline now pins `LLVM_PROFILE_FILE` to the scratch directory. In the re-run that trap caught four
  identical 160-byte probe profiles from the coverage configure (`audit/evidence/stray-profraw-check.txt`), which
  confirms the cause. After the pipeline, `scripts/git.sh status --short` shows exactly the 281 pre-audit entries
  plus `audit/` (`audit/evidence/pipeline.txt`), and the managed `.git` directory is still mode 0555.

---

## 3. Architecture reconstruction and documentation-vs-code consistency

### 3.1 Reconstructed architecture

```
 ITCH .gz ──► py: BinaryFileReader ─► Router(H-spec/H-flat) ─► TraceWriter ──► trace v1 (.mdt)
              (protocol.py)            (routing.py)            (trace/format.py)        │
 ITCH .gz ──► C++ ItchWalker (independent, CC-6 counts only)                              │
                                                                                          ▼
                       tiplog_sim ── driver::drive_trace ── trace::Reader (mmap, full validation)
                                            │ publish(intern(path), payload)
                                            ▼
   Engine ─┬─ topics::Registry (path↔id, partition = depth-≤2 ancestor, u16 local ids, observer hooks)
           ├─ subs::CompiledSubscription (shared state; per-partition bitset/all filters; wide ⇒ Scan)
           ├─ ring::Ring (8-aligned byte ring, PAD, whole-record FIFO eviction, sparse seq checkpoints)
           ├─ index::Index (shared block pool, per-partition block lists, sealed-block expiry min-heap,
           │                 lazy/swept open-block expiry, ForceEvict/RejectPublish pressure)
           └─ Replay / Tail (captured upper bound, common unread checkpoint, Scan | Indexed(k-way merge) | Auto)
                         merge::{StdPQ, BinHeap, Quad, Loser} over packed (pos>>3)<<16|cursor keys
 layout (separate library): model (prepare, two evaluators, H-BASE, H-KM), exact (ENUM, MASK-DP), global (Lagrangian)
 tests only: ref::ScanOracle / OracleTail (string-prefix matching, independent retention); Python V27 oracle
```

Trust boundaries (core has no network, no concurrency, no persistence): (1) the downloaded Nasdaq file;
(2) trace files read by `tiplog_sim`/`tiplog_trace_check`; (3) TSV inputs to `tiplog_layout`; (4) library
API callers (topic names, subscription specs, resume checkpoints, payload spans). Threat model used for §7 and
§11: a local user who can supply any of these inputs; no remote attacker exists in the core.

### 3.2 Consistency with the documents

| Topic | Documents | Code | Verdict |
|---|---|---|---|
| Module map, dependencies, ownership (ARCH §4) | layout independent of engine; oracle imports only `types.hpp`; Replay/Tail non-owning | Same (CMake target graph is a DAG; `tests/ref` includes only `tiplog/types.hpp`) | PASS |
| Ring framing, PAD, limits (ARCH §5.3) | 16-byte header, PAD ≥ 8, `max_record ≤ C/2`, checked preflight | `ring.cpp:dry_run/commit` | PASS |
| Seq↔pos checkpoints (§5.4) | every 2^L seq, scan ≤ 2^L + PADs | `ring.cpp:seek_after` | PASS (slot count always sized for 16-byte minimum; harmless over-allocation at r_min=32) |
| Index & expiry heap (§5.5) | 32-byte BlockMeta, min-heap on (last_pos, block, gen), lazy open expiry, sweep | `index.cpp` | PASS |
| Replay contract (§3.6, §5.6) | common checkpoint, FellBehind before touching memory, Done precheck, no +1 overflow | `engine.cpp:Replay::next_batch_into` | PASS |
| Failure table (§12) | oversized record → `std::errc::invalid_argument`; invariant violation → abort with state dump; malformed ITCH → abort **with byte offset** | `std::length_error` (`ring.cpp:118`); `std::logic_error` with a message, no dump; blank symbol → `ValueError` without offset | **Deviates** (AUD-005, AUD-011) |
| EngineConfig (§9, illustrative) | `pool_blocks // validated against the sizing rule`; §5.5 "configuration is validated at startup" | Engine accepts any `blocks ≥ 1`; undersized pools rely on the pressure policy (verified correct in §8.2) | Doc ambiguity (AUD-011) |
| Topic resource bound (§4) | `O(#topics × (path + ~48 B))` | Holds per topic, but a single deep path creates `depth` topics each storing its full prefix | Bound is literally met; no limit on depth/length (AUD-001) |
| README / REPORT numbers | CC-1..CC-6, RC-2/RC-3, P6/P7 headline values | Re-executed or traced (§8.6) | PASS where checked |

---

## 4. Requirements traceability matrix

Implementation references are `file:function`. "P" = project test, "A" = audit test. Observed results cite
`audit/evidence/...`.

| ID | Requirement (source) | Implementation | Tests | Observed | Verdict |
|---|---|---|---|---|---|
| R-PUB-1 | Dense global seq from 1; 8-aligned, monotone, never recycled positions (ARCH §3.1) | `ring.cpp:Ring::dry_run/commit` | P ring_test, oracle diff, CC-2; A pressure, engine | All pass; CC-2 digests reproduced | Implemented |
| R-TOP-1 | `/`-separated non-empty segments; created on intern (§3.2, §5.1) | `registry.cpp:validate_path/intern` | P topics_subs_test; A redteam | Pass; no depth/length bound | Implemented (robustness gap AUD-001) |
| R-TOP-2 | Partition = ancestor at depth min(2,d); u16 local id; reject exhaustion before mutation | `registry.cpp:intern` | P topics_subs_test; mutant M09 killed | Pass | Implemented |
| R-TOP-3 | Creation hook notifies subtree subscriptions (≤ depth lookups) | `registry.cpp:intern` (affected set), `compiled.cpp:Prepared` | P topics_subs_test | Correct; O(N²) dedupe | Implemented (perf gap AUD-002) |
| R-SUB-1 | Exact/Subtree at segment boundaries; future topics included (§3.2) | `compiled.cpp:Matching, compile` | P; A engine (oracle diff) | Pass | Implemented |
| R-SUB-2 | Union, at most once per subscription; normalization rules (§3.3) | `compiled.cpp:normalize`; one cursor per partition | P; M20 killed | Pass | Implemented |
| R-SUB-3 | Wide (depth-1 subtree) terms served by Scan (§3.3, §5.2) | `compiled.cpp:compile`, `engine.cpp:Replay` | P; M17 killed | Pass | Implemented |
| R-RET-1 | Byte-capacity overwrite-oldest, whole-record FIFO (§3.5) | `ring.cpp:dry_run` | P oracle; A pressure model | Pass | Implemented |
| R-REP-1 | Captured upper bound, nothing later delivered (§3.6, Q5) | `engine.cpp:Replay::Replay` | P; A engine | Pass | Implemented |
| R-REP-2 | `HistoryExpired` at open, nothing delivered | `engine.cpp:Replay::Replay` | P; A engine/pressure | Pass | Implemented |
| R-REP-3 | Common conservative checkpoint; FellBehind before memory access (§3.6) | `engine.cpp:next_batch_into` | P; M05/M06 killed; A pressure model | Pass | Implemented |
| R-REP-4 | `max=0` no progress; Done if `unread==upper` before expiry check | same | P V35 tests; M06 killed | Pass | Implemented |
| R-REP-5 | `after ≥ upper` ⇒ Done before `+1`; future start has no checkpoint | `Replay::Replay` | P; A engine | Pass | Implemented |
| R-REP-6 | `open_tail` rejects future start (`InvalidRange`) | `Engine::open_tail` | P; M16 killed | Pass | Implemented |
| R-REP-7 | Resume checkpoint validated, arbitrary offsets never interpreted (§5.4) | `Replay::Replay` (supplied branch) | A ForgedResumeCheckpointPositionsAreIgnored | Pass | Implemented |
| R-TAIL-1 | Live stream = chain of snapshots; chaining exact (Q6) | `engine.cpp:Tail::poll` | P engine_merge/oracle_tail tests, F3 corpus; A TailChaining (200 seeds) | Pass | Implemented |
| R-MODE-1 | Scan/Indexed(all kernels)/Auto identical outputs, statuses, checkpoints, errors (Q7) | `Replay::next_batch_into` | P; CC-2 identical digests; A ModeAndKernelEquivalence | Pass | Implemented |
| R-IDX-1 | Shared pool, per-partition lists, 32-B BlockMeta, 4-B entries (§5.5) | `index.cpp` | P index_test; M07/M14 killed | Pass | Implemented |
| R-IDX-2 | Sealed-block expiry min-heap; late partial seal (V37) | `index.cpp:seal/reclaim` | P index_test | Pass | Implemented |
| R-IDX-3 | Open-block lazy expiry + sweep on pressure / every N evictions | `index.cpp:prepare_append/commit/sweep_open` | P; A pressure (sweep 0/1/7) | Pass | Implemented |
| R-IDX-4 | Pool pressure: ForceEvict advances tail until one block frees; RejectPublish leaves state unchanged (V19) | `engine.cpp:publish`, `index.cpp:prepare_append` | P 1 fixed fixture; **A independent model, 400+400 seeds** | Pass (≈170k / ≈290k events) | Implemented |
| R-IDX-5 | Reader safety: min-key vs tail, generation checks (INV-Q4, V18) | `index.cpp:validate_cursor/advance` | P | Pass | Implemented |
| R-IDX-6 | Gauges equal brute-force recount (P4, V17) | `index.cpp:recount/check_invariants` | P; A checker test | Pass; checker failure path untested by P (AUD-003) | Implemented |
| R-MRG-1 | Four kernels, packed keys, k ≤ 65,535, sentinel, position < 2^51 (§5.7) | `kernels.hpp/.cpp` | P merge_test; M08/M19 killed | Pass | Implemented |
| R-AUTO-1 | Auto: Scan if wide, k > K_max, or estimate > ρ·records (§5.6) | `Replay::Replay` | P; RC-3 effective modes | Pass | Implemented |
| R-INV-R | Ring invariants R1–R7 (§10) | `Ring::check_invariants` | P (positive only); A checker (negative) | Pass; vacuous-checker mutant survives P | Implemented (test gap AUD-003) |
| R-INV-I/P | Index/pool invariants I1–I5, P1–P5 | `Index::recount/check_invariants` | P; A checker | same | Implemented (AUD-003) |
| R-INV-Q | Replay invariants Q1–Q7 | engine | P; A | Pass | Implemented |
| R-INV-M | Merge M1–M2 (M3 galloping is Tier C) | kernels | P | Pass | Implemented; M3 NOT APPLICABLE |
| R-TRC-1 | Trace v1 format; reader validates every length/offset (§5.0, V05) | `reader.cpp:Reader::validate/next`; `format.py` | P; fuzz F1; A 20k mutations; A 400 cross-language cases | Pass, Python and C++ accept/reject identically | Implemented |
| R-ITCH-1 | 23 types, spec lengths, BinaryFILE framing, terminator ⇒ incomplete (V01/V02) | `protocol.py`, `itch_walker.cpp` | P; A chunk invariance (C++ 2,000, Py 300), short reads, truncation | Pass | Implemented |
| R-ITCH-2 | Routing: S/V/W market, K by symbol, locate directory, unknown ⇒ `_unmapped` (§2.1, V03) | `routing.py:Router.route` | P; A router test | Pass | Implemented |
| R-ITCH-3 | Segment encoding: trim trailing spaces, %-encode outside `[A-Z0-9.]` | `routing.py:encode_symbol` | P | Pass; blank symbol raises untyped error | Partial (AUD-005) |
| R-ERR-1 | Malformed ITCH aborts with byte offset (§12) | `protocol.py:FramingError` | A RED-02 | Blank symbol: no offset | **Deviates** (AUD-005) |
| R-ERR-2 | Oversized record ⇒ `std::errc::invalid_argument`, no state change (§12) | `ring.cpp:dry_run` throws `std::length_error` | P expects `length_error` | No state change (PASS); error type differs from doc | Deviates (doc drift, AUD-011) |
| R-ERR-3 | Invariant violation ⇒ abort with state dump (§12) | throws `std::logic_error(message)` | A checker | Detects; no dump/abort | Deviates (doc drift, AUD-011) |
| R-LAY-1 | M-store model; two independent evaluators agree (L2, V28) | `model.cpp:evaluate_formula/evaluate_materialized` | P; A 3,000 random layouts | Pass | Implemented |
| R-LAY-2 | ENUM and MASK-DP exact for every k (L3, V29, CC-5) | `exact.cpp` | P CC-5; A 1,500 larger rational instances; M25 killed | Pass | Implemented |
| R-LAY-3 | H-BASE construction (V31) | `model.cpp:baseline` | P | Pass | Implemented |
| R-LAY-4 | H-KM exact for P_T; count(T) monotone (V30) | `model.cpp:threshold_layout` | P; **A brute force, 1,500 trees**; M24 killed | Pass | Implemented |
| R-LAY-5 | KM-min/max threshold endpoints, finite domain | `model.cpp:km_min/km_max` | P; A endpoint test | Pass | Implemented |
| R-LAY-6 | Checked rational/integer arithmetic, overflow rejection (V39) | `model.cpp:checked_*`, `prepare` | P | Pass | Implemented |
| R-LAY-7 | Global λ ≥ 0: own-budget optimality; certified bounds only with complete curves (§6.5) | `global.cpp` | P; **A brute force, 2,000 instances** | Pass | Implemented |
| R-LAY-8 | Worked example (V32) | `tools/tiplog_layout/worked_example.cpp` | P; C v32 | Byte-identical to recorded | Implemented |
| R-LAY-9 | Workloads W0–W3, class compression, H-BASE budget (§2.3, §6) | `inputs.py` | E regeneration | TSVs hash-identical to recorded inputs; W1/W2 totals reproduced (§8.6) | Implemented |
| NFR-CC1 | All required tests pass in release and ASan/UBSan, 0 sanitizer reports | — | A_baseline ctest ×4 | 186/186 ×4, 0 reports | PASS |
| NFR-CC2 | ≥1,000 seeds × ≥10,000 ops per mode/kernel (release) | `tests/differential` | C cc2 | Reproduced exactly (release); ASan 200-seed part not re-run | PASS (coverage caveat AUD-004) |
| NFR-CC3 | Each fuzz target ≥ 30 min at its gate | `tests/fuzz/targets` | D fuzz (300 s / 300 s / 600 s) | No crash: F1 11,922,936 runs, F2 453,724 runs (synthetic corpus), F3 12,881 runs; 30-min gates not re-run | PARTIALLY VERIFIED |
| NFR-CC4 | Every P6 configuration matches oracle output and outcome | `py/tiplog_py/exp/oracle.py`, `scripts/check_p6_experiments.py` | — | Oracle logic reviewed (§6); 10,295,181-check audit not re-run | PARTIALLY VERIFIED |
| NFR-CC5 | MASK-DP = ENUM, ≥10,000 instances | `tests/layout/layout_cc5.cpp` | C cc5; A larger | Reproduced, identical counters | PASS |
| NFR-CC6 | Python counts = C++ counts per type and locate | both parsers | C cc6 | Full day (C++ re-run) + 500 MB live prefix (both re-run) | PASS |
| NFR-RC1 | Figures regenerate from saved raw results | `figures/build.py` | F rc1 | 18/18 PNGs byte-identical; PDFs not compared (timestamps); final manifest step failed only because the audit ran the code out of tree (AUD-006 note) | PASS (PNGs) |
| NFR-RC2 | Converter byte-identical on repeat | converter | — | Not re-run (two full-day conversions ≈ hours, 3 GB writes) | NOT VERIFIED |
| NFR-RC3 | Identical digests across repeats and GCC/Clang | engine | C rc3, C cc2 | GCC = Clang on a 2M-record prefix (200× recorded prefix), 9 configs; CC-2 digests identical across two audit sessions; audit expiry runs fell behind with an empty prefix (non-empty-prefix case relies on the recorded RC-3) | PASS |
| H1–H7, T1–T5, M1–M3, L1–L5 | Experiment hypotheses and reported measurements | benchmarks, analysis | traced (§8.6) | Values trace to recorded data; timings not re-measured | NOT VERIFIED (re-measurement) |
| Tier C, R1–R10 | Galloping, T4, Binance, WAL, compaction, concurrency, network | — | — | Not authorized by the project | NOT APPLICABLE |

Undocumented extras: none found. Every file in `scripts/` and `tools/` is referenced from README, `docs/` or a `results/p*/` record (name search).

---

## 5. Findings register

Counts: **MEDIUM 2 · LOW 8 (1 SUSPECTED) · INFO 3 · TOOL WARNING 2 groups.** No CRITICAL or HIGH.

| ID | Category | Severity | Status | File:Function:Line |
|---|---|---|---|---|
| AUD-001 | Security / resource exhaustion | MEDIUM | CONFIRMED | `src/tiplog/topics/registry.cpp:Registry::validate_path:74`, `Registry::intern:125,180,193`; `src/tiplog/subs/compiled.cpp:has_subtree_prefix:21-26`, `compile:217` |
| AUD-003 | Test architecture | MEDIUM | CONFIRMED | `src/tiplog/ring/ring.cpp:Ring::check_invariants:281`; `src/tiplog/index/index.cpp:Index::check_invariants:557`; `src/tiplog/engine/engine.cpp:Engine::check_invariants:116` |
| AUD-002 | Performance | LOW | CONFIRMED | `src/tiplog/topics/registry.cpp:Registry::intern:210-212` |
| AUD-004 | Test architecture | LOW | CONFIRMED | `tests/differential/campaign.cpp:one_seed:88-125`; `tests/fuzz/targets/fuzz_engine_ops.cpp:162` |
| AUD-005 | Functional / error contract | LOW | CONFIRMED | `py/tiplog_py/itch/routing.py:encode_symbol:19-25`, `Router.route:63,74` |
| AUD-006 | Test architecture | LOW | CONFIRMED | `py/tests/test_exp_protocol.py:test_subscriptions_overlap_normalization_and_manifest_defaults:113` |
| AUD-007 | Dependencies | LOW | CONFIRMED | `py/requirements.txt:13` (`pytest==9.0.2`) |
| AUD-008 | API contract | LOW | CONFIRMED | `src/tiplog/ring/ring.cpp:Ring::at:101-105`; contract text `ring.hpp:126-127` |
| AUD-009 | Data integrity / supply chain | LOW | SUSPECTED | `py/tiplog_py/data/fetch.py:main:53-56,115-122` |
| AUD-012 | Test effectiveness | LOW | CONFIRMED (recorded data + audit run) | `tests/fuzz/targets/fuzz_engine_ops.cpp:LLVMFuzzerTestOneInput:105-109,144` |
| AUD-010 | Build reproducibility | INFO | CONFIRMED (by inspection) | `cmake/deps.cmake:31-35`; `README.md:36-43,75-77` |
| AUD-011 | Documentation drift | INFO | CONFIRMED | `docs/plan/ARCHITECTURE.md:346,658,780,785` vs `ring.cpp:118`, `engine.cpp:27-46` |
| AUD-013 | Resource use | INFO | CONFIRMED (measured) | `src/tiplog/trace/reader.cpp:Reader::validate:195-237` |
| TW-1 | clang-tidy | — | TOOL WARNING | 42 warnings, none confirmed (§10.1) |
| TW-2 | GCC `-fanalyzer` | — | TOOL WARNING | 16 warnings, none confirmed (§10.1) |

Detailed records follow the format: ID | Category | Severity | Status | Location | Evidence | Repro |
Expected vs Actual | Root cause | Impact | Recommended fix (text only) | Required regression test | Effort | Dependencies/Risks.

### AUD-001 — Unbounded topic depth/length: quadratic memory, cubic matching
- **Evidence.** `audit/evidence/B_audit_tests/redteam-depth-probe.log` (intern/compile time and heap per
  depth); `redteam-sim-unlimited.log` (`/usr/bin/time -v`: peak RSS of `tiplog_sim` on a 128 KB trace);
  `redteam-sim-1500MB.log` (`std::bad_alloc`, exit 1, under a 1.5 GB address-space limit);
  `release-audit_redteam_test.log`; red spec `release-audit_red_spec_test.log` (RED-01 fails).
- **Repro.** `PYTHONPATH=<copy>/py python audit/tools/make_deep_trace.py deep.mdt 16000 4` (four topic paths of
  depth 16,000, each 31,999 bytes; the file validates with `tiplog_trace_check`), then
  `/usr/bin/time -v build/release/tiplog_sim --trace deep.mdt`. For the CPU curve:
  `audit/tools/depth_probe.cpp` with depths 1,000…8,000.
- **Expected.** Either a declared representation limit rejects the path before mutation, or memory and matching
  stay near-linear in path bytes.
- **Actual.** `Registry::intern` stores every ancestor prefix as its own `std::string` (and a second copy in
  `staged_paths`), so one path of depth d costs Θ(d²) bytes. `has_subtree_prefix` hashes every prefix at every
  `/` boundary, so `compile()` (which matches every registered topic) costs Θ(d³) byte-hash work.
- **Root cause.** `validate_path` checks only empty segments/NUL; `Limits` bounds topics, partitions and local
  ids but not depth or path bytes. Matching rehashes prefixes instead of walking parent ids.
- **Impact.** Local DoS of `tiplog_sim` (and any embedding application) from one crafted trace record or API
  call; ITCH-derived topics have depth ≤ 4, so the production workload itself is unaffected.
- **Recommended fix.** Product decision required: (a) add `Limits::max_depth` and `max_path_bytes` (rejected
  before mutation, like the existing limits), and/or (b) match through the parent chain using topic ids
  (O(depth) id lookups per topic, no rehashing) and keep a per-node segment string rather than full prefixes.
  Mirror the bound in `TraceWriter`/`TraceReader` (Python and C++) so the converter cannot emit what the
  engine will reject.
- **Regression test.** RED-01 (`audit_red_spec_test.cpp`); plus a `tiplog_sim` E2E check that the crafted trace is
  rejected or stays under a memory ceiling.
- **Effort.** M. **Dependencies/risks.** Changing matching touches subscription compilation and hooks (P2
  code shared by every replay mode); rerun the full CC-2/F3 suite afterwards.

### AUD-003 — Invariant checkers are never shown to fail
- **Evidence.** `audit/evidence/D_static_mutation_deps_fuzz/mutation-results.json`: for M01–M03
  `killed_by_project` is empty (all 13 project test binaries pass) and the only audit binary that fails is
  `audit_checker_test` (outcome `survived_project_killed_audit`); `B_audit_tests/release-audit_checker_test.log`
  shows the new negative tests pass on the baseline. Coverage: the `corrupt(...)`/`broken(...)` branches of
  the checkers are 0-count in `B_audit_tests/uncovered-lines-project-tests.txt`.
- **Repro.** Apply mutant M01 (insert `return;` at the top of `Ring::check_invariants`), rebuild, run all
  project tests: all pass.
- **Expected.** The suite detects a checker that no longer checks (the randomized differential, fuzz and
  unit tests call `check_invariants()` after nearly every operation as their oracle).
- **Actual.** No project test ever corrupts state to see a checker throw.
- **Root cause.** Only positive (“invariants hold”) uses exist; no negative tests or fault injection.
- **Impact.** A future edit that weakens or short-circuits a checker would silently remove the strongest
  safety net behind CC-1/CC-2/CC-3 while every gate stays green.
- **Recommended fix.** Adopt `audit/tests/cpp/audit_checker_test.cpp` (corrupts a fill byte, a sequence number,
  a block count, and a record's topic through the existing read-only views) into the project suite, and add
  one negative case per invariant family (R1–R7, I1–I5, P1–P5).
- **Regression test.** `audit_checker_test` (EXECUTED: passes on baseline; fails on M01, M02, M03).
- **Effort.** S. **Dependencies/risks.** None; test-only.

### AUD-002 — Quadratic observer deduplication on topic creation
- **Evidence.** `B_audit_tests/release-audit_redteam_test.log` (`SubscriptionFanoutInternCost`), RED-04 in
  `release-audit_red_spec_test.log`.
- **Repro.** Compile N = 500/2,000/8,000 subscriptions `Subtree(s/X)`, intern 20 new topics under `s/X`, time per topic.
- **Expected.** O(N) per new topic (each affected observer must prepare an update once).
- **Actual.** `std::find_if(affected...)` per hook slot (`registry.cpp:211`) makes it O(N²).
- **Root cause.** Linear-search deduplication of `shared_ptr` observers.
- **Impact.** With many live subscriptions on one subtree, each new topic stalls the single publisher thread
  (7.7 ms per new topic at 8,000 subscriptions; quadratic extrapolation gives ~1 s at 100,000).
- **Recommended fix.** Deduplicate with an `unordered_set<const TopicObserver*>` (or a per-observer epoch mark).
- **Regression test.** RED-04 (scaling ratio < 6 for 4× subscriptions). **Effort.** S. **Risks.** None.

### AUD-004 — CC-2 delivery coverage is thin; payload content checks are weak
- **Evidence.** `C_reproductions/cc2-compare.log` (`coverage_profile`), the 9 JSON outputs in
  `C_reproductions/cc2/`.
- **Expected.** The 10,000-operation schedule should mostly exercise replay delivery, the core feature.
- **Actual.** Per release configuration: 10,000,000 operations, 1,888,634 batches of which 75,672 (4.0%)
  executed replay work; 899,244 of 1,857,515 opens (48.4%) were `HistoryExpired`; 231,676 records delivered
  (0.023 per operation). Payloads are one repeated byte (`campaign.cpp:123-125`, `fuzz_engine_ops.cpp:162`), so an
  intra-payload offset or byte-order error with correct length and locator would not be detected.
- **Root cause.** Tiny rings (4–64 KiB) with large payloads, random `after` values, eight slots and small budgets.
- **Impact.** The CC-2 evidence is honest in its JSON but weaker than "108 M differential operations" suggests.
  The audit's random-payload and pressure tests (§8.2) partially close the gap.
- **Recommended fix.** Bias `after` toward the retained range, raise ring sizes for a share of seeds, fill
  payloads with seeded random bytes, and report delivered records and execution batches in the CC-2 summary
  next to the operation count.
- **Regression test.** `AuditEngine.ModeAndKernelEquivalenceWithRandomPayloads` and `AuditPressure.*` (EXECUTED, pass).
- **Effort.** S.

### AUD-005 — Malformed ITCH symbol aborts without a byte offset
- **Evidence.** `B_audit_tests/pytest-audit.log`: `test_red02_blank_symbol_aborts_with_framing_error_and_offset`
  fails with `ValueError: empty stock symbol` raised at `routing.py:25`.
- **Repro.** A BinaryFILE stream with an `S` message then an `R` message whose 8-byte symbol is all spaces;
  `python -m tiplog_py.itch convert <file> --output out.mdt`.
- **Expected (ARCH §12).** Strict mode aborts *with byte offset* (`FramingError.offset`).
- **Actual.** Conversion aborts (correct), partial traces are removed (correct), but the error is an untyped
  `ValueError` with no offset; the CLI prints `ITCH error: empty stock symbol`.
- **Root cause.** `encode_symbol` validates independently of the framing reader and has no offset context.
- **Recommended fix.** Validate the symbol field in `Router.route` (or the converter loop) and raise
  `FramingError(message, offset)` using the reader's current frame offset.
- **Regression test.** RED-02. **Effort.** S.

### AUD-006 — CWD-dependent project test
- **Evidence.** `A_baseline/pytest-from-py-dir.log` (1 failed, `FileNotFoundError: configs/P6/matrix.toml`) vs
  `A_baseline/pytest-documented-root.log` (151 passed); RED-03 in `B_audit_tests/pytest-audit.log`.
- **Related (INFO).** `py/tiplog_py/figures/layout.py:167` records `Path(__file__).relative_to(Path.cwd())`, so
  the figure build raises `ValueError` unless the code lives under the current directory
  (`F_rc1_figures/figures-build.log`; all 18 PNGs were already written when it failed).
- **Recommended fix.** Resolve the path from `Path(__file__).resolve().parents[2]`; record the figure source
  path relative to the package root rather than the CWD.
- **Regression test.** RED-03. **Effort.** S.

### AUD-007 — pytest 9.0.2 advisory (CVE-2025-71176 / GHSA-6w46-j5rx-g56g / PYSEC-2026-1845)
- **Evidence.** `D_static_mutation_deps_fuzz/pip-audit.json`; OSV range `introduced 0, fixed 9.0.3`.
- **Impact.** Local DoS/privilege risk on multi-user hosts via predictable `/tmp/pytest-of-{user}`; dev-only.
- **Recommended fix.** Pin `pytest==9.0.3` (or later) and re-freeze. **Regression test.** `pip-audit` step in CI. **Effort.** S.

### AUD-008 — `Ring::at()` returns fabricated items for interior positions
- **Evidence.** `B_audit_tests/release-audit_redteam_test.log` (`RingAtInteriorPositionFabricatesItem`:
  `ring.at(16)` returns seq 57, never published, no exception).
- **Expected.** Header comment (`ring.hpp:126-127`): position "must be a retained item boundary"; "malformed
  /range-invalid positions throw before access". The behavior for an aligned interior position is unspecified.
- **Impact.** Memory-safe (bounds are checked), but a caller can obtain a forged record. Internal callers pass
  only index/ring-derived boundaries (verified by the differential tests).
- **Recommended fix.** Decision required: document that interior positions are a precondition violation with
  unspecified result, or check boundaries in debug builds (`is_boundary` is O(retained), so not in release).
- **Regression test.** PROPOSED, depends on the decision. **Effort.** S.

### AUD-009 — Re-acquisition does not verify the recorded checksum (SUSPECTED)
- **Evidence.** Code reading only: `fetch.py:53-56` checks URL and Last-Modified, then `fetch.py:115-122`
  computes a fresh SHA-256 and overwrites `data/manifest.json` without comparing it to the previous value.
- **Why not executed.** It requires downloading the 3.5 GB file from Nasdaq (third-party service).
- **Recommended fix.** If a manifest SHA-256 exists, fail on mismatch; pass `--source-sha256` from the manifest
  to the converter by default. **Effort.** S.

### AUD-012 — Low F3 fuzz throughput
- **Evidence.** Recorded gate: 1,802.6 s and 39,231 executions (`results/p6/fuzz-prefix-final-verified.json`, quoted
  in REPORT §5). Audit run: 12,881 runs in 603 s (21 exec/s, peak RSS 994 MB), no crash
  (`D_static_mutation_deps_fuzz/fuzz-engine_ops-all-600s.log`); for comparison F1 ran 39,611 exec/s.
- **Root cause.** With `TIPLOG_FUZZ_MODE=all`, every input whose first byte has bit 7 set runs the full pressure
  fixture four times; each operation also runs `Engine::check_invariants()` (O(retained)), up to 16,384 ops/input.
- **Recommended fix.** Run the fixed fixtures once per process (or as unit tests), and cap per-input operations
  lower. **Effort.** S.

### AUD-010 (INFO) — Build inputs not fully hash-pinned
`pip install -r py/requirements.txt` without `--require-hashes`; an exact system GoogleTest 1.17.0 takes
precedence over the hash-verified archive (documented, `cmake/deps.cmake:31-35`, `README.md:75-77`). Cached archives match the
pinned SHA-256s (`D_.../dependency-archive-sha256.log`); OSV lists no advisories for either pinned commit
(`osv-cpp-pins.log`).

### AUD-011 (INFO) — Documentation drift in the failure table and EngineConfig comment
See §3.2. Either update ARCHITECTURE §12/§9 to the implemented behavior (`std::length_error`; checkers throw
`std::logic_error`; undersized pools are allowed and handled by the pressure policy) or change the code.

### AUD-013 (INFO) — Trace dictionary memory amplification
`Reader::validate` keeps three containers per dictionary entry: 7.6× heap per file byte for a 2.6 MB
dictionary-only trace (`release-audit_redteam_test.log`). Bounded by file size; no action required beyond
noting it alongside AUD-001.

---

## 6. Functional and architectural defects

No functional defect was found in the replay engine, ring, index, merge kernels, layout solvers, trace
readers or ITCH walkers. The review checked, among others: PAD placement and the `pad + need ≤ C` argument;
capacity floor vs boundary rounding; sparse-checkpoint staleness; expiry-heap ordering with late seals;
index-version/plan-owner commit guards; supplied-checkpoint sanitization; Tail re-open and error conversion;
packed-key ranges; loser-tree replay paths; DP state sufficiency, caps and reconstruction; KM optimality and
threshold plateaus; Lagrangian certificate preconditions; the Python V27 oracle's PAD/retention prefix-sum
algorithm; and the P7 workload/class-compression rules against ARCHITECTURE §2.3. Two hypotheses raised during
review were **rejected by measurement**:

- *ForceEvict pressure is O(retained) per publish* (because `dry_run` calls the linear `is_boundary`). The walk
  stops at the oldest block's end, i.e. exactly the items evicted anyway. Measured: 1.17× publish cost (86.9 ms vs
  74.4 ms per 1 M publishes) with an undersized pool while it evicted 3,606,481 records under pressure
  (`release-audit_redteam_test.log`).
- *Undersized pools break retention semantics.* The independent pressure model agreed on every tail position,
  pressure counter, rejection and replay outcome (§8.2).

Architecture: layering matches ARCHITECTURE §4; no circular dependencies; the optimizer is isolated from the
engine; the test oracle shares no production helpers. Contract deviations are documentation-level (AUD-011)
plus AUD-005 and AUD-008.

## 7. Security and threat-model assessment

| Surface | Checks | Result |
|---|---|---|
| Trace files (C++ `Reader`, Python `TraceReader`) | 20,000 mutated traces (C++, release+ASan), 400 cross-language accept/reject comparisons, libFuzzer F1 run | No crash/UB; identical accept/reject; only `FormatError`/`TraceError` raised. DoS via deep paths: AUD-001 |
| BinaryFILE streams (C++/Python) | Chunk-invariance, short reads, truncation, 60 C++/Python count comparisons, libFuzzer F2 run | PASS |
| Engine API | Forged resume checkpoints at every aligned offset; invalid topic ids; aliased payload republish; Replay/Tail after Engine destruction (release) | PASS (sanitized / rejected / copied / `logic_error` instead of use-after-free); `Ring::at` interior positions AUD-008 |
| Topic names / subscriptions | Deep paths, fan-out | AUD-001, AUD-002 |
| `tiplog_layout` TSV | Code review: checked integers/rationals, caps on states/work/time, input≠output check | No defect found (hard-link input/output aliasing bypasses the path check: INFO) |
| Injection | All `subprocess` calls use argv lists; no `shell=True`, `eval`, `pickle`, `yaml.load`, archive extraction; JSON writers escape | PASS |
| Secrets | Full git history (`log -p`) and tree scanned for key/token/password patterns; `.aws/.codex/.agents` are empty managed dirs | None found |
| Data licensing | Tracked fuzz corpus contains no ASCII runs ≥ 6 bytes (no symbol strings); tracked data are aggregates | PASS |
| Dependencies | pip-audit + OSV | AUD-007 (pytest); C++ pins clean |
| Network | Only `fetch.py` (curl with TLS, `--fail`, size/range checks) | AUD-009 |
| Concurrency/auth/session/XSS/SQL/SSRF/LLM | Not present in the core by design | NOT APPLICABLE |

## 8. Test results

### 8.1 Baseline (existing suites)

| Run | Command | Result | Duration |
|---|---|---|---|
| CTest release | `ctest --preset release -j4` | 186 passed, 0 failed, 0 skipped | see `A_baseline/steps.tsv` |
| CTest debug | `ctest --preset debug -j4` | 186 / 0 / 0 | 〃 |
| CTest asan-ubsan | `ctest --preset asan-ubsan -j4` | 186 / 0 / 0, 0 sanitizer reports | 〃 |
| CTest fuzz (corpus replay) | `ctest --preset fuzz -j4` | 186 / 0 / 0 | 〃 |
| pytest (documented) | `python -m pytest -c py/pytest.ini py/tests` from repo root | 151 passed | 〃 |
| pytest from `py/` | `python -m pytest` with cwd `py/` | 150 passed, 1 failed (AUD-006) | 〃 |
| Builds | 4 presets | 0 errors; 3 `-Wdangling-else` warnings in `tests/layout/layout_test.cpp` (GCC) | 〃 |

JUnit XML: `A_baseline/ctest-<preset>.xml`.

### 8.2 Audit tests (EXECUTED)

| Binary / file | Cases | Release | ASan/UBSan | What it adds |
|---|---|---|---|---|
| `audit_engine_test` | 6 | pass | pass (5; the release-only lifetime test is `#ifdef NDEBUG`) | Mode/kernel equivalence with random payloads; Tail vs reference over 200 seeds; aliased republish; lifetime safety; invalid topic; forged checkpoints |
| `audit_pressure_test` | 2 | pass | pass | Independent ForceEvict/RejectPublish model, all modes/kernels, 800 seeds × 2,000 ops |
| `audit_layout_test` | 5 | pass | pass | MASK-DP=ENUM to 15 nodes/6 classes with rational costs; evaluators; KM brute force; endpoints; global brute force |
| `audit_trace_test` | 3 | pass | pass | Trace round trip; 20,000 mutated traces; ITCH walker chunk invariance |
| `audit_checker_test` | 4 | pass | pass | Negative tests for the three invariant checkers (AUD-003) |
| `audit_redteam_test` | 5 | pass (demonstrations) | pass (4; timing test excluded) | AUD-001/002/008/013 measurements; pressure-cost hypothesis check |
| `audit_red_spec_test` | 2 | **fail (expected)** | fail (expected) | RED-01, RED-04 |
| `test_audit_parsers.py` | 1,062 | 1,061 pass, **1 expected fail** (RED-02) | — | Chunk/short-read/truncation properties; C++ vs Python walker; Python vs C++ trace reader differential; router |
| `test_audit_repo_hygiene.py` | 13 | 12 pass, **1 expected fail** (RED-03) | — | CWD independence; bootstrap/pairing contracts; time parser |

Logs: `B_audit_tests/release-*.log`, `asan-*.log`, `pytest-audit.log`.

### 8.3 Coverage (MEASURED, clang source-based, core `src/` + `tools/tiplog_bench/contracts.hpp`)

Per-file region, function, line and branch columns: `B_audit_tests/coverage-project.log` and
`coverage-project-plus-audit.log`.

| Scope | Lines | Branches (missed/total) |
|---|---|---|
| Project unit tests only | **94.50%** | **86.97%** (247/1,895) |
| Project + audit tests | 94.77% | 87.76% (232/1,895) |

Per file (project tests only), lowest branch coverage first: `index.cpp` 99.10% lines / 79.19% branches,
`ring.cpp` 92.44% / 81.44%, `reader.cpp` 91.88% / 83.33%, `exact.cpp` 95.47% / 86.89%, `engine.cpp`
96.08% / 87.56%, `model.cpp` 95.06% / 88.98%, `compiled.cpp` 100% / 89.71%, `registry.cpp` 92.38% / 90.38%.
The libFuzzer targets are not instrumented here, so fuzz-only paths count as missed. `llvm-cov` warned about
mismatched data for 110 header-defined functions instantiated in several binaries; header rows are approximate.

### 8.4 Untested-path inventory (project suite)

From `B_audit_tests/uncovered-lines-project-tests.txt`:
- All failure branches of `Ring/Index/Engine::check_invariants` and `Ring::decode` corruption checks (AUD-003).
- `Engine::publish` defensive branches `index pressure victim must reference DATA` and `pressure preparation did
  not free one block` (unreachable unless the index is corrupt).
- `Replay` indexed-path defensive throws (`retained unread checkpoint has expired cursor`, `index cursor references PAD`).
- `Engine::open_replay` `RepresentationLimit` for > 65,535 indexed cursors (Indexed mode, not Auto).
- `Tail::poll` error after a batch in the same poll (lines 419–422) — not covered by the project unit tests (the
  coverage build does not instrument the libFuzzer targets).
- `Registry` observer-serial exhaustion, depth exhaustion, `ObserverHandle` move-assignment.
- `Reader` OS error paths (`fstat`, `mmap` failure, empty file).

### 8.5 Mutation testing (EXECUTED, 25 hand-written mutants)

`D_static_mutation_deps_fuzz/mutation-results.json`. Project suite: 20 killed, 5 survived. Survivors: M01–M03
(vacuous checkers, real gap, AUD-003), M21 (`seek` ignores index tail) and M22 (accept non-PAD supplied
boundary) — both equivalent: their conditions are unreachable because `next_pos ≥ tail` is checked before
seeking, and a DATA record at the tail boundary makes `candidate == canonical`. Score 20/25 raw, 20/23 excluding
equivalent mutants (87%). With `audit_checker_test` added: 23/23.

### 8.6 Reproduction of documented results

| Claim | Reproduction | Result |
|---|---|---|
| CC-2: 9 configs × 1,000 seeds × 10,000 ops (release) | `C_reproductions/cc2/*.json`, `cc2-compare.log` | All counters and digest `1217005992737911606` identical to the recorded release rows |
| CC-5: 10,000 instances, 57,461 comparisons | `cc5-compare-recorded.log` | Identical counters |
| V32 worked example 5,517,460,497 / 39,881,491 / 30,029,491 | `v32-diff-recorded.log` | Byte-identical JSON |
| CC-6: 268,744,780 messages, 18 types, 8,907 locates | `cc6-*.log` | C++ re-run byte-identical to recorded C++ counts and equal to recorded Python counts; live Python vs C++ on a 500 MB prefix equal |
| RC-3: GCC = Clang | `rc3-compare.log` | 9 configs over 2,000,000 records (trace SHA-256 `6062bdb9…`), identical; outputs identical across modes/kernels for the success case (17,760 records) and the FellBehind case (empty prefix) |
| P7 inputs and W1/W2 headline (−27.9%, −30.2%; KM-min +2.5%, +1.1%) | `E_p7_recompute/*.log` | Regenerated TSVs hash-identical to the recorded manifest (W1 β0 `1e47cbc7…`, W2 β0 `f3bf6ba7…`, W1 β1 MiB `f86f7430…`). Recomputed totals, H-spec β=0, 8,907/8,907 feasible per method: W1 base 19,367,265,136, KM-min 14,312,697,608, DP 13,964,962,856 (−27.89%, +2.49%); W2 53,063,664,304 / 37,453,911,320 / 37,046,713,312 (−30.18%, +1.10%). Identical to REPORT §8.4 |
| P6 T1 ratios 40.62 [39.45, 41.69] and 0.585 [0.581, 0.593]; outcome totals | Traced in `results/derived/tip-paired-ratios.csv` rows 326 and 950, `tip-outcomes.csv` | Present exactly (40.619 [39.452, 41.693]; 0.5849 [0.5814, 0.5932]; ok 125,700, invalid_config 4,320, one `crash`-status interrupted attempt). Not re-measured |
| RC-1 figures | `F_rc1_figures/png-compare.json` | 18/18 PNGs (F01–F18) byte-identical to `results/figures/*.png` |

### 8.7 Second-run reconciliation

The first audit session's raw logs were lost in a host reboot (§2.3). The full pipeline was re-run on
2026-10-26 (`audit/evidence/pipeline.txt`: stages A–E finished 01:06–01:48 UTC). Every deterministic value
measured in both runs (test counts, digests, counters, mutation outcomes, project-suite coverage, CC-6 counts)
was identical. Project + audit coverage rose from 94.65% / 87.44% to 94.77% / 87.76% because the second run's
audit set includes the new checker tests; the P7 recomputation and RC-1 comparison ran only in the second run. Timing values differ slightly between runs and are quoted from the persisted run:
RED-01 compile 2.81 s (run 1: 2.6 s), RED-04 ratio 13.6 (run 1: 13.2), deep-path compile at depth 8,000 20.8 s
(run 1: 20.6 s), pressure cost ratio 1.17 (run 1: 1.34). One count was corrected: clang-tidy reports 42
warnings, not the 43 noted in run 1.

## 9. Performance, concurrency and reliability

- Performance defects: AUD-001 (deep paths), AUD-002 (fan-out). ForceEvict cost hypothesis rejected (§6).
- Allocation per indexed batch (`make_kernel`, cursor vectors) and the copy of the subscription handle per replay
  are constant-factor costs already inside the measured T1–T3 numbers; no change recommended without a benchmark.
- Concurrency: the core is single-threaded by design (ARCHITECTURE §1); R4 is not authorized. NOT APPLICABLE.
- Reliability: rejected publications leave state unchanged (verified for RejectPublish under random schedules);
  writer failure in the Python converter aborts all `.partial` traces, but if the second writer's `finish()` fails
  after the first succeeded, the first trace remains (code reading; LOW, not separately listed).
- Timing results were not re-measured (§15).

## 10. Dependencies, configuration, build and DevSecOps

### 10.1 Static analysis (TOOL WARNINGs)
- clang-tidy (`bugprone,cert,clang-analyzer,performance,concurrency`): 42 warnings
  (`D_.../clang-tidy.log`). 28 `bugprone-unchecked-optional-access` rely on the invariant "status `More` ⇒
  checkpoint engaged", which holds on every constructor path; 1 `clang-analyzer-security.ArrayBound` in
  `Quad::at` requires `heads.size()+3` to overflow, which `validate_heads` (≤ 65,535) excludes; the rest are
  `getenv`/`exit` thread-safety notes in single-threaded tools and benchmarks, two ignored `setvbuf`/`fprintf`
  return values in `tiplog_index_memory`, one empty catch in `runtime_main.cpp:84`, and style/performance notes
  (`std::move` of a trivially copyable type, an oversized enum base, a by-value parameter, an implicit widening).
  None confirmed.
- GCC `-fanalyzer`: 16 warnings in libstdc++ container internals and aggregate initialization
  (`gcc-fanalyzer.log`); contradicted by clean ASan/LSan runs. None confirmed.

### 10.2 Dependencies and build
Python: 15 pinned packages, `pip check` clean, one advisory (AUD-007). C++: Google Benchmark 1.9.5 and GoogleTest
1.17.0 pinned by commit + SHA-256 (archives verified); system GoogleTest 1.17.0 used when present (AUD-010).
Builds reproduce from a clean copy with the cached archives, no network needed.

### 10.3 Operations
Logging writes no secrets; tools print JSON with escaped strings. There is no CI configuration in the
repository; checks are run by `scripts/check_all.sh` locally (INFO). The closeout checker treats new
untracked paths as "unattributed", so `audit/` does not break the P8 gate.

## 11. Red-team scenarios (DISCOVER → DEMONSTRATE → DOCUMENT; nothing fixed)

| # | Entry point | Preconditions | Input / action | Expected | Actual | Impact | Severity | Evidence |
|---|---|---|---|---|---|---|---|---|
| RT-1 | `tiplog_sim --trace` | Attacker supplies a trace file | Valid 128,284-byte trace (5 records), 4 topics of depth 16,000 | Bounded memory or rejection | Peak RSS 2,034,208 KB in 3.5 s; `std::bad_alloc` (exit 1) under a 1.5 GB limit | Local DoS | MEDIUM (AUD-001) | `B_.../redteam-sim-*.log` |
| RT-2 | `Engine::intern` + `compile` | API caller controls topic names | One path of depth 2k–8k | Near-linear | compile 0.36 s → 2.70 s → 20.8 s (×7.5 per doubling); heap 8.3 → 32.6 → 129.3 MB | CPU/memory DoS | MEDIUM (AUD-001) | `redteam-depth-probe.log` |
| RT-3 | `Engine::compile` ×N + `intern` | Many subscriptions on one subtree | 500 / 2,000 / 8,000 subscriptions, new topics | O(N) | 0.063 / 0.533 / 7.72 ms per topic (×8.5, ×14.5 per 4×N) | Publisher stall | LOW (AUD-002) | `release-audit_redteam_test.log` |
| RT-4 | `Engine::open_replay(ResumeCheckpoint)` | Caller forges `next_pos` | Every aligned offset incl. planted fake headers | Ignored | Ignored (identical to honest replay) | — | none | `release-audit_engine_test.log` |
| RT-5 | `Engine::ring().at()` | Public const access | Aligned interior position | Throw | Fabricated record (seq 57) | Forged record to caller | LOW (AUD-008) | `release-audit_redteam_test.log` |
| RT-6 | Trace parsers | Corrupted trace | 20,000 mutations + 400 cross-language | `FormatError` only | `FormatError` only; Python = C++ | — | none | `release-audit_trace_test.log`, `pytest-audit.log` |
| RT-7 | Replay/Tail after `Engine` destroyed | Release build | `next_batch`/`poll` | No UAF | `std::logic_error` | — | none | `release-audit_engine_test.log` |
| RT-8 | `publish(payload aliasing ring)` | Caller republishes a delivered span | Span overwritten by the same publish | Bytes preserved | Preserved | — | none | 〃 |
| RT-9 | ITCH converter | Malformed symbol | All-space symbol | `FramingError` with offset | `ValueError`, no offset | Diagnostics | LOW (AUD-005) | `pytest-audit.log` |
| RT-10 | Pool pressure | Undersized pool | 800 random schedules | Documented policy | Matches model | — | none | `release-audit_pressure_test.log` |
| RT-11 | Secrets / data leakage | Repo access | History + tree scan, corpus scan | None | None | — | none | §7 |

## 12. Root-cause and defect dependency map

- **RC-A: no bounds on topic path shape** → AUD-001 (and contributes to AUD-013's memory profile). Fixing it may
  change `Registry::Limits`, `TraceWriter`/`Reader` validation and subscription matching; do it before AUD-002 so
  both registry changes land and are regression-tested together.
- **RC-B: linear-search deduplication in `Registry::intern`** → AUD-002. Independent of RC-A, same function.
- **RC-C: oracle-only use of invariant checkers** → AUD-003. Independent; should land first, because every other
  fix relies on the checkers as a safety net.
- **RC-D: test-generator parameters** → AUD-004, AUD-012. Independent.
- **RC-E: error-contract drift between plan and code** → AUD-005 (code), AUD-011 (docs). AUD-005 is a code fix;
  AUD-011 is a documentation decision.
- AUD-006, AUD-007, AUD-008, AUD-009, AUD-010 are independent.

## 13. TDD red-test catalog (Stage 2 acceptance contract)

| Test | File | Assertion | Baseline result (EXECUTED) | Finding |
|---|---|---|---|---|
| RED-01 `DeepTopicPathIsRejectedOrMatchedEfficiently` | `audit/tests/cpp/audit_red_spec_test.cpp` | depth-4,000 path is rejected with `RepresentationLimit` before mutation, **or** intern and compile each < 0.25 s | FAIL: compile 2.81 s | AUD-001 |
| RED-04 `SubtreeHookFanoutIsLinearInSubscriptions` | same | per-topic cost ratio for 8,000 vs 2,000 subscriptions < 6 | FAIL: ratio 13.6 (0.45 → 6.08 ms) | AUD-002 |
| RED-02 `test_red02_blank_symbol_aborts_with_framing_error_and_offset` | `audit/tests/py/test_audit_parsers.py` | converter raises `FramingError` with `.offset ∈ {14, 16}` | FAIL: `ValueError('empty stock symbol')` | AUD-005 |
| RED-03 `test_red03_project_tests_do_not_depend_on_working_directory` | `audit/tests/py/test_audit_repo_hygiene.py` | project test passes with cwd `py/` | FAIL: `FileNotFoundError` | AUD-006 |
| REG-03 `AuditChecker.*` (4 tests) | `audit/tests/cpp/audit_checker_test.cpp` | each checker throws on one corrupted field | PASS on baseline; FAIL on mutants M01–M03 | AUD-003 |
| REG-04 `AuditEngine.ModeAndKernelEquivalenceWithRandomPayloads`, `AuditPressure.*` | `audit_engine_test.cpp`, `audit_pressure_test.cpp` | random-payload equivalence; pressure model | PASS | AUD-004 |
| PROPOSED | — | `pip-audit` clean in CI | (fails today on pytest 9.0.2) | AUD-007 |
| PROPOSED | — | `fetch.py` fails on recorded-SHA mismatch (mocked curl) | not written | AUD-009 |
| PROPOSED | — | depends on the AUD-008 decision | not written | AUD-008 |

## 14. Prioritized remediation plan (for approval; nothing done)

| Batch | Items | Why first | Acceptance criteria | Risk |
|---|---|---|---|---|
| 1 | AUD-003 (adopt checker negative tests) | Restores the safety net every later fix relies on | REG-03 passes; M01–M03 killed by the project suite | None (tests only) |
| 2 | AUD-001 (decision: limits and/or parent-chain matching), then AUD-002 | Only MEDIUM security item; same module as AUD-002 | RED-01, RED-04 pass; RT-1 rejected or < 64 MB; full CTest ×4, CC-2 sample, fuzz smoke unchanged | Medium: touches subscription compilation; needs product decision on limits |
| 3 | AUD-005, AUD-006, AUD-007 | Small, independent | RED-02, RED-03 pass; `pip-audit` clean | Low |
| 4 | AUD-004, AUD-012 (test-generator tuning) | Strengthens evidence | CC-2 summary reports delivered/execution batches; execution-batch share and F3 exec/s increase | Low; changes recorded CC-2 digests (new evidence, not a regression) |
| 5 | AUD-009, AUD-010, AUD-011, AUD-008 | Docs/decisions | Documented decisions; tests as decided | Low |

Note for Stage 2: changing engine sources would invalidate the "19 core binaries byte-identical" provenance
recorded by the P7/P8 gates. Any remediation must be recorded as a new phase, not as a silent edit.

## 15. Residual risks, blockers and NOT VERIFIED items

| Item | Status | Blocker | Residual risk |
|---|---|---|---|
| P6/P7 timing results (T1–T5, M1–M3, DP runtime) | NOT VERIFIED (traced only) | Project rules require a quiet, pinned host; another Claude session and desktop load were present | Timing values could differ on a quiet re-run; ratios' recorded CIs are host-specific |
| CC-3 30-minute fuzz gates | PARTIALLY VERIFIED | Time-boxed to 5/5/10 min | Bugs needing longer campaigns |
| CC-4 10,295,181-check P6 audit | PARTIALLY VERIFIED | Re-running needs the 7 GB raw tree and writes into `results/` | Oracle logic reviewed; numbers not recomputed |
| CC-2 200-seed ASan/UBSan portion | NOT VERIFIED (re-run) | Time | Low: release part reproduced exactly and audit ASan runs are clean |
| RC-2 converter repeatability | NOT VERIFIED | Two full-day conversions (hours, ~3 GB writes) | Low |
| Python full-day count | PARTIALLY VERIFIED | ~1 h run | Low: recorded counts equal re-run C++ counts; live 500 MB prefix equal |
| `fetch.py` acquisition | NOT VERIFIED | Would contact Nasdaq | AUD-009 |
| `tiplog_bench`, `runtime_main`, benchmark harness internals | PARTIALLY VERIFIED | Static review + clang-tidy only | Measurement-harness bugs would affect timings, not correctness |
| Python figure/analysis code | PARTIALLY VERIFIED | Scanned; RC-1 output compared (§8.6) | Statistical-method errors outside the checked paths |

---

## 16. Independent second audit pass — 2026-10-26

**Review complete; implementation changes await approval.** This appendix preserves the first report
above and adds **13 new confirmed findings: 3 MEDIUM and 10 LOW**, plus one recommended feature.
AUD-001–AUD-013 retain their original identities and historical evidence. The combined numbered
register now contains **26 findings: 5 MEDIUM, 18 LOW (including the original suspected AUD-009),
and 3 INFO**. Additional inspection-only observations below are deliberately excluded from those counts.

**Independent assessment:** ordinary engine publication/replay correctness remains strong under the
executed tests. The most consequential new issues concern source-file preservation, interrupted
experiment recovery, and the integrity of the current derived reports. The first pass's conditional
verdict needs these additional conditions: resolve AUD-014/015 and reconcile AUD-026 before treating
regenerated evidence as accepted. The numerical health score in §1 is historical, not a new assurance
score for this pass. No audit can guarantee discovery of every possible defect; the evidence and
remaining limits below define what was actually assessed.

### 16.1 Scope, independence and verification

The review covered the current working tree, including the P6–P8 work absent from HEAD
`aa13c1824ba5a7a3593a0f63c6f455cac851e822`. Three parallel independent reviews covered the runtime,
Python tooling, and layout/trace/benchmark tools; the primary review covered build/configuration,
all 31 scripts, cross-component contracts, and consolidation. The prior findings were checked for
overlap and were not counted again.

| Area | Second-pass work |
|---|---|
| C++ production library | All 25 source/header files read: runtime, registry/subscriptions, ring/index, merge, driver, trace/walker, layout model/exact/global |
| C++ tools and benchmarks | All 10 tool files and 4 benchmark files read, including the previously scanned timing/frontends and benchmark fixtures |
| Python | All 31 package modules, the C hashing helper, and all 12 Python test files read; experiment journaling, acceptance, retention oracle, statistics and figures examined in depth |
| Build and orchestration | CMake/presets, 12 CMake fragments, requirements/configuration and 31 scripts reviewed; final evidence and source applicability checks executed |
| Tests and documentation | Relevant C++ unit/differential/fuzz/reference tests inspected; architecture, declared scope, report/reproduction contracts and prior audit consulted |
| Exclusions | Generated dependency internals and every raw data/corpus blob were not reviewed line by line. Large saved measurements were read where validation required them. No new controlled performance campaign was run. |

All new project artifacts are under `audit/second_pass/`; builds and destructive-input fixtures used
`/tmp`. No production implementation, configuration, accepted gate, raw measurement or source trace
was changed. A 6,829-file before/after manifest covers source, tests/corpora, scripts, configuration and
documentation outside `audit/`; see [the verification record](second_pass/root/source-verification.json).
The original report prefix is preserved byte for byte; its original length/hash are recorded in
[original-report.json](second_pass/root/original-report.json).

| Executed check | Result | Evidence |
|---|---|---|
| Fresh isolated Release configure/build and full CTest | **186 passed**, 0 failed | `second_pass/root/configure-release.log`, `build-release.log`, [CTest log](second_pass/root/ctest-release.log), [JUnit](second_pass/root/ctest-release.xml) |
| Fresh isolated ASan/UBSan build and full CTest | **186 passed**, 0 failed; leak checking enabled | `second_pass/root/configure-asan-retry.log`, `build-asan-final.log`, [CTest log](second_pass/root/ctest-asan.log), [JUnit](second_pass/root/ctest-asan.xml) |
| Full Python suite against the scratch source and fresh Release binaries | **151 passed**, 0 skipped | [pytest log](second_pass/root/pytest-final.log), [JUnit](second_pass/root/pytest-final.xml) |
| Targeted independent core/Python checks | 124 existing core tests and 109 Python tests passed; these overlap the full suites above and are not additional unique coverage counts | `second_pass/core/*_test.log`, `second_pass/python/targeted-pytest.log` |
| New defect/feature demonstrations | All final demonstration assertions succeeded, meaning the defects are present; these are not passing specifications for repaired behavior | [Core review](second_pass/core/findings.md), [Python review](second_pass/python/findings.md), [Tools review](second_pass/layout_tools/findings.md) |
| Full P6 saved-output independent audit re-executed | **10,295,181 checks; overall FAIL solely on 2 frozen build-file identities** (`CMakeLists.txt`, `build/release/compile_commands.json`); no output/outcome comparison failures | [Audit JSON](second_pass/root/cc4-rerun.json), [log](second_pass/root/cc4-rerun.log) |
| Current core closeout verification | **FAIL: 9 of 2,064 checks**, arising from 3 changed derived files and dependent compatibility checks; AUD-026 | [Closeout JSON](second_pass/root/core-closeout.json), [log](second_pass/root/core-closeout.log) |

The two P6 audit provenance failures refer to the later P7 build extension, not an output mismatch.
The separate closeout checker verifies that the CMake addition is the permitted layout include and
the original compile commands are retained. Nevertheless, the standalone P6 re-audit returned
**failed**, and is not relabelled passed. This substantially closes the first pass's unexecuted
CC-4-output check while retaining its source-applicability qualification.

Test setup limitations are retained in the logs: the initial Python scratch run lacked the expected
`build/release` path (3 setup failures and 39 skips); after binding that path to the fresh build, all
151 passed. The first sanitizer configure failed because LeakSanitizer cannot run under sandbox
tracing; cached failed feature probes were cleared and configuration/tests rerun outside tracing
with `ASAN_OPTIONS=detect_leaks=1:abort_on_error=1` and halt-on-error UBSan. The separate core observer
probe also has an earlier sanitizer log with leak checking disabled; the full-suite result above
does not depend on that log. These setup failures are not product findings.

### 16.2 New findings register

Every item below is **CONFIRMED by an executed reproduction**. Severity reflects this local,
single-threaded research project's actual exposure; no remote service or concurrent/durable contract
is assumed. Priority P1 means address in the next remediation work; P2 means follow after the safety
and evidence issues; P3 means a limited input/extension/tooling case. Effort is an estimate, not a commitment.

| ID | Severity / priority | Finding | Scope / likely effort |
|---|---|---|---|
| AUD-014 | MEDIUM / P1 | Measurement/conversion write-path aliases can destroy the source | Data CLI; S–M |
| AUD-015 | MEDIUM / P1 | Torn JSONL append prevents otherwise journalled process recovery | Experiment runner; M |
| AUD-016 | LOW / P2 | Retention oracle rewrites suffixes per PAD, producing quadratic preparation work | Experiment preparation; S–M |
| AUD-017 | LOW / P2 | Valid large payloads overflow the independent oracle's aligned-size field | Oracle/synthetic tooling; S |
| AUD-018 | LOW / P2 | T2 aggregation replaces the configured duration with 10 seconds | Nondefault matrix analysis; S |
| AUD-019 | LOW / P2 | Lightweight acceptance reports missing measurement controls as verified | Standalone validation helper; S |
| AUD-020 | LOW / P2 | Coarse partial-block estimates make Auto scan a sparse recent range | Runtime selection performance; M |
| AUD-021 | LOW / P3 | Reentrant public topic observers corrupt topic identity | Custom observer API; S–M |
| AUD-022 | LOW / P2 | Some evidence writers return success after output failure | Benchmark/example/CC-5 tools; S |
| AUD-023 | LOW / P3 | Synthetic mixture count overflow silently changes the workload | Custom mixture CSV; S |
| AUD-024 | LOW / P3 | Recording backend accepts NaN and emits invalid JSON | Simulator CLI; S |
| AUD-025 | LOW / P2 | Quiescence checker can inspect a different attempt's process log | Retried runtime rounds; S |
| AUD-026 | MEDIUM / P1 | Current derived evidence differs from frozen identities and loses available noise flags | Reporting/provenance; investigate, then S–M |

### 16.3 Detailed findings and proposed acceptance checks

#### AUD-014 — Source preservation checks omit actual write targets

**Location:** `py/tiplog_py/itch/__main__.py:69–85,95–109`; `py/tiplog_py/trace/format.py:57–61,97–104`.
`convert()` checks final outputs, metadata and counts against the input, but then opens
`<output>.partial` with `w+b`. Given input `source.mdt.partial` and output `source.mdt`, the
preflight allows the command and the writer truncates/renames the source. The isolated 16-byte
valid-input demonstration left the input path absent. Separately, `measure(input, output=input)`
successfully replaced its BinaryFILE input with approximately 1.7 KB of JSON.

This can destroy a costly local input through a permitted CLI invocation. It does not imply that
the accepted Nasdaq input was damaged. Evidence: [Python probes](second_pass/python/probes.json),
reproduction script `second_pass/python/probe_python_second_pass.py`.

**Proposed remedy:** validate the complete write set before opening anything, including temporary
paths and generated tables; use uniquely owned temporary files and preserve the input in both modes.
Existing-file identity checks should include symlinks/hardlinks. Include second-writer construction
in cleanup handling. **Acceptance:** input/final/temp aliases, primary-final/secondary-temp aliases,
and failure to initialize writer two preserve every source/preexisting artifact; ordinary dual
conversion still produces valid repeatable traces. Only the two source-loss cases were executed;
cross-writer and hardlink variants remain proposed checks.

#### AUD-015 — A torn append defeats the process journal's recovery promise

**Location:** `py/tiplog_py/exp/run.py:49–54,61–81`, especially line 72; pending-marker replay near line 402.
The pending marker contains all rows before publication, but recovery parses every existing JSONL
line before deduplicating. A partial last object raises `JSONDecodeError` immediately. The executed
fixture retained a complete first row, an incomplete final row and the intact authoritative marker;
recovery failed and the marker remained pending. `fsync()` after appending does not prevent an
interruption or failed write during the append.

An expensive interrupted campaign can therefore require manual repair despite having sufficient
journal information. No accepted current file was found torn. Evidence: `pending_journal_torn_final_line`
in [probes.json](second_pass/python/probes.json).

**Proposed remedy:** immutable per-process segments with manifest publication, or explicit recovery
of an incomplete final record from the owned pending marker. Preserve evidence and reject interior
committed corruption. **Acceptance:** fault injection at byte boundaries of multirow publication,
partial UTF-8/JSON tokens, write exceptions and resume yield each observation exactly once; corrupt
earlier committed rows are reported. Avoid loading the entire append file solely to recover its tail.

#### AUD-016 — PAD handling makes independent retention preparation quadratic

**Location:** `py/tiplog_py/exp/oracle.py:121–157`, especially `positions[index:] += padding` at line 146.
Each PAD updates the entire remaining NumPy suffix: O(N × PAD_count), which becomes O(N²) when
wraps grow with input length. A valid 64-byte ring with 24-byte records gives 1,999 PADs and
3,998,000 element updates for 4,000 records, versus 31,999 PADs and **1,023,968,000** updates for
64,000 records: 16× input causes 256× suffix work. Diagnostic medians were 0.0071 s and 0.8695 s;
these are active-host diagnostics, not controlled project performance claims.

Evidence: [oracle_scaling.json](second_pass/python/oracle_scaling.json) and
`second_pass/python/probe_oracle_scaling.py`. This affects small-retention/long-input preparation,
not the C++ publish hot path; the fixture does not establish a problem in the frozen large-capacity campaign.

**Proposed remedy:** accumulate PAD deltas and prefix-sum once, preserving oracle independence.
**Acceptance:** scalar whole-item retention equivalence across many wraps, correct PAD/tail positions,
and O(N + PAD_count) structural update work. Prefer work counts over narrow timing thresholds.

#### AUD-017 — Aligned record size needs more than the oracle's u16 field

**Location:** `py/tiplog_py/exp/oracle.py:19–20,89–96`; `py/tiplog_py/exp/synthetic.py:63–69,102`.
The format accepts u16 payload lengths up to 65,535, but align8(16 + payload_length) reaches
65,552. The independent index also stores that aligned size in u16. Traces with payloads
65,513 and 65,535 passed Python and C++ readers, then failed `TraceIndex` with `OverflowError`;
65,512 succeeded. The synthetic generator likewise accepts a 65,535-byte mixture then fails
assigning its row. Evidence: `valid_trace_payload_boundary` and `synthetic_max_payload` in
[probes.json](second_pass/python/probes.json).

The accepted ITCH/empirical payloads are small, so this does not invalidate those measurements.
**Proposed remedy:** use at least u32 for aligned size and bump the cache/parser schema, rebuilding
old caches. **Acceptance:** trace/synthetic boundaries 65,512/65,513/65,535 agree with C++ format
acceptance and correct retention/digests at an adequate capacity; old caches rebuild explicitly.

#### AUD-018 — Configured T2 duration is overwritten during aggregation

**Location:** `py/tiplog_py/exp/matrix.py:108–113`; `py/tiplog_py/exp/run.py:239–240,522–528`;
`py/tiplog_py/analysis/summarize.py:163–176`.
The matrix supplies its configured backlog as `market_seconds`; aggregation replaces it with literal
10. A 20-second single-reader cohort with 20 billion CPU ns consequently reports **2 CPU
seconds/market second instead of 1**. Writer amortization also consumes the overwritten duration.
Evidence: `t2_configurable_backlog` in [probes.json](second_pass/python/probes.json).

**The frozen P6 matrix uses 10 seconds and is unaffected.**
**Proposed remedy:** preserve the declared duration and check constituent reader/workload agreement.
**Acceptance:** complete groups at 1/10/20/60 seconds produce correct replay and writer rates;
mixed-duration groups fail, and comparison identities cannot silently mix durations.

#### AUD-019 — Missing measurement controls default to success in lightweight acceptance

**Location:** `py/tiplog_py/exp/audit.py:42–68`, especially line 57.
`row.get('measurement_command_ok', True)` treats absent control evidence as verified. A supplied
cohort with a saved warm-up, ten distinct measured process identities and oracle fields, but no
command-validation field, returns `passed` and `measurement_commands_valid=true`.
The helper also cannot detect an entirely absent configuration without an expected plan.
Evidence: `acceptance_without_measured_commands` in [probes.json](second_pass/python/probes.json).

**Scope qualification:** the final campaign separately invokes the stronger
`scripts/check_p6_experiments.py`, which checks plan/requests/processes/commands and exact coverage.
This reproduction does not bypass that gate. **Proposed remedy:** require explicit true control
evidence and accept an expected manifest, or clearly label the result as a limited supplied-row audit.
**Acceptance:** absent/false/null controls fail; explicit controls pass; a supplied expected manifest
detects missing configurations and duplicate/wrong repetition labels.

#### AUD-020 — Auto's boundary-block overcount can cause avoidable scans

**Location:** `src/tiplog/index/index.cpp:370–385`; `src/tiplog/engine/engine.cpp:216–225`.
The estimator counts every entry in an overlapping block even when most precede the requested
checkpoint. Reproduction: 1,023 old A postings, 4,000 B postings, then one A posting; replay starts
after the old A records. With ordinary default block size and Auto fraction, the estimate is
**1,024 candidates although only one posting is in range**. Auto selects Scan and fetches
**4,001 records / 64,016 bytes** before delivering it; explicit Indexed fetches **one / 16 bytes**.
Evidence: [fresh-source probe log](second_pass/core/probe_fresh.log).

This is a demonstrated limitation of the deliberately conservative metadata estimate, not an output
correctness violation or a universal 4,001× speed claim. It particularly affects sparse recent ranges
in formerly busy partitions. **Proposed remedy:** count in-range deltas in first/last overlapping
blocks, retaining full-block counts for interiors, if avoided scans justify the extra planning cost.
**Acceptance:** partial/expired boundary blocks, first=last block, exact lower/upper boundaries and
empty ranges; preserve mode equivalence and measure planning overhead before changing policy.

#### AUD-021 — Reentrant observer preparation corrupts topic IDs

**Location:** `src/tiplog/topics/registry.cpp:155,226–231`; public observer API in `registry.hpp:42,107`.
An observer's guarded `prepare()` calls `intern("r/s/inner")` while the outer operation interns
`r/s/outer`. Both transactions use stale reserved TopicId 3/local ID 1. The outer `intern()` and
`find(outer)` return 3, but `get(3).path` is `r/s/inner`; `all_topics()` contains duplicate IDs.
Evidence: [observer log](second_pass/core/observer_reentrancy.log) and its source beside it.

This requires a custom implementation of the exposed observer API. Built-in compiled subscriptions
do not reenter, so ordinary engine/CLI use is unaffected; no no-reentrancy precondition was found.
**Proposed remedy:** a mutation guard spanning prepare/commit, or an internal-only observer contract.
**Acceptance:** nested mutation is rejected before changing state; outer success/rollback remains
consistent whether the observer catches or propagates the rejection; verify path↔ID round trips,
unique IDs/local IDs, partition counts and subscription filters.

#### AUD-022 — Final output failures are not consistently reflected in tool exit status

**Location:** `tools/tiplog_bench/main.cpp:876–887`; `tools/tiplog_layout/worked_example.cpp:246–260`;
`tests/layout/layout_cc5.cpp:394–402`.
Writing to `/dev/full` gives exit 0 and no stderr for a prefill/memory-only benchmark, the worked
example and CC-5 summary output. Buffered final output is not reliably flushed/closed and checked
before success. A valid benchmark replay request correctly returns 1 because that path flushes;
later memory/allocator output is still after that flush. This distinction was explicitly tested.

Fresh-build evidence: [confirmation.json](second_pass/layout_tools/fresh_release/confirmation.json)
and the per-command JSON files in that directory. An automation trusting exit status can accept
missing evidence after disk-full or another I/O failure; no current result is asserted lost.
**Proposed remedy:** flush/check final streams, and close/check owned output files, before success.
**Acceptance:** valid files parse and contain all expected records; `/dev/full` fails nonzero in
all affected output modes, retaining the valid-request control case.

#### AUD-023 — Custom mixture counts can wrap and silently alter generated traffic

**Location:** `tools/tiplog_bench/main.cpp:281–299,436–438`, especially unchecked addition at line 294.
Two equal counts of 9,223,372,036,854,775,809 each fit u64 individually, but their sum wraps to 2.
The cumulative array becomes nonmonotone and no longer represents the intended distribution.
In this fixture both cumulative values exceed every queried draw (0 or 1), so the demonstration
establishes silent workload skew without requiring a search-precondition violation.
The tool exits 0/status ok and generates only 12-byte payloads: 100 records produce `head_pos=3200`.
Replacing both counts with 1 preserves the intended equal distribution and bounded RNG range,
but produces both payload lengths and `head_pos=5568` with the same seed.

Evidence: `bench_overflow_mix.json`, `bench_equal_mix.json` and outputs under
`second_pass/layout_tools/fresh_release/`. The checked-in empirical mix is not shown to overflow.
**Proposed remedy:** check `count > UINT64_MAX - total` before accumulation and validate every mix
row before generation; align the contract with `publish_bench`, which already checks overflow.
**Acceptance:** overflow fails before publishing; valid equal/skewed distributions remain deterministic;
maximum valid totals are handled safely.

#### AUD-024 — Simulator recording mode emits a nonfinite JSON token

**Location:** `tools/tiplog_sim/main.cpp:24–31,99,185–192,252–253`.
`--backend recording --auto-max-index-fraction nan` succeeds and emits
`"auto_max_index_fraction":nan`, which is invalid JSON. The Engine constructor validates this
option, but the recording backend constructs no Engine and bypasses that check.
Evidence: `recording_nan_json.json` under `second_pass/layout_tools/fresh_release/`.

**Proposed remedy:** validate finite [0,1] fractions during shared CLI parsing and serialize only
finite JSON numbers. **Acceptance:** NaN/infinity/out-of-range inputs fail consistently for both
backends; endpoints 0 and 1 produce strictly parseable JSON.

#### AUD-025 — Quiescence verification selects a process log by glob, not accepted attempt

**Location:** `scripts/check_p7_runtime_quiescence.py:62–63`.
The checker uses `next(parent.glob("round-NN-*.process-audit.jsonl"))`. Retried rounds retain
multiple attempts; directory iteration order does not bind a log to the accepted round. In a
synthetic 11-round retry history, the accepted attempt has 10 seconds of foreign CPU use and an
older attempt is quiet. The checker chooses the other log, reports 0 seconds and returns **passed**.
The fixture adapts to filesystem iteration order; no checker code was patched.

Evidence: [probe-quiescence.log](second_pass/root/probe-quiescence.log),
[reproduction](second_pass/root/probe_quiescence.py). The current saved runtime directory has one
process-audit log per round, so this does not establish a bad historical acceptance.
**Proposed remedy:** load the accepted status record, use its explicit `process_audit` path and
verify its recorded identity; reject ambiguous/unbound evidence. **Acceptance:** a quiet rejected
attempt plus a noisy accepted attempt fails regardless of filenames/creation order, and the inverse
passes; missing or changed accepted logs fail.

#### AUD-026 — Current derived artifacts no longer satisfy the frozen evidence contract

**Location:** `results/derived/tip-summary.json`, `tip-statistics.csv`, `tip-outcomes.csv`;
identities in `results/p7/p6-figure-extension-baseline.json` and `results/p8/acceptance-evidence.json`;
enforcement in `scripts/check_core_closeout.py:242–259,272–276,779–781`.
The current closeout invocation returns **failed with 9 checks**. Three derived hashes differ
from the accepted baseline; several failures are repeated/dependent checks of those same differences,
not nine independent defects. The current files' 2026-10-26 06:44 IST modification times precede this
second pass. Their identities and the checker output were recorded without changing them.

There is also a concrete metadata discrepancy, not just a hash difference. For
`M1/k1/zipf0.8/N4194304/Quad-pad0`, the persisted summary reports **0 observed noise annotations,
0 flagged, 15 unknown**. Reconstructing that same cohort through the current analyzer and saved
frequency sidecar yields **15 observed, 15 flagged, 0 unknown**. Evidence:
[probe-saved-noise.json](second_pass/root/probe-saved-noise.json) and
[its read-only reproduction](second_pass/root/probe_saved_noise.py).

This means the currently packaged derived analysis is not the frozen accepted analysis and omits
available noise qualification for at least that cohort. It does **not** prove wrong replay outputs,
altered raw timings or incorrect plotted medians. The producing invocation/root cause and full
semantic diff remain unverified; do not attribute the change to a person/session from timestamps alone.

**Proposed remedy:** preserve/hash the divergent files first, identify their generating context,
then reconstruct in an isolated output tree using all frozen sidecars. Compare numerical values,
noise annotations and provenance separately. Record any accepted regeneration and new identities
as an explicit remediation phase; do not make the gate pass by blindly replacing expected hashes.
**Acceptance:** the intended current closeout passes, all expected noise annotations are retained,
raw measurements remain unchanged, and report/figure source identities refer to the reviewed output.

### 16.4 Additional review observations and performance opportunities

These are **inspection-based observations**, not additional reproduced defects. They remain in the
report so approval can cover the whole review without inflating the confirmed-finding count.

| Item | Evidence / consequence | Suggested disposition |
|---|---|---|
| OBS-01: exception classification | `tools/tiplog_bench/main.cpp:843–874`: timed/untimed replay disagreement throws `logic_error`, but the broad catch emits `invalid_config`; allocation/unexpected exceptions take the same route. No actual replay disagreement was found. The independent expected-outcome audit rejects unexpected outcomes. | Separate validation/runtime failures from known invalid configurations; propose an injected-failure test before changing status schemas. |
| OBS-02: M3 setup/resident memory | `bench/micro/index_bench.cpp:231–239,272–274` constructs all four B indexes before filtering. Build-only chronological pairs and position lists remain resident. At 32,817,244 postings, these reference arrays alone account for at least ~788 MB decimal before spare capacity; four minimum posting pools add ~525 MB. | Profile selected-arm setup/RSS; filter before construction and release build-only data if needed. Existing hot-loop claims and explicit index-memory counters are not disproved by this observation. |
| OBS-03: inert CLI option | `tools/tiplog_bench/main.cpp:63,86–88` stores `--measure-prefill` but does not use it; prefill timing is unconditional. | Remove or define/test the option; low-impact interface cleanup. |
| OBS-04: end-to-end optimizer resources | `tools/tiplog_layout/main.cpp:393–397` and runtime frontend `:505–509` cap entries per curve, while retaining all curves. `model.cpp:273–283` prepares incidence data before solver caps. Aggregate input/prepare memory is not bounded by the solver work/time limit. | Consider explicit total input/curve/preparation budgets for untrusted or very large jobs. Preparation is explicitly excluded from reported solver time (`results_layout.md:370–385`), so this is not a timing-contract violation. |
| OBS-05: automated enforcement | No CI configuration is present. Existing local suites pass while the newly demonstrated failures remain. Audit probes/checker negative tests are not automatically part of `check_all.sh`. | Adopt approved regressions and a deterministic, data-independent CI subset. Keep full-data evidence verification separate and explicit. This is a delivery/testing gap, not a new product feature requirement. |
| Existing unnumbered dual-output reliability limitation | First report §9 already notes that writer one can finish before writer two fails, leaving one final trace. Writer-two construction also precedes the converter's cleanup `try`. | Carry into AUD-014's write-set/ownership work; define multi-artifact publication semantics. Do not count it again as a new discovery. |

No new ordinary ring/index/merge or exact-layout result mismatch was demonstrated. Extra per-batch
kernel allocations, complete trace validation before a record-count limit, fixed-host CPU controls,
and the lack of networking/persistence/concurrent readers were checked against the declared scope.
They are not automatically defects. The first pass's rejected ForceEvict asymptotic hypothesis remains
rejected. A new merge kernel, WAL, network service or concurrency layer is not required to complete Tier B.

### 16.5 The single feature worth adding: work-budgeted replay and tail polling

**Recommendation F-01: add an optional deterministic inspection-work budget to Replay/Tail polls.**
The current `max` limits delivered matches, not work spent finding them. In an executed 16 MiB-ring
fixture with a busy partition and an exact subscription matching nothing, **one `next_batch(1)`
inspects 1,000,000 records / 16,000,000 bytes and delivers zero** before returning Done. Indexed also
visits 1,000,000 postings. The result was reproduced in Scan, Indexed and Auto; see
[probe_fresh.log](second_pass/core/probe_fresh.log). Work is finite under ring capacity, but callers
cannot choose a useful per-poll work bound. On a shared single-threaded loop, publishing and other
consumers must wait for that call to finish.

This feature directly improves the project's central replay/retention behavior without expanding it
into a different system. Preserve the output limit and add an optional cap on inspected bytes,
records or postings, plus an explicit cooperative-stop result/checkpoint. A deterministic work cap
fits reproducibility better than a deadline alone; cancellation/deadlines can be considered later.
ReplayWork telemetry already provides a useful accounting foundation. This is a proposed enhancement,
not a claim that the existing documented output-limit contract is violated.

**Proposed acceptance contract:**

- A poll respects its inspection cap, with at most a clearly documented single-record allowance.
- Empty-match polls make monotone resumable progress. For the same captured range while its history
  remains retained, repeated bounded polls produce the current unlimited output with no skips/duplicates.
- PAD, eviction between polls, all kernels, exact output-budget boundaries and `max=0` are covered;
  expiry is checked before touching overwritten data.
- The existing API/Q7 behavior remains unchanged when no work cap is supplied. With a cap, define
  intermediate checkpoints/statuses explicitly: Scan and Indexed do different physical work, so
  identical per-call checkpoints cannot simply be assumed. Require eventual output equivalence while
  history remains retained, safe progress, and explicit expiry under the new contract. Different
  cooperative stop points can legitimately lead to different expiry outcomes when publication
  interleaves between polls; do not promise identical outcomes for every such schedule.

Estimated effort **M–L**, with semantic/API risk greater than the small correctness fixes. Implement
after the data-safety and test-oracle repairs, not as a prerequisite for approving this audit.

### 16.6 Consolidated remediation order for approval

| Batch | Items | Reviewable outcome / validation |
|---|---|---|
| 0 | Preserve/reconcile AUD-026 | Retain divergent artifacts, identify semantic changes and sidecar resolution, produce a reviewed current analysis with coherent identities; current closeout passes without hiding historical evidence |
| 1 | AUD-003, AUD-014, AUD-015 | Adopt negative checker tests; preserve sources/outputs; recover torn-tail process publication exactly once; targeted regressions plus affected full suites |
| 2 | AUD-001, AUD-002 | Decide topic bounds/matching strategy and remove quadratic observer dedupe; existing red specifications plus randomized/runtime/fuzz regression checks |
| 3 | AUD-016, AUD-017, AUD-018, AUD-019, AUD-022, AUD-023, AUD-025 | Linear oracle padding, valid-size/cache support, duration-correct T2, explicit controls, truthful I/O exits, checked mix counts and accepted-attempt evidence binding |
| 4 | AUD-020, AUD-021, AUD-024; prior AUD-004/005/006/007/008/009/010/011/012/013 decisions | Profile the Auto estimate change; guard observer mutation; consistent finite JSON configuration; complete previously proposed tests/dependency/docs decisions |
| 5 | Approved observations and F-01 | Take only agreed resource/setup/API changes; define bounded-poll semantics before coding, benchmark separately under the declared quiet-host protocol |

Prioritization is about dependencies and impact, not permission to change source now. Any engine or
evidence change must be recorded as a new remediation phase, preserving the historical P6/P7/P8
acceptance records. Fresh controlled timings are needed only for performance claims or policy
decisions; deterministic correctness/work-count checks can run during ordinary development.

### 16.7 Report errata and remaining limits

- **Report correction:** §4 R-ITCH-1 says `terminator ⇒ incomplete`; read **missing terminator ⇒
  incomplete**. Both implementations and tests already behave correctly. The C++ walker's missing
  byte-offset diagnostics fit the existing AUD-005 diagnostic scope; no duplicate finding is added.
- The initial report's no-functional-defect statement applies to its inspected/reproduced paths.
  This pass adds a public custom-observer counterexample (AUD-021) and data-tooling counterexamples;
  ordinary engine output equivalence still passed.
- Quiet-host P6/P7 timings, 30-minute fuzz gates, full-day Python counting, full-day repeat conversion,
  and the entire million-row P7 study were not rerun in this pass. Existing evidence is cited as
  historical, not relabelled newly executed. No new dependency/advisory lookup was performed;
  AUD-007 retains its first-pass evidence rather than a claim of current advisory completeness.
- The full P6 saved-output re-audit and current closeout were executed and their failures retained,
  as reported above. The earlier §15 blockers for that re-audit are therefore superseded by these
  concrete second-pass results; the rest of §15 remains qualified as stated.
- Root cause/full semantic extent of AUD-026 and unexecuted hardlink/cross-writer/fault-injection
  variants remain explicit investigation items for approved remediation. No production fixes,
  source commits, deployment, data reacquisition or new feature implementation were performed.

## 17. Approved remediation closeout — 2026-10-26

The user approved the audit plan and instructed implementation to stop after the fixes, before
**F-01, work-budgeted replay/tail polling**. That approved remediation is complete: **AUD-001–AUD-026
are closed, and OBS-01–OBS-05 are resolved**. The original findings above remain unchanged as the
historical audit record; this section supersedes their open implementation status and the
pre-remediation "nothing fixed" statements. It does not claim that an audit can prove the absence
of every possible future defect.

The [remediation report](../docs/report/REMEDIATION.md) records implementation decisions,
compatibility changes and limitations. The separate [current-source acceptance](remediation/acceptance.json)
and [passing verifier result](remediation/checks.json) bind the corrected tree to new evidence.
The existing P1–P8 phase gates and P8 acceptance records retain their original hashes. They continue
to describe the original implementation and its performance measurements.

### 17.1 Findings closure register

| Finding | Status | Resolution / evidence |
|---|---|---|
| AUD-001 | Closed | Shared 4,096-byte / 128-segment topic limits reject before mutation in Registry/subscriptions; C++ and Python trace/oracle paths agree. Exact limits and rollback covered. [Core](remediation/core.md), [Python](remediation/python.md), [tools](remediation/tools.md). |
| AUD-002 | Closed | Hash-based observer and ancestor deduplication preserves deterministic notification order and preparation-before-commit. Fanout/overlapping-root regression and local diagnostic scaling checked. [Core](remediation/core.md). |
| AUD-003 | Closed | Four negative checker controls are part of normal CTest. All three vacuous Ring/Index/Engine checker mutations are killed. [Mutation evidence](remediation/core/mutation-summary.json). |
| AUD-004 | Closed | Differential schedules favor useful retained/live readers while retaining expiry and rejection cases; payloads include nonuniform bytes. New complete 108M-operation campaign passed. [Summary](remediation/core/final-validation/summary.json). |
| AUD-005 | Closed | All 14 symbol-bearing ITCH types validate blank fields with typed absolute-offset errors; C++ framing diagnostics are also chunk-independent. [Python](remediation/python.md), [tools](remediation/tools.md). |
| AUD-006 | Closed | Repository-anchored test/figure provenance paths; all 225 package tests pass from `py/` as well as root. [JUnit](remediation/python-from-py.xml). |
| AUD-007 | Closed | pytest updated to 9.0.3; all 15 project pins checked against current advisories, with no reported vulnerabilities. [Advisory snapshot](remediation/pip-audit.json). |
| AUD-008 | Closed by API decision | O(1) `Ring::at` explicitly requires a proven retained boundary. New `at_checked` walks retained boundaries for untrusted locators and rejects forged interior headers. [Contract/tests](remediation/core.md). |
| AUD-009 | Closed | Recorded SHA-256 is verified before acquisition-manifest replacement, including reacquisition. Mismatch preserves old manifest/download evidence. Three mocked controls pass; no new Nasdaq acquisition claimed. [Python](remediation/python.md). |
| AUD-010 | Closed | Hash-locked CPython 3.14/Linux x86_64 project/tool wheels; pinned hash-verified GoogleTest archive is default, including old caches unless system use is explicitly opted into. [Locks and build decisions](../docs/report/REMEDIATION.md). |
| AUD-011 | Closed | Architecture now matches actual exceptions, diagnostic invariant behavior and pressure-policy handling of undersized pools; current checks and historical measurements are distinguished. [Architecture](../docs/plan/ARCHITECTURE.md), [remediation report](../docs/report/REMEDIATION.md). |
| AUD-012 | Closed | Fuzzer fixed fixtures run once/process, compilation is lazy and full invariant recounts are periodic/final; per-operation output/retention oracle remains. Separate final mutation smokes pass. [Core](remediation/core.md). |
| AUD-013 | Closed by resource decision | Temporary dictionary-duplicate views borrow immutable input bytes instead of copying path strings. Per-path limits apply; no arbitrary aggregate dictionary cap introduced. [Tools](remediation/tools.md). |
| AUD-014 | Closed | Full write-set path/inode/ancestor preflight, unique owned temporaries, staged bundles and handled-error rollback preserve sources and old outputs. Includes constructor/finish/rename/metadata faults and symlink/hardlink cases. [Python](remediation/python.md). |
| AUD-015 | Closed | Journal boundaries and exact authoritative row sequencing support every-byte torn-tail recovery. Valid-JSON altered/extra/reordered rows and interior corruption reject without discarding unrelated data. [Python](remediation/python.md), [independent review closure](remediation/core/review-confirmation.json). |
| AUD-016 | Closed | Oracle PAD processing uses deltas and one prefix sum; independent scalar and structural linear-work controls pass. [Python](remediation/python.md). |
| AUD-017 | Closed | Aligned record sizes use u32; parser-version-1 caches rebuild as version 2. Full u16 payload boundaries agree across independent index and C++ validation. [Python](remediation/python.md). |
| AUD-018 | Closed | T2 preserves configured duration and checks shared constituent identity. Version-2 group IDs include duration/source/workload; independent auditor explicitly supports historical version 1. [Report](../docs/report/REMEDIATION.md). |
| AUD-019 | Closed | Measurement control evidence must be explicitly true; exact repetition labels and optional expected-manifest coverage are checked. Limited supplied-row audits label their scope. [Python](remediation/python.md). |
| AUD-020 | Closed | Exact partial-block counts improve Auto's existing decision rule. The original sparse recent-range reproduction now reads one record via Indexed instead of Scan's 4,001, with equivalent output/checkpoint. [Core](remediation/core.md). |
| AUD-021 | Closed | Registry guards the entire observer mutation transaction. Nested intern/observe reject before mutation; callback reads/reset, rollback and subsequent operations remain valid. [Core](remediation/core.md). |
| AUD-022 | Closed | Final stream flush/close failures produce nonzero exits across affected benchmark/layout/evidence tools. `/dev/full` and valid-file controls are in normal CLI regressions. [Tools](remediation/tools.md). |
| AUD-023 | Closed | Shared strict payload-mixture parsing validates every row and checks u64 cumulative overflow before publication. Valid distributions remain deterministic. [Tools](remediation/tools.md). |
| AUD-024 | Closed | Finite `[0,1]` Auto fractions validate before simulator backend selection; recording mode cannot emit NaN/infinity. [Tools](remediation/tools.md). |
| AUD-025 | Closed | Quiescence verification binds the exact accepted status/acceptance/log identities and every consumed eligibility field. Ten script controls pass; historical 11-round quiescence remains valid. [Evidence](remediation/historical-quiescence.json). |
| AUD-026 | Closed | Isolated reconstruction exactly reproduced all four frozen derived hashes. Divergent copies retained; accepted canonical files restored. Complete semantic diff and original raw-file hashes verified; reporting root/output controls added. [Reconstruction](remediation/reconcile-baseline.json), [semantic diff](remediation/reconcile-semantic.json), [raw identities](remediation/tools/frozen-p6-measurements.json). |

### 17.2 Additional observations resolved

- **OBS-01:** benchmark expected configuration rejections remain distinct from `validation_failure`
  and `runtime_error`. Unexpected internal failures exit nonzero and cannot validate as an expected
  rejection. A final integration regression in explicit Indexed packed-cursor rejection was caught,
  fixed with narrow untimed request validation, and verified by the full Python/CLI suites.
- **OBS-02:** M3 filters before preparing input, constructs only selected block sizes, avoids opening
  the trace for a no-match filter, and releases build-only chronological/reference arrays.
- **OBS-03:** `--measure-prefill` is a documented compatibility alias; prefill remains always measured.
- **OBS-04:** aggregate frontend defaults are 128 MiB input, 2M curve entries, 200M preparation-work
  units and 2M memberships per prepared case. The library defaults to 100M preparation-work units
  per call. All 32 frozen CASE and 24 curve batches fit. These bound logical work/storage, not exact RSS.
- **OBS-05:** normal local checks include script regressions; CI covers four builds, Python, dependency
  advisories and bounded fuzz smokes. The local equivalent passed; no hosted CI execution is claimed.

### 17.3 Final executed validation

| Check | Result |
|---|---|
| Configure/build and full CTest in Debug, Release, ASan/UBSan and fuzz presets | **205/205 passed in each preset**; zero failures/errors/skips. Final sanitizer tests use leak detection outside tracing. |
| Complete Python package and script tests from root | **259 passed**: 225 package cases and 34 script cases, including 17 negative controls for the new evidence verifier. |
| Complete Python package tests from `py/` | **225 passed**, zero skips. |
| Independent differential campaign, fresh binaries/generator | **90M Release + 18M sanitized operations passed**, all nine supported mode/kernel pairs; identical digests within each seed-count cohort. |
| Three mutation-fuzzer smokes | **10,000 runs each**, ASan/UBSan/leak checking enabled; no crashes; original seed corpora unchanged. |
| Layout CC-5 | **10,000 cases each** in Release and sanitizer builds; zero mismatches; complete summaries equal the historical accepted result. |
| Worked example | Release and sanitizer outputs byte-identical to the frozen snapshot. |
| Independent experiment-auditor self-test | Both T2 identity versions pass; 13 distinct tampering controls reject. Temporary synthetic evidence only. |
| Dependency validation | Hash-locked installation, `pip check` clean, all 15 project pins without reported advisories. |
| Original raw measurement identities | **5,364/5,364 unchanged**, totaling **4,105,957,437 bytes**. |
| Current-source closeout | **Passed, zero failures**. Rehashes current source/documents, evidence, retained originals and raw files; rejects missing/stale execution evidence. |

Exact command arguments, environments, exits, input identities and log hashes are in
[command records](remediation/checks/). [JUnit and the current acceptance inventory](remediation/acceptance.json)
identify the final runs. The [full functional report](remediation/core/final-validation/summary.json)
binds 21 executed jobs, source snapshots and binary hashes. Supporting focused runs are described
in [core](remediation/core.md), [Python](remediation/python.md) and [tools](remediation/tools.md) notes;
their overlapping test counts are not added to the final totals.

### 17.4 Evidence reconciliation and retained limits

The divergent analysis differed only in noise-counter fields: **6,542 configurations**, all
74,660 statistics rows and 6,542 of 6,759 outcome rows. All other summary and CSV values were
identical; paired ratios were already identical. Reconstruction recovered **125,700 observed
noise annotations, 74,935 flagged**, and exactly matched the four frozen hashes before canonical
restoration. No expected historical hash was rewritten to accept the divergence. The original
invocation producing the divergent files remains unknown.

Historical binaries and the original audit text were retained and checked against identities
recorded at remediation start. The original 2026-10-25 measurement manifest supplies the raw-file
SHA-256 values; P8 inventories that manifest by path/size rather than its own SHA-256. This provenance
limit is recorded in the raw-identity report instead of claiming a stronger chain.

No fresh controlled P6/P7 throughput/latency campaign, full-day conversion/counting campaign,
entire P7 study or 30-minute fuzz gate was run for the corrected source. Local fanout/planning/harness
timings remain diagnostics. The original performance tables remain historical. The final functional
matrix above is newly executed evidence, including leak checking, rather than reuse of old passes.

Multi-output publication restores bundles on handled failures; several filesystem renames do not
provide whole-bundle power-loss atomicity. The documented input/resource limits intentionally reject
previously accepted excessive inputs. Cache/group schema changes and legacy support are described
in the remediation report. No networking, durability, concurrent-reader layer or other roadmap
feature was added.

**Stopped after the approved fixes. F-01 remains deferred.** The replay/tail implementation and
public engine API files are byte-identical to the remediation-start baseline; see
[scope confirmation](remediation/core/scope-confirmation.json). The single recommended next feature
remains work-budgeted replay/tail polling, to be considered in its separate subsequent phase.
