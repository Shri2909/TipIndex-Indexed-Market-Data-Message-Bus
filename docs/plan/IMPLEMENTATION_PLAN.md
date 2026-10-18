# IMPLEMENTATION PLAN — phases, hours, gates, fallback, roadmap

Plan version **v1.1** · 2026-10-17 · **Approved with Tier B defaults. P0 complete; P1–P5 jointly authorized in dependency order.** The user approved 2019-12-30 Nasdaq data only, no privileged benchmark-setting changes and the proposed writable repository setup. The subsequent joint execution instruction supersedes separate start messages within P1–P5 only; passing each gate permits automatic continuation through P5. P6–P8, Tier C and roadmap work remain outside this authorization. §14 records the amendments to the original estimates/tasks. [Approval and execution record](PROGRESS.md).

---

## 1. Scope tiers and hour budgets

Your weekly hours are unknown (DEC-1), so the four-week core is shown at three budgets. **Effort hours** are estimates for focused engineering work, not measured productivity. The table preserves the v1.0 base breakdown; v1.1 adds a provisional **4–8 h review/correctness allowance** across P3–P7: A ≈66–70 h, B ≈95–99 h, C ≈129–133 h. Tier B therefore needs roughly 24–25 effort h/week. Calibrate after P0/P1 before committing the remaining calendar.

| Tier | Effort (h) | Your hours/week if you implement | Your hours if the agent implements* | Contents |
|---|---:|---:|---:|---|
| **A: Minimum core** | ≈62 | ≈15.5 | ≈28 total (≈7/wk) | ITCH (H-spec, one window); ring; index + pool; StdPQ + BinHeap; scan oracle and differential tests; T1 + T5; optimizer with ENUM + baseline + KM-min/max on ENUM-feasible partitions; worked example; short report |
| **B: Standard core (recommended)** | ≈91 | ≈23 | ≈39 total (≈10/wk) | A + H-flat variant; Loser + Quad kernels; M1-touch, M2, M3; T2, T3; **MASK-DP** with DP=ENUM validation; L3 gap; L5 sensitivity; full report |
| **C: Extended core** | ≈125 | ≈31 | ≈50 total (≈12.5/wk) | B + galloping; T4 open-loop storm; book-consistency validator; L6 drift; H-LS; Binance workload (R7); tagged index entries (R9) |

\* Agent-implemented user hours are a speculative **[S] planning model**, not evidence of a 75% speedup or a promise of delivery. Record actual implementation/review/debugging time after P0/P1. The earlier study/review estimates are retained for comparison; do not choose scope on those savings alone. Calendar time also includes downloads, conversion, fuzzing and benchmark runs. No sudo changes are needed for the default fallback protocol.

**Recommendation: Tier B if the revised 24–25 effort h/week is realistic.** It aims for a measured tip index and a scoped optimizer checked against enumeration. With less time, choose Tier A or revise scope after the first authorized phases; agent assistance is not evidence that the larger tier fits automatically.

**The full project is larger than four weeks.** About **150 h** beyond Tier B for the durable and concurrent system (R1–R4, R6–R7, R9). About **225 h** if the optional network service, power-loss testing, and cross-partition bundling are included (§7). The full system is therefore roughly **240–315 effort hours in total**, about **3–4 months at 20 h/week**.

---

## 2. Dependency graph (core)

```
P0 ─► P1 ─► P2 ─► P3 ─► P4 ─► P5 ─► P6 ─► P8
             │                      ▲
             └────────► P7 ─────────┘     (P7 needs P1 volumes + P2 registry; independent of P3–P6)
```

---

## 3. Core phases

Each phase lists entry criteria, required study (STUDY_PLAN IDs), tasks with hours per tier, verification commands (PLANNED; the authoritative list is VALIDATION_PLAN §11), outputs, and definition of done (DoD). Effort is shown as **A / B / C** hours.

### P0 — Bootstrap and environment (4 / 5 / 5 h)

