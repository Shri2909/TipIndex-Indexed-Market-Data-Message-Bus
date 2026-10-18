# PROGRESS — workflow state and evidence

This file records authorization. It **cannot grant** it. Approval is recorded here only after you give it.

| Field | Value |
|---|---|
| Plan version | **v1.1** (2026-10-17), superseding proposed v1.0 |
| Approval state | **APPROVED** by the user on 2026-10-17 with the proposed Tier B defaults; approval explicitly does not start implementation |
| Authorized phase | **P1–P5 jointly authorized** by the user on 2026-10-17; P0–P4 complete, P5 executing. |
| Workflow step | 4 of 5: execute P1 → P2 → P3 → P4 → P5, passing each gate before automatic continuation; stop after P5 |
| Selected tier | **Tier B**; effort estimates remain provisional and weekly availability is unspecified |
| Approved defaults | 2019-12-30 Nasdaq data only; no privileged benchmark-setting changes; proposed writable repository setup preserving managed/read-only metadata |

## Approval record — 2026-10-17 (Asia/Calcutta)

The user explicitly stated:

> I approve plan v1.1 with the proposed Tier B defaults: 2019-12-30 Nasdaq data only, no privileged benchmark-setting changes, and the proposed writable repository setup.
>
> Approval does not start implementation. Wait for my separate phase-start instruction.

At that approval boundary, P0–P8 remained unstarted and no phase was authorized. The separate P0 start and its evidence are recorded below. Tier C and roadmap execution remain outside this approval. Recording approval changes workflow status only, not scope, acceptance criteria or implementation evidence.

## Completed tasks (historical planning stage)

- Inspected the workspace: only `MASTER_PROJECT_PROMPT.md`; no `PROJECT_PLAN.md`; not a git repository. Nothing was modified or overwritten.
- Read the reference article PDF in full (12 pages; tree figures extracted at native resolution).
- Researched sources and wrote the evidence ledger (RESEARCH.md, 48 entries).
- Wrote the planning package: INDEX, RESEARCH, STUDY_PLAN, ARCHITECTURE, IMPLEMENTATION_PLAN, VALIDATION_PLAN, PROGRESS.

## Historical planning checks (environment and metadata only)

| Check | Result |
|---|---|
| Hardware and OS | i5-1235U hybrid (P-cores 0–3, E-cores 4–11), 14 GiB RAM, NVMe ext4 with 30 GB free, Ubuntu 26.04, kernel 7.0.0-38 |
| Toolchain | GCC 15.2, Clang 21.1.8 (ASan/UBSan/libFuzzer runtimes present), CMake 4.4, no ninja; googletest 1.17.0 installed; valgrind 3.26 |
| perf | perf 7.0.14; `perf_event_paranoid=4`; `perf stat -e cycles,instructions -- true` and `-e task-clock` both **failed** for an unprivileged user |
| Python | 3.11.9; numpy 2.4.6 and matplotlib 3.11.1 present; pandas, scipy, pyarrow, hypothesis absent |
| Nasdaq samples | Directory listing, HEAD (sizes, Last-Modified, Accept-Ranges), first 128 KiB of `12302019.NASDAQ_ITCH50.gz` and `S120825-v50.txt.gz` decoded: framing verified; gzip ISIZE read |
| Binance | HEAD probes of 5 files; one CHECKSUM file read |
| Links | Planned citations checked with HTTP (DOIs return 403 to scripts; cited as identifiers) |

**Materials downloaded for reading:** spec PDFs, papers, and the 128 KiB probes were stored in the session scratch directory, **not** in this repository.

**At the planning-stage boundary:** no dataset download, build, code, test, benchmark or installation had occurred. The following Phase 0 section is the subsequent tooling execution record.

## Unresolved issues

- Tier and DEC-2–DEC-4 defaults are approved (see INDEX); actual weekly availability remains unspecified and estimates will be calibrated after authorized P0/P1.
- Q-02 to Q-07 are resolved by measurements in P1, P5, P6, and R3 (IMPLEMENTATION_PLAN §9).

## Next action

Finish P5 acceptance under the joint P1–P5 authorization. P0–P4 gates passed; P5 implementation, release/sanitizer tests and RC3 passed. Complete all-mode CC2, final integrated F3 and isolated M1/M1-touch/M2 pilot, then stop. No P6–P8, Tier C or roadmap work is authorized.

## Log

| Date (UTC+5:30) | Event |
|---|---|
| 2026-10-16 | Plan v1.0 written; approval requested |
| 2026-10-17 | User requested rerun/research refresh and amendments to existing files. Reviewed all seven docs, checked primary sources, performed narrow read-only environment checks, and proposed v1.1; implementation remains unauthorized. |
| 2026-10-17 | User explicitly approved v1.1 with Tier B defaults and explicitly instructed that implementation wait for a separate phase-start message. Recorded approval and synchronized current-status wording only; authorized phase remains None. |
| 2026-10-17 | User separately instructed “Start Phase 0 of approved plan v1.1, Tier B” and authorized P0 only. Read master/INDEX/PROGRESS and P0-relevant planning/review requirements, performed read-only preflight, and began P0.1–P0.6. |
| 2026-10-17 | P0.1–P0.6 completed; all four preset configure/build/CTest checks and Python checks passed, along with fallback and Clang plumbing checks. P0 gate passed; stopped before P1. |
| 2026-10-17 | User requested a single reusable P2–P5 implementation prompt without repeated permission requests. Prepared PHASES_2_TO_5_IMPLEMENTATION_PROMPT.md, explicitly including P1 if incomplete because P2 depends on its artifacts, and linked it in INDEX. This request was prompt preparation only; P0 remains complete and no later phase was started or authorized by storing the template. |
| 2026-10-17 | User requested making P1 an explicit part of the combined prompt. Revised the template to PHASES_1_TO_5_IMPLEMENTATION_PROMPT.md with full P1–P5 scope and automatic continuation after passed gates. This is a prompt revision, not execution; current phase authorization remains unchanged. |
| 2026-10-17 | User separately instructed execution of P1–P5 as one jointly authorized sequence, including the full approved Nasdaq download, all checks and automatic continuation after each passed gate. P0 was verified/reused. P6–P8, Tier C and roadmap execution remain outside this authorization. |

