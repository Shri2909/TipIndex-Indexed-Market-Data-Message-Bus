# tiplog — research and implementation plan (INDEX)

| | |
|---|---|
| Plan version | **v1.1** · 2026-10-17 · research/design refresh of v1.0 |
| Approval state | **APPROVED** by the user on 2026-10-17 with the proposed Tier B defaults |
| Authorized phase | **P1–P5 jointly authorized** by the user's separate 2026-10-17 execution instruction; P0–P3 complete, P4 in progress. Stop after P5. |
| Selected scope/defaults | **Tier B**; 2019-12-30 Nasdaq data only; no privileged benchmark-setting changes; proposed writable repository setup |
| Planning-stage completion means | The design and execution protocol are reviewable. Actual implementation has advanced through P3; phase evidence and current work are recorded in PROGRESS. |

**Workspace inspected before the research refresh.** The master prompt and all seven original planning documents were reviewed; no root PROJECT_PLAN.md was present. The managed `.git` directory could not be used as a repository. The refresh edited planning files only. P0 now uses a separate writable `.tiplog-git` with the original workspace as its worktree; managed metadata is preserved. See [PROGRESS](PROGRESS.md) and [the dated historical review](REVIEW_2026-10-17.md).

## Approved core scope

**Project.** `tiplog`: a C++20 market-data pub/sub log with hierarchical exact/subtree subscriptions, a byte-bounded in-memory tip, dense per-partition indexes in a shared block pool, ordered catch-up via k-way merge, and an offline storage-layout optimizer. The workload is NASDAQ TotalView-ITCH 5.0 (2019-12-30 sample, 3.52 GB gzip). Disk durability and recovery are designed but come after the core.

**Recommended four-week core: Tier B, ≈95–99 provisional effort hours** (≈24–25 h/week), including a 4–8 h allowance for this review's correctness requirements. The old agent-review-time model is an unmeasured assumption, not a delivery promise. Calibrate scope/time after authorized P0/P1.

| Tier | Effort | What it adds |
|---|---:|---|
| A | ≈66–70 h | Minimum shippable core, including corrected contracts |
| B (recommended) | ≈95–99 h | Adds the class-mask DP with scoped exactness/coverage, more kernels and experiments |
| C | ≈129–133 h | Adds galloping, open-loop overload tests, Binance, tagged entries |

See IMPLEMENTATION_PLAN §1.

**The full system does not fit in four weeks.** WAL and crash recovery, compaction into store packs with disk→tip handoff, disk experiments, and a concurrent bus add ≈150 h beyond Tier B. With the optional network service and extras, ≈225 h. Total ≈240–315 h, about 3–4 months at 20 h/week. These are roadmap items R1–R10 and are **not authorized**.

## Navigation (deliverables in MASTER_PROJECT_PROMPT §7)

| # | Deliverable | Where |
|---|---|---|
| 1 | Four-week scope; full-system roadmap estimate | IMPLEMENTATION_PLAN §1, §7 |
| 2 | Evidence ledger; focused study plan | RESEARCH §2 and §6 (61 ledger IDs, with actual read depth); §4 analyses; STUDY_PLAN |
| 3 | Architecture, interfaces, invariants, decisions | ARCHITECTURE §1–5, §9–12 |
| 4 | Algorithms and exact scope of the optimality claim | ARCHITECTURE §5.7, §6 (§6.9 claims) |
| 5 | Dependency-ordered tasks: hours, artifacts, acceptance | IMPLEMENTATION_PLAN §2–3 |
| 6 | Weekly gates; fallback scope | IMPLEMENTATION_PLAN §4–5 |
| 7 | Correctness and benchmark matrices; figures; raw outputs | VALIDATION_PLAN §3, §6, §9, §10 |
| 8 | Repository structure, tooling, reproduction commands (PLANNED) | IMPLEMENTATION_PLAN §6; VALIDATION_PLAN §11 |
| 9 | Risks, unresolved questions, cheapest resolving experiments | IMPLEMENTATION_PLAN §8–9 |
| 10 | Completion checklist; report outline; resume bullets | IMPLEMENTATION_PLAN §10–12 (career relevance §13) |
| — | Workflow state | PROGRESS |
| — | 2026-10-17 changes, evidence, and implementation implications | [REVIEW_2026-10-17.md](REVIEW_2026-10-17.md); appendices in each respective document |
| — | Full findings/concepts → implementation inventory, including optional and deferred scope | [FINDINGS_TO_IMPLEMENTATION.md](FINDINGS_TO_IMPLEMENTATION.md) |
| — | Final problem statement, benchmark settings, expected outputs and numerical acceptance criteria | [PROBLEM_STATEMENT_AND_BENCHMARKS.md](PROBLEM_STATEMENT_AND_BENCHMARKS.md) |
| — | Reusable approval, Phase 0 start and later-phase execution messages; storing the template authorizes nothing | [IMPLEMENTATION_EXECUTION_PROMPT.md](../../IMPLEMENTATION_EXECUTION_PROMPT.md) |
| — | Single P1–P5 execution message, explicitly including full P1 and automatic continuation after passed gates; template only | [PHASES_1_TO_5_IMPLEMENTATION_PROMPT.md](../../PHASES_1_TO_5_IMPLEMENTATION_PROMPT.md) |

**Labels used throughout:**
- [A]: the article states this.
- [V]: verified from a primary source or probe.
- [I]: inference.
- [D]: design choice.
- [S]: assumption.
- [H]: hypothesis to test.
- [Q]: open question.

## Key findings and design decisions