**Execution status:** P0.1–P0.6 complete and gate passed on 2026-10-17. [Actual commands, source traceability, results and limitations](PROGRESS.md#phase-0-execution--2026-10-17-asiakolkata). Estimates/tasks below are retained; 5 h is not measured elapsed effort. P1 is not authorized.

**Entry:** plan approved; explicit "Start Phase 0"; DEC-4 answered (git init in this folder).

**Study:** none required.

| Task | h | Artifact |
|---|---:|---|
| P0.1 Inspect metadata/write access, then initialize a repository only at a supported writable location; preserve any managed/read-only `.git` directory. Add `.gitignore` (`build/`, `data/raw/`, `data/traces/`, large `results/raw/`), README stub; preserve `MASTER_PROJECT_PROMPT.md` | 0.5 | recorded repository layout |
| P0.2 CMake skeleton (C++20, strict warnings), `CMakePresets.json` (debug, release, asan-ubsan, fuzz); FetchContent pin: Google Benchmark **v1.9.5**; googletest via system 1.17.0 with a pinned FetchContent fallback; Makefiles generator (no ninja) | 2 | `CMakeLists.txt`, `CMakePresets.json`, `cmake/deps.cmake` |
| P0.3 Validate an explicit Python interpreter, create project `.venv`, smoke-check compatible dependencies and freeze versions. Current read-only metadata: Python 3.14.4, numpy 2.3.5, matplotlib 3.11.0, pytest 9.0.2; hypothesis optional. Do not reuse v1.0's different environment as current fact. | 0.5 | interpreter/version manifest and `py/requirements.txt` |
| P0.4 `scripts/env_capture.sh`; verify P-core pinning and frequency sampling; if DEC-2 = yes, check `perf list` event names and `perf stat --control` | 1 | `results/env/*.json` |
| P0.5 `scripts/check_all.sh` + one trivial C++ test and one Python test (plumbing only) | 0.5 | script |
| P0.6 Update PROGRESS | 0.5 | PROGRESS.md |

**Verify (PLANNED):** `scripts/check_all.sh`; `scripts/env_capture.sh`.

**DoD:** every preset configures and builds; ctest and pytest pass; environment JSON saved; counter decision recorded (counters, or the fallback of VALIDATION §5.6).

### P1 — Data acquisition, conversion, characterization (10 / 12 / 12 h)

**Entry:** P0 done; DEC-3 answered; ≥10 GB free disk; network available.

**Study:** ST-01, ST-02.

| Task | h | Artifact |
|---|---:|---|
| P1.1 Fetch `12302019.NASDAQ_ITCH50.gz` (range-resumable); `gzip -t`; SHA-256; `data/manifest.json` | 0.5 + wall | manifest |
| P1.2 Streaming measurement: exact uncompressed bytes; BinaryFILE terminator present?; counts and bytes per type and per locate; timestamp inversions; **converter throughput on the first ~2 GB → RK-01 decision** (Python vs C++ converter) | 2 | `results/data/itch_20191230_counts.json` |
| P1.3 Converter: framing, spec length table, directory, K-by-symbol, market-wide routing, unknown-locate routing, H-spec (+ H-flat in B/C), symbol encoding, time window, trace v1 + `.meta.json`, deterministic output | 4 | `py/tiplog_py/itch/` |
| P1.4 Golden tests V01–V03 | 2 | `py/tests/` |
| P1.5 C++ `tiplog_walk` independent counter + V04 | 1 | tool + check |
| P1.6 C++ trace reader + V05 + fuzz F1 (F2 skeleton) | 1.5 | `src/tiplog/trace/`, `tests/fuzz/` |
| P1.7 L1 characterization → topic-volume CSVs (window and full day); F01–F05; partition \|V\| and b histograms (inform RK-06, RK-07) | 1–2 | `results/data/*_volumes.csv`, figures |

**Verify (PLANNED):** pytest V01–V03; `tiplog_walk` vs converter counts (CC-6); converter run twice → same SHA-256 (RC-2); `ctest -R trace`; fuzz F1 for 30 min.

**DoD:**
- V01–V05 pass and CC-6 holds exactly.
- RC-2 holds.
- F01–F05 are produced by scripts, and the **first real measurements** (sizes, counts, skew) are recorded in PROGRESS.

### P2 — Topics, subscriptions, oracle, driver (7 / 9 / 9 h)

**Entry:** P1.3 trace format and topic dictionary are done.

**Study:** ARCHITECTURE §3, §5.0–5.2.

| Task | h (B) | Artifact |
|---|---:|---|
| P2.1 Topic registry | 2 | `src/tiplog/topics/` |
| P2.2 Subscription normalization and compilation; topic-creation hook; wide terms | 2.5 | `src/tiplog/subs/` |
| P2.3 `ref::ScanOracle` (path-string matching; independent retention model) | 2 | `tests/ref/` |
| P2.4 Deterministic driver (trace → publish; scripted scenarios; seeds) | 1.5 | `tools/tiplog_sim` |
| P2.5 Tests V06–V09 | 1 | `tests/unit/` |

Tier A trims P2.2 (no hook optimizations) and P2.4 (minimal driver).

**Verify (PLANNED):** `ctest --preset release -R "topics|subs|oracle"`; the same in `asan-ubsan`.

**DoD:** V06–V09 pass in both presets.

### P3 — Ring and scan replay (9 / 11 / 11 h)

**Entry:** P2 done.

**Study:** ST-03, ST-04; ST-13 before P3.5.

| Task | h (B) | Artifact |
|---|---:|---|
| P3.1 Ring: header encode/decode, PAD, append/evict, positions, checkpoints | 4 | `src/tiplog/ring/` |
| P3.2 Scan replay; captured upper bound; HistoryExpired/FellBehind | 2 | `src/tiplog/engine/` |
| P3.3 `check_invariants` (INV-R1–R7) | 1 | — |
| P3.4 Tests V10–V14 (+ differential harness) | 3 | `tests/differential/` |
| P3.5 Fuzz F3 (scan mode); asan-ubsan run | 1 | `tests/fuzz/` |

**Verify (PLANNED):** CC-1/CC-2 commands for V10–V14; `taskset -c 4-11 ./build/fuzz/fuzz_engine_ops -max_total_time=1800`.

**DoD:** V10–V14 meet CC-1/CC-2; F3 runs 30 min clean (or every crash is fixed and regressed).

### P4 — Block pool and partition index (9 / 11 / 11 h)

**Entry:** P3 done.

**Study:** ARCHITECTURE §5.5; ST-05 optional.

| Task | h (B) | Artifact |
|---|---:|---|
| P4.1 Block pool (SoA meta + entries, free list, generations) | 2 | `src/tiplog/index/` |
| P4.2 Append/seal/expiry-min-heap reclaim/open-block expiry/sweep/pressure policy; generic-vs-ITCH sizing validation and V37 late-seal regression | 4 + share of v1.1 allowance | — |
| P4.3 Index cursor (gen checks, block chaining, seek); indexed replay for k = 1 | 2 | — |
| P4.4 Memory accounting (live, slack, high-water) + brute-force recount | 1 | — |
| P4.5 Tests V15–V20; F3 indexed mode | 2 | — |

**Verify (PLANNED):** CC-1/CC-2 for V15–V20; F3 for 30 min in indexed mode.

**DoD:** V15–V20 meet CC-1/CC-2; slack recount exact; sizing rule checked on synthetic worst cases.

### P5 — Merge kernels and indexed catch-up (6 / 11 / 14 h)

**Entry:** P4 done.

**Study:** ST-06, ST-08, ST-11; ST-07 for Tier C.

| Task | A | B | C | Artifact |
|---|---:|---:|---:|---|
| P5.1 k-cursor set over partition indexes | 1.5 | 1.5 | 1.5 | `src/tiplog/merge/` |
| P5.2 StdPQ + BinHeap (early-exit replace-top) | 2 | 2 | 2 | — |
| P5.2b Loser tree; Quad heap | — | 3 | 3 | — |
| P5.2c Galloping wrapper (adaptive threshold) | — | — | 3 | — |
| P5.3 Multi-partition indexed replay; Auto (thresholds configurable); `Tail` chaining with re-armed cursors | 1 | 1.5 | 1.5 | — |
| P5.4 Tests V21, V23–V25 (+ V22 in C) | 1 | 2 | 2 | — |
| P5.5 M1 harness (A: minimal); M1-touch + M2 (B/C) | 0.5 | 1 | 1 | `bench/micro/` |

**Verify (PLANNED):** CC-1/CC-2 for V21–V25; `merge_bench` pilot with raw JSON saved.

**DoD:** all kernels produce identical outputs, equal to the oracle; M1 pilot raw data saved; benchmark harness reviewed against VALIDATION §7 (no strawman baselines).

### P6 — Tip experiments, analysis, figures (7 / 13 / 25 h)

**Entry:** P5 done; DEC-2 applied or fallback recorded; P1 traces available.

**Study:** ST-12; ST-14 for Tier C.

| Task | A | B | C | Artifact |
|---|---:|---:|---:|---|
| P6.1 Experiment driver + TOML configs + `runs.jsonl` writer + digest check (CC-4) | 2 | 3 | 3 | `py/tiplog_py/exp/`, `configs/` |
| P6.2 Pilot (CV) and protocol freeze | 1 | 1.5 | 1.5 | pilot notes |
| P6.3 Runs: T1 + T5 (A); + T2, T3, M3 (B); + T4 with HdrHistogram (C) | 2 | 3 | 11 | `results/raw/` |
| P6.3b Book-consistency validator V34 (C) | — | — | 4 | — |
| P6.4 Analysis + bootstrap CIs + figures F06–F13 (+ F19 in C) | 1.5 | 3.5 | 3.5 | `py/tiplog_py/figures/` |
| P6.5 Results summary + claims table + failure counts | 0.5 | 2 | 2 | `docs/report/results_tip.md` |

**Verify (PLANNED):** `.venv/bin/python -m tiplog_py.exp.run configs/T1.toml --reps 10 --cpu 2`; `.venv/bin/python -m tiplog_py.figures.build --all`.

**DoD:** CC-4 holds for every configuration; RC-1 holds; every non-`ok` status is reported; claims table rows point to raw files.

### P7 — Storage-layout optimizer (6 / 13 / 16 h)

**Entry:** P1.7 volume tables and P2 registry. It can run in parallel with P3–P6 when time allows.

**Study:** ST-09; ST-10 optional.

| Task | A | B | C | Artifact |
|---|---:|---:|---:|---|
| P7.1 Model + two independent evaluators | 1.5 | 2 | 2 | `src/tiplog/layout/` |
| P7.2 H-BASE; H-KM with min/max bisection | 1.5 | 2 | 2 | — |
| P7.3 ENUM (Gray code) | 1 | 1.5 | 1.5 | — |
| P7.4 MASK-DP + reconstruction + global γ sweep | — | 3 | 3 | — |
| P7.5 Validation V28, V30–V32 (A); + V29 / CC-5 (B) | 1 | 2 | 2 | `tests/layout/` |
| P7.6 Studies: L2 on ENUM-feasible partitions + L4 (A); broader L2/L3/L5 with **per-workload exact coverage** (B); + L6 and H-LS (C); figures F14–F18 (+ F20) | 1 | 2.5 | 5.5 | `tools/tiplog_layout`, figures and coverage |

**Verify (PLANNED):** `ctest -R layout`; `tiplog_layout … --methods base,km-min,km-max,enum,dp`.

**DoD:**
- V28–V32 pass; CC-5 holds (B/C).
- The worked example matches §6.7 exactly.
- Every reported gap compares an identical objective and feasible set.
- Claims are scoped per ARCHITECTURE §6.9.

### P8 — Report and packaging (4 / 6 / 8 h)

**Entry:** P6 and P7 done.

| Task | h (B) | Artifact |
|---|---:|---|
| P8.1 Technical report (outline §11) | 3.5 | `docs/report/REPORT.md` |
| P8.2 Reproduction guide; final checklist; resume bullets with real numbers | 2 | `docs/report/REPRODUCE.md` |
| P8.3 Final PROGRESS update | 0.5 | PROGRESS.md |

**DoD:** the core completion checklist (§10.1) is fully ticked with links to evidence.

**Per-tier totals:** A = 4+10+7+9+9+6+7+6+4 = **62 h** · B = 5+12+9+11+11+11+13+13+6 = **91 h** · C = 5+12+9+11+11+14+25+16+8 + R7 7 + R9 7 = **125 h**.

---

## 4. Weekly gates (Tier B; weeks counted from "Start Phase 0")

| Week | Planned work (h) | Gate | Evidence required |
|---|---|---|---|
| 1 | P0 (5), P1 (12), P2.1–P2.2 with their tests (≈5.5) ≈ 22.5 | **G1:** data converted and characterized; registry and subscriptions tested | `data/manifest.json`, CC-6, RC-2, F01–F05, V01–V08 green |
| 2 | P2.3–P2.4 + V09 (≈3.5), P3 (11), P4 (11) ≈ 25.5 | **G2:** tip store correct | V09–V20 under CC-1/CC-2; F3 30 min clean in both modes |
| 3 | P5 (11), P7.1–P7.3 + V28/V30–V32 (≈7), P6.1–P6.2 (4.5) ≈ 22.5 | **G3:** kernels verified; exact enumeration validated; pilot noise known | V21–V25; ENUM evaluators agree; CV recorded |
| 4 | P7.4–P7.6 (≈6), P6.3–P6.5 (8.5), P8 (6) ≈ 20.5 | **G4:** results and report | CC-4, CC-5, RC-1; report; checklist |

Passing a gate does **not** authorize the next phase. I report at each phase boundary and wait for your instruction.

**If a gate slips by more than 25%,** I prepare an **amendment** that applies the next items from §5, and wait for your approval before changing scope.

## 5. Fallback cut order (applied only by approved amendment)

1. Tier C items (excluded from B by default).
2. T3 reduced to 2 configurations; M3 dropped.
3. Quad kernel.
4. L5 hierarchy sensitivity.
5. MASK-DP. Keep ENUM; exactness claims are then limited to ENUM-feasible partitions, with the covered fraction reported.
6. Loser tree. Keep StdPQ vs BinHeap.
7. T2. Keep T1 and T5.

**Never cut:** oracle differential tests, sanitizer runs, data checksums, environment capture, failure accounting, and the limitations section.

**Minimum shippable core if badly late** (end of week 3 without P5): ring + index + BinHeap with T1 + T5; optimizer worked example + ENUM on ITCH partitions. Everything else moves to the roadmap with that status recorded.

---

## 6. Repository structure and tooling (planned)

```
/ (this folder)
├── MASTER_PROJECT_PROMPT.md          (existing; preserved)
├── docs/plan/                        (this package)       docs/report/ (P6–P8)
├── CMakeLists.txt  CMakePresets.json  cmake/deps.cmake
├── src/tiplog/{topics,subs,ring,index,merge,engine,trace,layout}/   storage/ (R1+)
├── tools/{tiplog_sim,tiplog_walk,tiplog_layout,tiplog_bench}/
├── tests/{unit,differential,ref,layout,fuzz/{targets,corpus}}/
├── bench/{micro,e2e}/
├── py/tiplog_py/{data,itch,binance,trace,exp,analysis,figures}/   py/tests/
├── configs/ (TOML experiment configs; W0–W3 workloads)
├── scripts/{env_capture.sh,check_all.sh}
├── data/{manifest.json, raw/ (ignored), traces/ (ignored)}
└── results/{env,raw (large ignored),derived,figures}/
```

**Tooling:**
- Compilers: GCC 15.2 (primary), Clang 21.1.8 (sanitizers, fuzzing, cross-compiler check).
- C++20 only; CMake 4.4 (Makefiles).
- googletest 1.17.0; Google Benchmark v1.9.5; optional HdrHistogram_c 0.12.1 after release/commit review and smoke checks (Tier C).
- Explicit validated Python/venv; current refresh sees Python 3.14.4, and compatibility/pins are verified in authorized P0.
- valgrind (Cachegrind fallback); `perf` (DEC-2); `iostat` (R3).

---

## 7. Roadmap beyond the core — NOT AUTHORIZED

These items are part of the intended system. Listing them authorizes nothing. Each would need its own approved amendment or plan revision and an explicit start instruction.

| ID | Item | Depends on | Effort (h) | Gate (observable) |
|---|---|---|---:|---|
| R1 | WAL segments, durable publication, crash recovery, crash-state injection, F4 | Core | 28–36 | V40–V42, V47; recovery = prefix (INV-D1) |
| R2 | Compaction into store packs, manifest/CURRENT, orphan GC, disk reader + tip handoff | R1, P7 | 30–42 | V43–V46; handoff with no gap or duplicate |
| R3 | Disk experiments D1–D3: page-cache treatments, physical/logical bytes, measured α/β, rewrite cost and ranking validation | R2 | 12–18 (re-estimate at authorization) | F21–F23 with recorded residency snapshots and failed eviction attempts; no device-cold guarantee |
| R4 | Concurrent bus: 1 writer, N readers; generation-validated reads vs EBR; TSan; `perf c2c` | Core | 30–45 | V48; scaling curves |
| R5 | Network service (TCP, flow control, slow-consumer policy) — optional | R4 | 35–60 | Protocol tests; overload behavior |
| R6 | Signal-delay study (trading relevance) — optional | Core (+ book builder) | 10–16 | Time-to-correct-state and staleness of a simple book feature during catch-up; **no backtest or profit claims** |
| R7 | Binance secondary workload (pulled into Tier C) | P6 | 6–10 | T1/T3/T5 variants with constructed-order caveat |
| R8 | Power-loss / file-system crash testing (dm-log-writes-style) — optional | R1 | 15–25 | Crash-state replay results |
| R9 | Tagged index entries (8-bit topic tag; fewer record fetches) — in Tier C | P5 | 6–10 | T1 delta; shared expiry contract unchanged unless separately amended |
| R10 | Cross-partition cold bundling (different feasible set) — optional | P7 | 8–12 | Separate L-study, never mixed with core results |

**Full-project completion** is defined by observable artifacts:
1. a working bounded system covering ring, index, disk WAL, store packs, recovery, and concurrent readers;
2. reproducible experiments with raw data;
3. independently checked invariants (oracle, ENUM, crash-state tests, TSan);
4. documented limitations;
5. conclusions backed by saved measurements.

**Planning-stage completion (this run) is not that.** It means only that the design and the execution protocol are ready for review.

---

## 8. Risk register

| ID | Risk | Impact | Cheapest experiment that resolves it | Fallback |
|---|---|---|---|---|
| RK-01 | Python conversion too slow for a full day | P1 overrun | P1.2: time conversion of the first ~2 GB; projected > 45 min → switch | C++ converter; Python stays for analysis |
| RK-02 | Disk/RAM limits (30 GB, 14 GiB) | Data cannot be processed | `gzip -dc \| wc -c` (no disk writes) for the exact size; window sizing | Windows only; never store uncompressed full days |
| RK-03 | No hardware counters (paranoid = 4) | Weaker attribution | Default: time-only/Cachegrind; if access is explicitly enabled, probe actual events and record scheduling/scaling. Level 2 is not a universal guarantee. | Keep fallback; no system changes required |
| RK-04 | Laptop noise (hybrid cores, turbo, thermals) | Unstable results | P6.2 pilot: 30 repetitions, CV check | More repetitions; performance governor (DEC-2); report wider CIs |
| RK-05 | Record fetches dominate, so kernel differences vanish end-to-end | Weak M1 → T1 story | M1 vs M1-touch on one k | Report as a finding (H2) |
| RK-06 | Index slack/memory with ~10⁴ partitions | Pool pressure at small rings | P1.7 counts → §5.5 formula before P4 | Smaller B; sweep in T5 |
| RK-07 | Partition trees too big for ENUM / too many classes for DP | Exactness coverage | \|E\| and b histograms from P1.7 + workload files | Restrict exact claims; report coverage |
| RK-08 | Consumer workloads are assumed | Layout conclusions are model-dependent | Run L2 on W1 and W2 early (week 3) | Sensitivity tables; explicit limitation |
| RK-09 | Layout overfits one window | Overstated benefit | L6 (Tier C), or a 2-window check inside L2 | State as a limitation |
| RK-10 | Conservative FellBehind false positives | Pessimistic failure counts | Count in T1/T4 | R9 tagged entries |
| RK-11 | Nasdaq sample terms unclear | Publication risk | You check terms before publishing derived data | Publish code, checksums, and aggregates only |
| RK-12 | Unknown weekly hours | Scope miss | DEC-1 | Tiers; amendments with the §5 cut order |
| RK-13 | "Reconstruction of Aria" over-claimed | Credibility | — | Heuristics labeled independent; RESEARCH §1.3 non-identifiability |
| RK-14 | Toolchain issues (no ninja; CMake 4.4 policies; FetchContent network) | P0 slip | P0.2 skeleton build (≈30 min) | System googletest; vendored tarballs |
| RK-15 | Sample files change or disappear (listing updated 2026-08-06; checksum files 404) | Reproducibility | Record SHA-256 + Last-Modified at download | Keep a local copy (not redistributed) |

## 9. Open questions (also in INDEX)

- **Q-01** The article's objective and bisection variable. Not resolvable from the text; handled by labeling.
- **Q-02** Uncompressed size and counts of the chosen day (P1.2).
- **Q-03** Skew and family mix (L1).
- **Q-04** Scan/index crossover region (T1/T3).
- **Q-05** Which kernel wins at realistic k and interleaving (M1).
- **Q-06** Pool slack at realistic P and B (T5).
- **Q-07** Realistic α and β (R3).
- **Q-08** Counters (DEC-2).
- **Q-09** Weekly hours (DEC-1).

---

## 10. Completion checklists

### 10.1 Core (to tick at P8, with evidence links)
- [ ] All core phase DoDs met. PROGRESS lists the evidence per phase.
- [ ] CC-1…CC-6 and RC-1…RC-3 satisfied (VALIDATION §1.1).
- [ ] Every fuzz target ran ≥30 min at its last gate; crashes regressed.
- [ ] `data/manifest.json` with SHA-256 for every input; no raw or derived message-level data in git.
- [ ] Every figure regenerates via `figures.build --all`; the claims table points to raw files.
- [ ] Non-`ok` statuses reported; no p99.9 without n ≥ 10⁵; no throughput→latency claims.
- [ ] Optimizer claims scoped (ARCHITECTURE §6.9); worked example reproduced.
- [ ] Report includes limitations and threats to validity; resume bullets filled with measured numbers or removed.

### 10.2 Full project
- [ ] R1–R4 gates passed (R5, R6, R8, R10 if chosen); disk claims only for tested crash models.
- [ ] Measured α and β feed back into a revised optimizer study.

## 11. Technical report outline (P8)

1. Abstract.
2. Background: ITCH and the reference article, with the article's statements separated from our work.
3. Problem and semantics (ARCHITECTURE §3).
4. Tip store design: ring, positions, block-pool index, reclamation, merge kernels.
5. Correctness evidence: oracle, invariants, fuzzing, sanitizers.
6. Experimental method: environment, protocol, fairness.
7. Results: M1–M3, T1–T5 with uncertainty and failure counts.
8. Storage-layout optimization: model, exact methods, heuristics, worked example, L1–L5 results (modeled bytes).
9. Limitations and threats to validity (laptop, single day, assumed workloads, no durability in core, Nasdaq-only coverage).
10. Related work.
11. Conclusion and roadmap.

Appendices: reproduction commands; checksums; configurations; environment.

## 12. Resume bullets (placeholders; filled only from measured results)

- "Built a C++20 retained-log pub/sub engine for NASDAQ TotalView-ITCH 5.0 (≈[N]M msgs/day) with hierarchical exact/subtree subscriptions and a shared block-pool partition index. Indexed catch-up reduced replay CPU time by [X]× (median, 95% CI [a, b], n = [n]) versus linear scan for [subscription class], verified against an independent oracle with [M] randomized differential tests, ASan/UBSan, and libFuzzer."
- "Formalized topic-store splitting as a budgeted connected-partition problem. Implemented an exact O(|V|·K·2^b) class-mask DP (0 mismatches vs exhaustive enumeration on [T] random trees) and threshold-greedy heuristics. On ITCH volumes, the optimized layout cut modeled recovery bytes by [Y]% at equal store count versus a fixed three-segment split (greedy within [G]% of optimal)."

## 13. Career relevance (no promises)

**Directly relevant to engineering roles** (trading infrastructure, market data, low-latency C++). The project exercises:
- bounded-memory structures (rings, pools, reclamation);
- cache-aware algorithms (k-way merge layouts);
- exchange-protocol parsing (ITCH);
- correctness under failure (explicit expiry, crash recovery in the roadmap);
- disciplined measurement (pinning, counters, coordinated omission).

**Supporting relevance to trading roles:**
- fluency with order-book event semantics (adds, executions, cancels, crosses, NOII);
- data completeness and sequencing (replay boundaries without look-ahead);
- an optional, separately costed signal-delay study (R6) on how catch-up delay turns into stale state.

The project does not test trading skill, alpha research, or strategy performance, and it makes no claims about shortlisting, profitability, novelty, or production readiness.

## 14. Refresh amendments and phase handoff — 2026-10-17

These v1.1 amendments are included in the approved Tier B plan where applicable; they are not completed tasks. The existing core/roadmap split and separate approval/start gates are retained.

| Phase | Addition or correction | Evidence required at the future gate |
|---|---|---|
| P0 | Recheck interpreter/package pins and writable repository layout; default to no privileged settings; review optional histogram release only if T4 is selected | Environment manifest; reproducible venv command; successful counter probe or explicit fallback |
| P1 | Count the complete decompressed stream with decompressor failures propagated; do not infer a finite size range from ISIZE | Exact count/size and checked manifest; measured skew and tree/class sizes |
| P2/P3 | Common replay progress contract; oversized-record/PAD/arithmetic/id checks; correct capacity vs pressure invariants | V35/V36/V38 subset, oracle equality and unchanged state on rejected inputs |
| P4 | Ordered sealed-block expiry, wide delta arithmetic, partial/expired capacity accounting | V37 plus updated V15–V20; heap/list memory and maintenance recorded |
| P5 | Guard packed limits/sentinel, align batch statuses, qualify cache/branch hypotheses | V35/V38, kernel equivalence, representative generated-code inspection before machine-code claims |
| P6 | No simultaneous fuzzing/measurement; named cache treatment; paired repetition design; held-out Auto calibration | Raw paired rounds, honest counter/residency labels, outcome-aware digest checks |
| P7 | Rational/scaled costs, overflow limits, finite threshold domain, nonnegative multiplier bounds, exact-coverage limits | V39 plus DP/ENUM agreement on solved instances; heuristic-only/timeout rows explicit |
| P8 | Explain the review's corrected contracts and attach source-to-decision/evidence links | Report/claims reflect v1.1, with no planned test represented as passed |

The provisional 4–8 h allowance in §1 is an estimate for these correctness and review tasks, not measured effort. If the calendar cannot absorb it, apply the existing cut order through an approved amendment; never cut the amended correctness requirements. Optional papers/studies replace optional reading or stay on the roadmap rather than adding mandatory systems.

New research has bounded effects: S49 informs adversarial merge cases, S50 strengthens optional L6 drift controls, S53 adds later modeled-versus-measured ranking checks, and S51/S52 inform later re-layout/write-cost accounting. No database framework, research-package dependency, OVC kernel, or concurrency feature is added to the four-week core.

S61 adds equal-valued/distinct-event cases to existing replay validation. S59 informs repeated fallback and overlap-resource accounting in R2/V46; S60 informs cancellation/outstanding-attempt/resource-release cases only for later R5. These article-driven refinements stay inside the existing core/roadmap boundary.

At the next authorized phase, read INDEX/PROGRESS first and follow the v1.1 contracts and validation additions. **Plan v1.1 / Tier B is approved. P0 is complete; P1 waits for a separate explicit phase-start instruction.**