## Phase 0 execution — 2026-10-17 (Asia/Kolkata)

**Authorization:** the user separately instructed “Start Phase 0 of approved plan v1.1, Tier B” and “This message authorizes Phase 0 only.” The prior explicit approval is preserved above. Read `MASTER_PROJECT_PROMPT`, INDEX and this progress record first, then `IMPLEMENTATION_EXECUTION_PROMPT` and the P0-relevant research/study/architecture/implementation/validation/review/inventory/problem requirements. P0 has no mandatory study item. ST-11/12/13 and V01–V39 remain scoped to their later phases.

**Preflight:** [read-only snapshot](../../results/p0/preflight.json) records original Markdown hashes, writable workspace, tool versions, topology, disk and the initial failed plain Git discovery. The workspace had ≈31.45 GB free. Managed `.git` was empty, mode 0555, and unwritable. No existing source, build files, tests or `AGENTS.md` were found. Master-prompt SHA-256 remains `89c0fe2ab7be8304d5cf9b9b8da07ee554efffc9c75596822fdd4f353f7d3067`.

### Completed tasks and artifacts

| Task | Status | Concrete result |
|---|---|---|
| P0.1 | Complete | Initialized supported explicit Git directory `.tiplog-git/`, with original workspace as worktree; [git wrapper](../../scripts/git.sh), [.gitignore](../../.gitignore), [README](../../README.md). Managed `.git` remains empty/0555. No commit made; HEAD is unborn and all project files are untracked, explicitly recorded as dirty. |
| P0.2 | Complete | [CMakeLists](../../CMakeLists.txt), [presets](../../CMakePresets.json), [dependencies](../../cmake/deps.cmake): C++20/strict project warnings; Unix Makefiles; GCC debug/release, Clang sanitizer/fuzz; immutable Benchmark 1.9.5 and exact system GTest 1.17.0 with pinned fallback. |
| P0.3 | Complete | `/usr/bin/python3` validated as CPython 3.14.4; isolated `.venv` created, binary dependencies installed locally; [complete package pins](../../py/requirements.txt), [interpreter manifest](../../results/env/p0-python.json), `pip check`, NumPy/import/Agg-render smoke passed. |
| P0.4 | Complete | [env_capture.sh](../../scripts/env_capture.sh) / [Python implementation](../../scripts/env_capture.py), [machine environment JSON](../../results/env/p0-environment.json). CPU2 belongs to `cpu_core`, siblings 2–3, taskset affinity `[2]`, sched_getcpu start/end 2. Frequency samples saved. No privileged setting changes. Counter fallback explicit. |
| P0.5 | Complete | [check_all.sh](../../scripts/check_all.sh) / [runner](../../scripts/check_all.py); `Plumbing.Cxx20AndGoogleTest` and [Python plumbing test](../../py/tests/test_smoke.py). All four presets plus Python pass; exact arguments/logs retained. |
| P0.6 | Complete | This authorization/task/traceability/gate/handoff record; current-status navigation synchronized; [RESEARCH §7](RESEARCH.md#7-phase-0-just-in-time-source-inspection--2026-10-17) records actual original-source inspection. |

### Finding → implementation → executed evidence

| Finding/source | Decision / task | Code file or symbol | Required check | Executed evidence/status |
|---|---|---|---|---|
| Managed read-only metadata; approved DEC-4; original Git `--git-dir/--work-tree` documentation | Preserve `.git`, supported separate metadata; P0.1 | `scripts/git.sh`; `.gitignore` | Repository discovery through explicit layout, ignore rules, unchanged master/managed metadata | [preflight](../../results/p0/preflight.json), [final artifact checks](../../results/p0/artifact-checks.json): passed |
| Finding #54, S42/S48, DD-15; pinned original dependency CMake files | Keep approved versions and immutable content; P0.2 | `cmake/deps.cmake`, `TIPLOG_FORCE_FETCH_GTEST` | Build every preset and actual fallback, retain license attribution | [successful gate summary](../../results/p0/20261017T042909.444760Z/summary.json), [supplemental commands](../../results/p0/supplemental-checks.json), [source revisions/hashes](../../results/p0/build-sources.md): passed |
| S45, DD-17, VALIDATION §4; official Clang compile/link and fuzzer-no-link guidance | Real sanitizer plumbing, no fake engine/fuzzer; P0.2/P0.5 | `CMakePresets.json`, `tiplog::build_options`, `tiplog::fuzzer_options`, `tests/unit/smoke_test.cpp` | ASan/UBSan/fuzz instrumented build and CTest, leak detection enabled | [ASan CTest](../../results/p0/20261017T042909.444760Z/asan-ubsan-ctest.log), [fuzz-preset CTest](../../results/p0/20261017T042909.444760Z/fuzz-ctest.log): 1/1 each passed, no diagnostics. Timed F1–F3 not applicable to P0. |
| Finding #54, RESEARCH §6.4; Python/PyPI original metadata; DD-15 | Validate explicit interpreter and fresh isolation; P0.3 | `py/requirements.txt`, `py/tests/test_smoke.py::test_python_plumbing` | Dependency consistency, import + numerical operation + headless PNG | [install log](../../results/p0/python-install-network.log), [manifest](../../results/env/p0-python.json), [pytest](../../results/p0/20261017T042909.444760Z/python-pytest.log): passed; 15 project packages frozen, bootstrap pip separately recorded |
| Finding #49, S41/S47, DD-18; original hybrid PMU note S56 | Verify P-core and capture state, avoid assumed isolation; P0.4 | `scripts/env_capture.py::main`, `PIN_DIAGNOSTIC`, `build_info` | JSON parse; affinity + sched_getcpu; frequency sampling; environment fields | [machine capture](../../results/env/p0-environment.json), [artifact checks](../../results/p0/artifact-checks.json): passed. SMT sibling idle is not verified; no noise claim. |
| Finding #50, S32/S56, approved DEC-2, VALIDATION §5.6 | Actual probes determine counter access; no system changes; P0.4 | `scripts/env_capture.py` profiling/controls fields | Retain probe outcomes; wall/getrusage + later reduced-case simulated Cachegrind fallback | [machine capture](../../results/env/p0-environment.json): cycles, instructions and task-clock denied (exit 1), paranoia 4; counters null, fallback selected. Control/ack measurement and Cachegrind runs deferred to applicable later experiments. |
| Finding #52, reproducibility protocol | Record actual commands/configuration/outcomes; P0.5/P0.6 | `scripts/check_all.py::main`, `CMakePresets.json` | All four configure/build/test pipelines + Python; extra compiler plumbing | [14-command gate](../../results/p0/20261017T042909.444760Z/commands.jsonl) all exit 0; [six supplemental commands](../../results/p0/supplemental-checks.json) all exit 0. This does not establish later RC-1/RC-2/RC-3 engine criteria. |
| Other source/invariant findings (#1–48, #51/#53 where engine/optimizer/bench-specific; S49–S55/S57–S61 algorithms/roadmap) | Deferred to named phases, no scope expansion | No dummy implementation | V01–V49/M/T/L and later gates | Not run / not applicable to P0; prior source-reading limitations preserved |

### Commands actually executed and outcomes

All commands ran in the workspace unless noted. Logs retain exact expanded paths/argv and results.

- `git --git-dir="$PWD/.tiplog-git" --work-tree="$PWD" init --initial-branch=main`; `scripts/git.sh rev-parse --show-toplevel`; `scripts/git.sh status --short`; `scripts/git.sh check-ignore build/example data/raw/example data/traces/example results/raw/example .venv/example .tiplog-git/config`: passed. Managed `.git` was not initialized, deleted or chmodded.
- `/usr/bin/python3 -m venv .venv`; `.venv/bin/python -m pip install --disable-pip-version-check --retries 0 --timeout 30 --only-binary=:all: numpy==2.3.5 matplotlib==3.11.0 pytest==9.0.2` with project-local `PIP_CACHE_DIR`: passed outside the network-restricted sandbox. Initial restricted install failed with no matching distribution/index access; retained [initial log](../../results/p0/python-install.log). `.venv/bin/python -m pip freeze > py/requirements.txt` and `pip check`: passed. No global package install.
- Verified pinned dependency downloads and hashes: actual URLs/commands/results in [build-source notes](../../results/p0/build-sources.md). Initial restricted curl DNS failed; approved retry outside the restriction passed. No dataset downloaded.
- First `scripts/check_all.sh`: debug/release configure/build/CTest passed; ASan configuration stopped when Benchmark's regex feature probe hit LeakSanitizer's ptrace restriction. [Failed summary](../../results/p0/20261017T042756.293032Z/summary.json), [LSan diagnostic](../../results/p0/sanitizer-sandbox-failure.log). This was a failed run, not a regex implementation defect.
- `cmake --fresh --preset asan-ubsan`: rerun outside sandbox tracing, passed ([log](../../results/p0/asan-unsandboxed-configure.log)). `scripts/check_all.sh` rerun outside tracing: **14/14 commands passed** ([summary](../../results/p0/20261017T042909.444760Z/summary.json)). CTest 1/1 for debug/release/asan-ubsan/fuzz; pytest 1/1; pip check clean. ASAN_OPTIONS=`detect_leaks=1:abort_on_error=1`; UBSAN_OPTIONS=`print_stacktrace=1:halt_on_error=1` in sanitizer test presets. No sanitizer check disabled.
- `cmake --preset release -B build/gtest-fallback -DTIPLOG_FORCE_FETCH_GTEST=ON`, `cmake --build build/gtest-fallback --parallel 4`, `ctest --test-dir build/gtest-fallback --output-on-failure --no-tests=error`: all passed, actual pinned fallback built. Same three steps using `-B build/release-clang -DCMAKE_CXX_COMPILER=clang++`: all passed. [Exact commands/results](../../results/p0/supplemental-checks.json).
- `scripts/env_capture.sh --preset release > results/env/p0-environment.json`: passed. `bash -n`, Python compilation, JSON parsing, out-of-directory script invocation, preserve/ignore/frozen-package and Markdown local-link checks: [artifact checks](../../results/p0/artifact-checks.json). Environment capture retains perf failures and missing optional `core_type` sysfs fields; P-core verification uses available hybrid PMU membership and topology.

### Phase 0 gate — passed

| Completion criterion | Met/unmet | Evidence |
|---|---|---|
| Approved plan + separate P0 instruction + DEC-4 | **Met** | Prior approval and subsequent explicit P0 authorization above |
| P0.1 writable repository, ignores, README; preserve original work | **Met** | `.tiplog-git` wrapper + preflight/final preservation checks |
| P0.2 every required preset configures and builds | **Met** | All four preset configure/build commands exit 0; fallback and Clang extra checks passed |
| P0.3 explicit validated interpreter, local venv, compatible frozen versions | **Met** | Interpreter manifest, frozen 15-package snapshot, pip check and scientific imports/rendering |
| P0.4 environment JSON saved, P-core pin/frequency checks, counter decision recorded | **Met** | Machine JSON; pin_verified=true, CPU2 start/end, frequency fields; DEC-2 fallback |
| P0.5 CTest and pytest pass; plumbing only | **Met** | 1/1 CTest each preset; 1/1 pytest; no engine, data or workload benchmark |
| P0.6 actual authorization/tasks/traceability/results/limitations/handoff saved | **Met** | This section and linked source/evidence artifacts |

**Limitations / continuation:** no P0 blocker remains. LeakSanitizer needs execution outside the sandbox's ptrace restriction in this environment; preserved presets keep leak detection enabled. Fresh dependency downloads need network access outside the restricted shell; verified archives are cached only under ignored build storage. Requirements are an environment snapshot, not a portable hashed wheel lock. Git has no commit/SHA yet; the [artifact manifest](../../results/p0/artifact-manifest.json) identifies checked project sources/build commands by hash. CPU governor/turbo/SMT stay as observed; sibling idleness and benchmark noise are not established. Hardware/software perf counters are unavailable in the captured context; no counter, latency, performance or physical-I/O claims are made. Exact data sizes/counts/skew, engine tests, timed fuzzing, optimizer checks, P6 pilots and all later gates are unrun. P0 evidence does not imply RC/CC core completion.

The next available phase is **P1 — data acquisition, conversion, characterization**, on a separate explicit start instruction. Scope remains approved v1.1/Tier B. No amendment was needed and no later phase began. Actual task/review/debug time was not separately instrumented; automated command durations are saved, and the 5 h estimate is not presented as measured effort.

## Joint P1–P5 authorization and live execution — 2026-10-17

The user explicitly instructed: “Execute Phases 1, 2, 3, 4 and 5 of approved plan v1.1, Tier B, as one jointly authorized sequence,” including the full 2019-12-30 Nasdaq acquisition and automatic continuation after each passed gate. This supersedes separate phase-start messages **within P1–P5 only**. `PHASES_1_TO_5_IMPLEMENTATION_PROMPT.md` was read completely; its stored template alone grants no authorization. P6–P8, Tier C and roadmap execution remain outside scope.

P0 implementation/evidence was verified and reused: original code/build/test hashes match the saved artifact manifest; only INDEX/PROGRESS changed since the P0 snapshot due later prompt preparation, which is preserved. P0 gate/artifact-check JSON both record passed. [P1 preflight](../../results/p1/preflight.json) records current hashes, ≈30.96 GB free disk, and unchanged empty/0555 managed `.git`.

| Phase | Current state | Gate evidence / next action |
|---|---|---|
| P1 | **Complete; gate passed** | [Phase gate](../../results/p1/phase-gate.json); acquisition, V01–V05/CC-6, RC-2, F1/F2 and real L1 figures all passed |
| P2 | **Complete; gate passed** | [Phase gate](../../results/p2/phase-gate.json); V06–V09/V38, independent oracle/driver, release and sanitizer checks passed |
| P3 | **In progress** | Starts automatically after complete P2 gate; bounded ring and scan replay |
| P4 | Pending | Starts automatically after complete P3 gate |
| P5 | Pending | Starts automatically after complete P4 gate; stop after P5 acceptance |

Acquisition initial HEAD confirms 3,524,013,057 B and range support. A 1 MiB probe returned HTTP206 with exact Content-Range. The slow single transfer was explicitly stopped with its partial bytes preserved, then restarted as at most 16 verified range requests; completed chunks resume by identity/size/header, final assembly is gzip-validated and SHA-256 hashed. Actual command/status/header logs are in `results/p1/`; until completion no valid full dataset, checksum, counts or phase gate is asserted. Source bytes and derived message-level files remain under ignored `data/raw/` and `data/traces/`.

P1 implementation checks so far: 14 independent C++ reader/walker tests pass in release and ASan/UBSan; Python golden/routing/trace/CLI checks pass, including synthetic cross-language compatibility. F1 and the implemented F2 are running their full 1,800-second gates on separate permitted E-cores; final statistics are pending. Synthetic figures are only a generator smoke check, not F01–F05 real-data evidence. A provisional 2-GiB conversion attempt on an insufficient compressed prefix correctly failed with gzip EOF and removed incomplete outputs; its failed log is retained and is **not** an RK-01 throughput decision. The accepted pilot will use the complete validated input and run in isolation from fuzzing/conversion work.

**First real input measurements:** full download/gzip validation passed; [manifest](../../data/manifest.json) SHA-256 `ef03df46a27e6bda4dead017f84c2e3979df7211f02c7868b51d53fceb99c689`. Independent C++ and `gzip | wc -c` report **8,251,407,909 decompressed bytes**, **268,744,780 messages**, **7,713,918,349 payload bytes**, **18 observed types**, **8,907 locates**, and **0 timestamp inversions**. The BinaryFILE zero-length terminator is **absent**: framing is complete and gzip integrity passes, but source session completeness remains explicitly `incomplete=true` as required by V02. This is not silently repaired or labeled session-complete. [C++ consistency checks](../../results/p1/cpp-full-day-consistency.json). Python CC-6/skew and repeat conversion remain pending.

The first F1/F2 invocations exited 0 with millions of executions but a large host wall-clock discontinuity inflated their reported wall duration (≈6,566 s versus ≈910 s monotonic). They are retained as successful command runs, **not accepted timed gates**. Fresh runs use `scripts/run_fuzz_gate.py` and require ≥1,800 monotonic seconds per target, continuing successful short attempts if clocks jump. No fuzz threshold or sanitizer setting was reduced.

**Accepted P1 timed fuzz checks:** [F1](../../results/p1/F1-trace-segmented-gate-20261017T142028.416744Z.json) passed **1,801.8978 monotonic seconds / 53,139,553 executions**; [F2](../../results/p1/F2-framing-real-segmented-gate-20261017T142151.850263Z.json) passed **1,801.7637 seconds / 2,043,899 executions**. Each has 15 successful exit-0 segments with final statistics and no sanitizer diagnostic. Required real F2 prefix bytes are local/ignored; tracked corpora remain synthetic. [Independent recheck](../../results/p1/fuzz-gate-verified.json) verifies log/stat/timing totals, unchanged target/runner hashes and saved corpus hashes. Earlier interrupted/synthetic-only attempts stay superseded and unaccepted. [Protocol/source details](../../results/p1/fuzz-segmented-notes.md).

The final metadata/CCDF corrections retain **69/69 Python tests passed**, [exact command/result](../../results/p1/python-final-metadata-check-20261017T142615.823401Z.json). [P1 traceability](../../results/p1/traceability.md) and [independent audit](../../results/p1/final-review.md) map completed checks and pending data work. P1 itself remains **in progress** until the isolated RK-01 pilot, complete Python/C++ reconciliation, both repeat trace hashes and real F01–F05 outputs pass. Current [data gate](../../results/p1/data-gate.json) saves that continuation point. No P2 implementation has begun.

**RK-01 resolved:** the isolated CPU2 first-2-GiB pilot scanned **2,147,483,668 B / 69,406,749 messages in 294.553 s** internally, after both fuzz gates and the required settling interval. Projecting against the measured full-stream byte count gives **1,131.778 s (18.86 min)**, below the approved 2,700 s switch threshold even with full L1 aggregate updates and both hierarchy writers. [Decision and exact boundary](../../results/p1/rk01-converter-decision.json), [fresh environment](../../results/env/p1-converter-pilot.json). Retain Python; no C++ converter fallback is needed. This is a conversion diagnostic, not an engine benchmark. Complete conversion/counting and repeat-hash checks remain pending.

## Phase 1 completed gate and Phase 2 handoff — 2026-10-17

**P1 is complete.** The joint P1–P5 instruction remains the authorization; no additional phase-start message is required. [Machine-readable phase gate](../../results/p1/phase-gate.json) marks every P1 criterion met; [implementation manifest](../../results/p1/implementation-manifest.json) identifies the checked sources before P2. The earlier live entries above are historical snapshots and their pending items are superseded by this gate.

| Task | Status | Implementation and executed evidence |
|---|---|---|
| P1.1 | **Met** | Resumable approved acquisition, range/header verification, `gzip -t`, SHA-256 and [manifest](../../data/manifest.json); [exact range commands](../../results/p1/range-acquisition-commands.json) |
| P1.2 | **Met** | Complete decompressed byte/count measurements, explicit absent terminator and zero inversions; [C++/gzip consistency](../../results/p1/cpp-full-day-consistency.json); isolated [RK-01 decision](../../results/p1/rk01-converter-decision.json) retains Python |
| P1.3 | **Met** | `py/tiplog_py/itch/` routing/conversion and `trace/format.py`; both hierarchies preserve payload/order, explicit 09:30–10:00 window, checked source identity and deterministic traces |
| P1.4 | **Met** | V01–V03: independently hand-built golden bytes for all 23 supported types, framing/routing/inversion/CRC failures; final Python suite **69/69 passed** |
| P1.5 | **Met** | `ItchWalker`/`tiplog_walk` independent from Python helpers; [CC-6](../../results/p1/cc6-reconciliation.json) exactly reconciles all 18 observed type keys and 8,907 locate keys |
| P1.6 | **Met** | Checked C++ `trace::Reader`, production `tiplog_trace_check`, V05; **14/14 C++ tests passed in release and ASan/UBSan**, with leak checks retained. [F1/F2 verified gates](../../results/p1/fuzz-gate-verified.json) exceed 1,800 monotonic seconds each |
| P1.7 | **Met** | Full-day/window topic, H-flat, partition, family, run/rate and complexity CSVs in `results/data/`; actual F01–F05 PNG/PDF in `results/figures/`; [41/41 real artifact checks](../../results/p1/real-data-artifact-checks.json), plus [visual review](../../results/p1/figure-visual-review.json) |

**Executed real-data commands:** [data gate](../../results/p1/data-gate.json) links nine exact command records/logs for the isolated pilot, full combined conversion/counting, repeat conversion, CC-6, both C++ trace reads, figure regeneration and artifact check. Full conversion took 867.479 s internally (873.927 s command); repeat command took 397.266 s. These are execution/conversion diagnostics, not engine performance results. Earlier failed prefix, clock-discontinuous and interrupted fuzz attempts remain preserved and excluded from acceptance.

**Measured artifacts:** full stream **268,744,780 messages / 8,251,407,909 B / 7,713,918,349 payload B**; **111,997 topics / 8,907 partitions / 8,906 symbols**. Routing found **zero unknown locates, symbol mismatches or directory conflicts**. Full-day symbol message Gini **0.77837**; top 1% carries **21.7987%** of messages. Trees have **4–21 nodes**; raw/effective per-workload class histograms are saved, without an exact-solver coverage claim. The chosen window has **32,817,244 records / 947,677,397 payload B / 62,964 topics**.

**RC-2 met for both hierarchies:** H-spec SHA-256 `6062bdb96ec8354ecf650cdfb979574530b2120aa06047fa48d14a78e5936f70`; H-flat `89cc31ac0c8907cf9552e85a60f04a221f4f2f9bc012769d0ab4de96376cbba2`. Each matches its independent full-source repeat. Both C++ reads agree on counts and ordered payload digest. [Source→decision/task→symbol→validation→actual evidence](../../results/p1/traceability.md), [original-source reading limits](../../results/p1/python-sources.md), [independent C++ sources](../../results/p1/cpp-sources.md), [final review](../../results/p1/final-review.md).

**Limitations:** the intact gzip lacks the BinaryFILE terminator, so `incomplete=true` is retained; session completeness is unproved. Raw input, traces, real fuzz seeds and payload-derived F2 logs remain local/ignored; [privacy audit](../../results/p1/privacy-audit.json) records the checks and their limits. Hardware counters remain unavailable; no privileged setting changed. No Git commit exists; checked source hashes are saved. No P1 blocker remains. Continue automatically with **P2**, then P3–P5 after their gates. P6–P8, Tier C and roadmap work remain outside authorization.

## Phase 2 completed gate and Phase 3 handoff — 2026-10-18

**P2.1–P2.5 complete; all P2 completion criteria met.** [Phase gate](../../results/p2/phase-gate.json) and [implementation snapshot](../../results/p2/implementation-manifest.json) record the passed dependency and actual commands. Final release and ASan/UBSan each pass **52/52 tests**, including **37 P2 cases**: 16 registry/subscription, 16 independent oracle and 5 driver tests. Final builds are warning-free; leak detection remains enabled and no sanitizer report occurred. Three initial nodiscard warnings in rejection tests were corrected with explicit discarded results; the affected builds/tests were rerun and earlier logs retained.

- **P2.1 / V06/V38 met:** `topics::Registry` creates ancestors/partitions and dense u16 local IDs, with preflight rejection before ancestor/filter mutation. Actual local ID 65535 and representation exhaustion are tested.
- **P2.2 / V07/V08 met:** `subs::normalize/compile`, partition filters, wide terms and future-topic observers; independent randomized segment matching and observer allocation/lifetime cases pass.
- **P2.3 / V09 met:** `tests/ref/ScanOracle` shares only value types, matches raw path strings and independently models division/modulo DATA/PAD retention. Hand-computed wrap, conservative expiry, exact-final-budget, future/max0/zero-output and equal-event cases pass.
- **P2.4/P2.5 met:** engine-neutral `driver::drive_trace` models seeded budgets/pauses/cadence. Sparse trace IDs are resolved through dictionary paths. Real-trace smoke processed 10,000 events and saved aggregate digests; the P2 CLI explicitly labels its recording backend. Production driver/CLI do not link the test reference.

[Topics source→decision→symbol→check ledger](../../results/p2/topics-sources.md), [oracle/driver ledger](../../results/p2/oracle-driver-sources.md), [independent audit](../../results/p2/review.md). Published Jane Street hierarchy/order statements remain separate from independent filter/hook/retention algorithms. Primary sections/revisions and limited reading are recorded. Review fixed NUL-path consistency, a retained identity-anchor lifetime corner and quadratic capacity growth before the gate; regression tests passed.

No P2 blocker remains. CC-2 differential campaigns, production ring/scan replay and timed F3 belong to **P3**, now automatically started under joint authorization. No later benchmark, index, optional extension or optimizer gate is implied by P2.

## Phase 3 live acceptance checks — 2026-10-18

P3 ring/checkpoints and Scan Engine/Replay are implemented; P4/P5 implementation has not begun. Final builds are warning-free. [Release](../../results/p3/release-tests-final-20261018T034022.019438Z.json) and [ASan/UBSan](../../results/p3/sanitizer-tests-final-20261018T034025.130173Z.json) each passed **86/86 tests**, including 17 ring and 17 engine cases; leak checks remain enabled. The retained-tail-PAD resume regression, 8-B checkpoint storage, generic 16-B DATA, aliases, rejected state and lifetime rules are covered.

**CC-2 passed:** [release](../../results/p3/differential-release-20261018T034047.389885Z.json) **1,000 seeds × 10,000 operations = 10,000,000**; [sanitizer](../../results/p3/differential-sanitizer-20261018T034107.454243Z.json) **200 × 10,000 = 2,000,000**. Scan has no active merge kernel in P3. Schedules compare raw paths/payloads, ordering, retention, exact statuses/checkpoints/errors and invariants against the independent oracle.

Seven synthetic F3 seeds passed smoke checks. The required [F3 timed gate](../../results/p3/F3-scan-segmented-gate-20261018T034111.719594Z.json) is **running, not passed**. [Live state and exact resume command](../../results/p3/live-state.json), [built source freeze](../../results/p3/implementation-freeze.json), [fuzz grammar/source map](../../results/p3/fuzz-sources.md), [ring sources](../../results/p3/ring-sources.md), [engine sources](../../results/p3/engine-sources.md), [independent review](../../results/p3/review.md). No P3 completion is claimed until ≥1,800 confirmed monotonic seconds and final statistics verify cleanly. Then finish its gate and continue P4 automatically.

## Historical research refresh evidence — 2026-10-17

The entries below record the research and prompt-preparation state **before the subsequent approval recorded above**. Their prior approval-status wording is historical, not the current workflow state.

- Preserved the original planning content apart from targeted corrections; appended a dated section to RESEARCH, ARCHITECTURE, STUDY_PLAN, IMPLEMENTATION_PLAN and VALIDATION_PLAN. Added REVIEW_2026-10-17.md as navigation and rationale.
- Rechecked newer primary merge/layout/drift/storage sources, recent Jane Street/Aeron engineering articles and official specifications/tool documentation; S49–S61 distinguish inspected sections, metadata-only discoveries, and inaccessible full text. No claim that all 2026 research was exhaustively searched.
- Analytical audit found replay-checkpoint inconsistency, late-seal FIFO ordering, ring-size/PAD constraints and representation bounds. These now have **planned** V35–V39 checks; none were run.
- Current read-only metadata: Python 3.14.4, numpy 2.3.5, matplotlib 3.11.0, pytest 9.0.2, pandas 3.0.3; compiler/perf versions unchanged; paranoid=4. Historical 2026-10-16 table above is preserved as the old record, not silently relabeled current.
- `.git` directory is present but `git rev-parse --show-toplevel` reports no repository. No metadata was initialized or changed. About 31.4 GB free disk at inspection.
- Only planning files were edited. No source code, prototypes, build scripts, application tests, optimizer runs, benchmarks, installations, privileged settings, or full datasets were created/executed.
- Documentation-only checks passed: eight files' Markdown fences/local links, 61 unique source IDs with no unresolved references, version/authorization consistency, changed-file scope, and unchanged master-prompt hash. Outcomes are recorded in REVIEW_2026-10-17.md; these do not satisfy implementation gates.
- At the user's request, consolidated the existing research/concepts into FINDINGS_TO_IMPLEMENTATION.md, linked from INDEX. This is an inventory of v1.1, not a scope change or implementation authorization; the earlier eight-file check remains the dated refresh check. The inventory follow-up checked nine planning documents for Markdown fences/prose links, confirmed its INDEX/PROGRESS references and consecutive 1–54 core entries, and found no unresolved inventory source IDs. The master prompt hash is unchanged. These are documentation checks, not implementation tests.
- At the user's request, consolidated the existing Tier B problem statement, benchmark settings, expected outputs and acceptance criteria into PROBLEM_STATEMENT_AND_BENCHMARKS.md, linked from INDEX. The candidate-traversal example is an arithmetic illustration, not timing evidence or a new speedup target. This brief preserves scope and authorization state; no project experiment was run.
- At the user's request, prepared IMPLEMENTATION_EXECUTION_PROMPT.md with separate reusable approval and Phase 0 start messages, source-to-code/evidence traceability, bounded just-in-time source verification and later-phase continuation instructions. Independent prompt review corrected the continuation template so P0-specific instructions cannot override a later named phase. Documentation checks passed for eleven prompt/planning files' fences/links, the three separate message templates, unchanged master-prompt hash and preserved approval state. Only the prompt and planning navigation/log were edited; preparing this template does not approve v1.1, select a tier or authorize implementation. Approval remains NOT APPROVED; authorized phase remains None.

## Phase 3 completed gate and Phase 4 handoff — 2026-10-18

**P3.1–P3.5 complete; every P3 criterion met.** [Phase gate](../../results/p3/phase-gate.json) and [checked source manifest](../../results/p3/implementation-manifest.json) identify the accepted implementation. The live entry above is historical and superseded by this gate.

Release and ASan/UBSan each passed **86/86 tests**, including 17 ring and 17 engine cases. CC-2 passed **10,000,000 release operations** and **2,000,000 sanitizer operations**, with independent path/payload/retention/status/checkpoint/error comparisons and invariant checks. Leak detection remained enabled. Final warning-free build and exact command logs are linked from the gate. The production Scan driver also processed 10,000 real trace records and delivered all 10,000 using budget7/cadence3/pause20:4; this is functional validation, not a benchmark.

**F3 passed: 1,801.2918 monotonic seconds, 216,843 executions, 15 exit-0 segments.** [Root verification](../../results/p3/fuzz-gate-verified.json) and [independent review](../../results/p3/review.md) checked terminal statistics, log/binary/runner/corpus hashes, no diagnostics and all 42 frozen source files unchanged. No crash artifact remains. Earlier unrun wording does not describe this final gate.

[Ring traceability](../../results/p3/ring-sources.md), [Engine traceability](../../results/p3/engine-sources.md), [F3 traceability](../../results/p3/fuzz-sources.md). Corrected v1.1 contracts include rejection before mutation, generic 16-B DATA, minimal 8-B PAD, 8-B sparse checkpoints, exclusive representation bounds, completion before expiry, exact-budget More and retained-tail-PAD checkpoint preservation. These are independent algorithms; no unavailable Aria details are claimed.

No P3 blocker remains. **P4 starts automatically** under the joint P1–P5 authorization. The [index integration review](../../results/p3/p4-handoff-review.md) and [independent pressure fixture arithmetic](../../results/p3/p4-pressure-fixture-plan.md) are preparation, not executed P4 evidence. P4 must pass its unit, independent recount, differential and fresh timed indexed F3 gates before P5 begins.

## Phase 4 implementation underway — 2026-10-18

P4 started automatically after the accepted P3 gate. The shared index API and Engine publication integration are being implemented; no P4 acceptance is claimed yet. `index::Index` separates prepared resources from nonallocating commit, retains 32-B SoA metadata and u32 deltas, orders sealed expiry by last position, and exposes independent recounts. Engine configuration preserves the P3 aggregate fields and appends explicit pool policy, indexing and enforced-minimum options.

The root has added an independent [F3 pressure fixture](../../tests/fuzz/pressure_fixture.hpp), alongside the ample-pool random oracle branch. [Planned validation map](../../results/p4/fuzz-plan.md) links the prior hand arithmetic to exact DATA/PAD losses, generation/reuse, common replay expiry and RejectPublish state checks. The source code and fixtures are work in progress: unit/differential/sanitizer/fresh timed indexed F3 checks remain **unrun**.

### P4 checks executed; timed gate pending

[Live evidence and exact continuation](../../results/p4/live-state.json): final warning-free builds, **121/121 release and 121/121 ASan/UBSan tests**, **10M release +2M sanitizer differential operations** passed. Actual Indexed opens:1,520,290/303,957; wide Scan fallbacks:335,905/68,316, reported separately. The declared grammar bound was corrected39→41 before these campaigns. Source code is frozen in the [49-file manifest](../../results/p4/implementation-freeze.json).

The prior1,250-input corpus passed indexed smoke; all9 named seeds, including true pressure/recycling cases, passed again after final golden-payload fixture additions. Fresh [F3 indexed timed gate](../../results/p4/F3-indexed-segmented-gate-20261018T102347.429747Z.json) is **running, not passed**; no P4 completion claim is made. Its dedicated fresh corpus preserves prior corpora while avoiding repeatedly loading all old long inputs during mutation segments.

[Allocator source/method/actual observations](../../results/p4/memory-sources.md) separately measures the required glibc contribution and preserves exact structural recounts. [Real trace Scan/Indexed smoke](../../results/p4/real-driver-mode-comparison.json) publishes10,000 events, delivers the same one AAPL event and completes at the same upper checkpoint; it is functional validation, not performance evidence. Independent review has found no unresolved source defect; its final timed audit remains pending. P5 source implementation still waits for this P4 gate.

**Local source provenance:** snapshot commit `d4e5b8323dd43a77c5d5f97fc46f2be25f5a0006` now exists in the approved writable `.tiplog-git`; managed `.git` remains read-only and untouched. [Revision audit](../../results/p4/source-revision.json) matches all49 frozen source files to that commit. Staging path checks excluded raw/traces/real fuzz seeds/F2 payload logs. Earlier commands retain their historical unborn-HEAD/source-hash provenance; this later snapshot is not substituted as run-time metadata. P5's future pilot will record its actual revision and dirty state. No push/publication occurred.

## Phase 4 completed gate and Phase 5 handoff — 2026-10-18

**P4.1–P4.5 complete; every P4 completion criterion met.** [Authoritative phase gate](../../results/p4/phase-gate.json), [checked source manifest](../../results/p4/implementation-manifest.json), [final independent review](../../results/p4/review.md). Earlier running/pending entries are historical snapshots superseded by this gate.

- **Pool/index:** fixed32-B metadata and separate u32 deltas; free-list/generations, prepared append/nonallocating commit, ordered expiry heap, full/partial seals, lazy cold-open expiry/cadence sweeps and declared pressure policies. V37 checks late partial seals and wide-before-narrow arithmetic.
- **Cursor/replay:** binary block/entry seeks, position/generation safety and k1 indexed replay preserve common completion/expiry/checkpoint rules; dynamic filters are reacquired after topic creation.
- **Accounting:** exact independent slot/recount conservation, heap/list/fixed storage/high-water; [actual supported allocator observations](../../results/p4/memory-sources.md) separately cover the declared process boundary. Generic16/enforced32 sizing and strong rejected-publication state checks pass.
- **Executed checks:** final warning-free builds; **121/121 release and121/121 ASan/UBSan tests**, **10M release +2M sanitizer differential operations**. Effective Indexed opens and wide fallbacks are reported separately.
- **F3 passed:** **1,801.3472 monotonic seconds /81,399 executions /15 exit-0 segments**. [Root terminal verification](../../results/p4/fuzz-gate-verified.json) and independent review verified all log/stat/binary/runner/corpus identities, all49 frozen sources unchanged, no sanitizer report and no failure artifact. Peak RSS717MiB. Corrected indexed-selector seed variants passed independent smoke and were retained in the campaign.

[Source→decision/invariant→task→symbol→validation→executed evidence: Index](../../results/p4/index-sources.md), [Engine](../../results/p4/engine-sources.md), [golden pressure/F3 map](../../results/p4/fuzz-plan.md), [allocator](../../results/p4/memory-sources.md). Published shared-pool observations stay distinct from our independent transactional, expiry and accounting algorithms. No P4 blocker remains.

**P5 starts automatically now** under the joint P1–P5 authorization. Its required kernels, multiparty replay/Auto/Tail, equivalence/differential/sanitizer/fuzz/RC3 checks and M1/M1-touch/M2 harnesses/pilot remain to be completed. [Read-only merge study](../../results/p4/p5-merge-study.md), [Engine/Tail study](../../results/p4/p5-engine-study.md), [benchmark handoff](../../results/p4/p5-benchmark-handoff.md) are preparation, not executed P5 evidence. Stop after P5's accepted gate; P6–P8, Tier C and roadmap work remain outside scope.


## Phase 5 live acceptance checks — 2026-10-18

P5.1–P5.5 implementation is integrated: four independent merge kernels, checked packed keys, multi-partition replay, configurable **uncalibrated** Auto, Tail re-arming, independent Tail reference, deterministic driver/campaigns and M1/M1-touch/M2 harnesses. No P5 completion is claimed before the remaining timed gate and pilot pass.

- Final integrated [release tests](../../results/p5/release-tests-integration-20261018T155700.707669Z.json) and [ASan/UBSan tests](../../results/p5/sanitizer-tests-integration-20261018T155840.807045Z.json) each passed **157/157**. Leak checks remain enabled. Named integrated F3 seeds passed their final smoke check.
- [RC3](../../results/p5/rc3-summary.json) passed **180 functional runs /170 equality checks**: repeated GCC/Clang, Scan/Indexed×4/Auto×4, actual narrow Indexed/Auto, wide Scan fallback, successful replay and nonempty-prefix expiry. [Integrity audit](../../results/p5/rc3-integrity.json) verifies commands, results and source/binary identities.
- [CC2 all configurations](../../results/p5/CC2-full-sequence-20261018T160119.265969Z.json) is **running**: nine configurations per preset, each 1,000×10,000 release or200×10,000 sanitizer operations. All nine release children passed; sanitizer children are in progress. The final cross-mode outcome/digest audit remains pending.
- Fresh [integrated F3](../../results/p5/F3-integrated-segmented-gate-20261018T160110.829382Z.json) is **running**, requiring ≥1,800 confirmed monotonic seconds. [38-file binary source freeze](../../results/p5/fuzz-source-freeze.json), [17 named scenarios](../../results/p5/named-corpus.json). No timed-gate completion is inferred from elapsed wall time.
- [Full-size M1 functional check](../../results/p5/M1-full-pilot-functional-20261018T160201.375404Z.json) passed all15 selected cases, including fully initialized1GiB touches, independent expected hashes and Quad padding variants. This is functional validation, **not timing evidence**. M2 matrix functional verification is in progress after its final build.
- [Pilot runner/method](../../results/p5/pilot-method.md) is prepared and validated. **Timed pilot and reduced simulated Cachegrind remain unrun** until all fuzzing, tests and builds finish, followed by a verified quiescence barrier, final source snapshot and fresh environment/AC/affinity checks. Full campaigns and P6.2 noise/calibration studies remain deferred.

[Engine/Tail traceability](../../results/p5/engine-sources.md), [merge/M1 traceability](../../results/p5/merge-sources.md), [RC3 traceability](../../results/p5/rc3-evidence.md). Primary-source reading boundaries remain explicit. These are independent algorithms; no unavailable Aria details or transferred speedups are claimed. P6–P8, Tier C and roadmap work remain unauthorized.


**P5 CC2 terminal update:** [all18 campaigns](../../results/p5/CC2-all-configurations.json)
passed **90,000,000 release +18,000,000 sanitizer operations**. Each of nine mode/kernel
choices independently met its required seed/operation counts. Canonical aggregate
outputs/outcomes match exactly across modes for each preset; only declared
mode-specific execution counters and elapsed time are excluded. F3 and isolated
pilot acceptance remain pending.