1. **[V] Data access.** The Nasdaq samples use BinaryFILE framing (2-byte big-endian length, zero-length terminator), confirmed on 2019 and 2025 files. The checksum files listed on the server return 404, so we record our own SHA-256. No license text was found, so nothing is redistributed. Binance data is CC BY-NC-SA 4.0 (terms dated 2026-08-26), and spot timestamps are in µs since 2025.
2. **[D] Topic tree.** The hierarchy follows the ITCH spec's sections: `itch/<SYM>/{stock,add,modify,trade}/<type>`, plus `noii`, `rpii`, `dlcr`, and `itch/_market`. The article's three-segment rule then genuinely mixes E/C with X/D/U in a `modify` store. The flat `itch/SYM/type` tree is only a sensitivity case, because there the baseline already gives exact-topic stores. Splitting is confined to each symbol's partition.
3. **[D] Execution model.** The core is a deterministic single-threaded engine, with no networking, concurrency, or durability claims.
4. **[D] Tip store, corrected.** An 8-byte-aligned byte ring with PAD and whole-record eviction; max_record≤C/2, checked representation limits, and generic minimum DATA size 16 B. Dense partition indexes use shared blocks. A **sealed-block expiry min-heap** replaces the invalid late-seal FIFO; memory includes partial/stale entries and heap/list costs.
5. **[D] Replay semantics, corrected.** Captured upper bounds and a common conservative unread checkpoint align Scan/Indexed/Auto expiry. Completed zero-output ranges advance the tail bookmark. Expiry remains explicit; generation/min-key checks are defensive, not substitutes for this shared contract.
6. **[D/H] Merge kernels.** Four kernels with bounded packed 64-bit keys plus optional galloping. **No presumed winner.** Positions, cursor ids and exhaustion sentinel are checked; cache-line and branch-free claims require layout/code evidence.
7. **[D] Store layout model.** Connected partitions capture the modeled residual layout. Enumeration and class-mask DP have a proposed exactness argument and **planned**, unexecuted cross-validation. Rational scaling, checked costs, finite thresholds and per-workload exact coverage are explicit. Unsupported instances are heuristic-only.
8. **[I] Worked example.** On the article's own figure, the "after" layout (39.9 MB total exact-read waste) is reproduced by the *largest-threshold* bisection, while the minimum at 4 stores is 30.0 MB. The article's procedure is therefore not identifiable, and our heuristics are labeled independent.
9. **[V] Benchmark environment.** A hybrid laptop with `perf_event_paranoid=4`, so pin to one P-core and either enable counters temporarily or use a time-only/Cachegrind fallback with limited claims.
10. **[V/I/D] New research and qualifications.** Added the May2026 merge follow-up, 2026 DriftBench/LayoutPilot/WAIR/XLL sources, and current WG21/tool evidence. They strengthen experiments and roadmap cost accounting without adding packages/features to the core. Corrected ISIZE, perf access, cache-residency, and fsync-recovery claims. Current Python/package metadata differs from yesterday's record; P0 must use a validated explicit interpreter.

## Decisions and approved defaults

| ID | Question | Options | Effect on the plan |
|---|---|---|---|
| **DEC-1** | Tier and effort budget | **Tier B approved**; actual weekly availability remains unspecified; agent execution still requires explicit phase-start instructions | Calibrate estimates after authorized P0/P1 |
| **DEC-2** | Benchmark settings | **Approved default: no privileged setting changes**; time-only/Cachegrind fallback. Actual per-event access still requires successful probes | Counter claims require recorded PMU/scheduling data |
| **DEC-3** | Data scope | **Approved: 2019-12-30 file only** (3.52 GB); the extra 2025 day remains optional outside Tier B | Acquisition waits for authorized P1 |
| **DEC-4** | Repository setup in P0 | **Approved default: writable supported repository layout**, large data ignored, existing `tiplog` identifiers; preserve managed/read-only metadata | P0 records actual layout before source setup |

The user explicitly approved v1.1 with these Tier B defaults on 2026-10-17, separately authorized the now-complete P0, then explicitly authorized **P1–P5 as one sequence**. Execute each gate in dependency order and continue automatically through P5; P6–P8, Tier C and roadmap items remain unauthorized. Do not ask again for routine defaults or intermediate phase starts. See [the approval and execution record](PROGRESS.md).

## Top risks and open questions

- **Weekly hours unknown** (RK-12): handled by tiers and amended cuts.
- **Python conversion speed** (RK-01): measured on the first ~2 GB in P1, with a C++ fallback.
- **Laptop noise** (RK-04): pilot coefficient-of-variation check first.
- **Assumed consumer workloads** (RK-08): sensitivity across W0–W3.
- **Article ambiguity** (Q-01): labeled.
- **Measured in P1:** day size/counts and skew (Q-02/Q-03), with exact artifacts in [PROGRESS](PROGRESS.md). **Still unknown:** scan/index crossover (Q-04), kernel winner (Q-05), and disk cost parameters (Q-07, roadmap).

## Change log

| Version | Date | Change |
|---|---|---|
| v1.0 | 2026-10-16 | Initial plan for approval |
| v1.1 | 2026-10-17 | Reviewed existing package; appended newer source evidence and corrected core contracts, optimizer qualifications, environment assumptions, and validation protocol. No implementation authorized or executed. |
| v1.1 approval | 2026-10-17 | User approved Tier B with the proposed defaults; implementation remains unstarted pending a separate phase-start instruction. No plan-version or scope change. |
| P0 execution | 2026-10-17 | User separately authorized P0 only. Bootstrap, dependency pins, all four preset builds/tests, Python plumbing and environment/fallback capture passed. No scope/version change; waiting before P1. |
