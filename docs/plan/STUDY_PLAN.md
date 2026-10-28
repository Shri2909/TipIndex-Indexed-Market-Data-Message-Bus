# STUDY PLAN — focused learning sequence for this build

Plan version **v1.1** · 2026-10-17 · study plan approved for the selected Tier B scope; research refresh appended in §4. Optional/roadmap readings retain their classification. No implementation exercise was run in the historical review. P0 tooling is complete (no required study items); P1–P5 are now jointly authorized in dependency order. Actual source inspection and execution state are recorded in [PROGRESS](PROGRESS.md). P6–P8, Tier C and roadmap execution remain outside this authorization.

## 0. Who does what

- **Bounded research already done:** the original ledger and the 2026-10-17 review in RESEARCH §6. This is not a claim that every cited full text was read or that research is exhaustive. Read the article analysis and corrected syntheses once; consult the dated read-depth entries as needed.
- **Your study (this file):** only what you need to build, review, and explain this project. The items below are short, targeted readings, each with a **small exercise** and a **check**. Exercises are optional practice. They are not project deliverables and do not affect phase gates.
- **Classification:**
  - **Required now**: before the phase that uses it.
  - **Just-in-time (JIT)**: only if that tier or roadmap item is chosen.
  - **Optional depth**: never needed for gates.
- **Budget:** Tier A ≈ 10 h, Tier B ≈ 12 h, Tier C ≈ 14 h, all inside the IMPLEMENTATION_PLAN hours. Roadmap JIT items are extra.

## 1. Prerequisite map

```
            ST-01 ITCH ──► ST-02 BinaryFILE ──► (P1 converter)
                │
                ▼
ARCH §3 semantics ──► ST-03 Aeron ring/positions ──► ST-04 Kafka log ──► (P3 ring)
                                    │
                                    ▼
                       ARCH §5.5 block pool ──(ST-05 reclamation, optional)──► (P4)
                                    │
             ST-11 Google Benchmark │
                     │              ▼
                     └──► ST-06 loser tree / heaps ──► ST-08 field reports ──(ST-07 galloping, C)──► (P5)
                                                                │
ST-13 sanitizers + libFuzzer ──► (P3–P5 tests)                  ▼
ST-12 benchmarking method ──(ST-14 coordinated omission, C)──► (P6 experiments)
ST-09 tree partitioning + our model ──(ST-10 Everett, optional)──► (P7 optimizer)
Roadmap JIT: ST-15 crash consistency (R1–R2) · ST-16 I/O measurement (R3) · ST-17 memory model (R4)
```

## 2. Sequence

### ST-01 — Nasdaq TotalView-ITCH 5.0 · Required now (before P1) · 1.5 h

- **Link:** https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf
- **Sections:** Overview; Architecture (locate codes); Data Types; §1.1–1.8; Appendix B. Skim Appendix A (revision log).
- **Prerequisites:** none.
- **Why it matters:** topic routing, message lengths, consumer definitions (BOOK, TAPE, AUCT, STAT), and the fact that E/C/X/D/U/B carry no symbol.
- **Exercise:** decode by hand the start of the 2019-12-30 sample: `00 0c 53 00 00 00 00 0a 11 ea 0e 8c 43 4f | 00 27 52 00 01 00 00 0a 53 a2 88 70 58 41 20 20 20 20 20 20 20 4e …`. Give each message's type, length, locate, timestamp, and (for the second) symbol and market category.
- **Answer key:** `S`, length 12, locate 0, 03:04:32.057544, event `O`. Then `R`, length 39, locate 1, 03:09:14.325414, symbol "A", category `N` (NYSE).
- **Check:** explain (a) why `D` needs the locate → symbol directory while `K` must be routed by symbol, and (b) which messages a TAPE consumer needs and why `C` has a printable flag.

### ST-02 — Nasdaq BinaryFILE v1.0 · Required now (before P1) · 0.25 h

- **Link:** https://www.nasdaqtrader.com/content/technicalSupport/specifications/dataproducts/binaryfile.pdf
- **Sections:** all (2 pages).
- **Why it matters:** historical-file framing and how to detect an incomplete file.
- **Exercise:** write the parser's states as a list: read length → length 0? → read payload → validate type and length.
- **Check:** what does a missing zero-length message mean, and what will our converter record?

### ST-03 — Aeron Transport Protocol Specification · Required now (before P3) · 1 h

- **Link:** https://github.com/aeron-io/aeron/wiki/Transport-Protocol-Specification
- **Sections:** frame header and alignment; padding frame; terms and positions; the shared-memory publication note (negative length → write → positive length).
- **Prerequisites:** ARCHITECTURE §3.5 and §5.3.
- **Why it matters:** in-band PAD, aligned variable-length records, and monotonic positions for staleness checks.
- **Exercise:** ring C = 64 B, max_record = 32 B, 8-byte alignment and a 16-byte header. Publish payloads of 10, 4, 8, 0, then 8 bytes. Track `head_pos`, `tail_pos`, `tail_seq`, and PAD. Separately explain why max_record=48 is rejected for this capacity.
- **Answer key (analytical, corrected v1.1):** sizes are 32, 24, 24, 16, 24.
  - The third publish needs PAD [56,64), evicts seq1, and leaves head=88, tail=32, retained {2,3}.
  - The fourth evicts seq2 and leaves head=104, tail=56 (PAD), retained {3,4}.
  - The fifth fits exactly to physical end, evicts that PAD and leaves head=128, tail=64, retained {3,4,5}.
- **Check:** prove that no record can straddle the physical end, and explain why a PAD can be as small as 8 B.

### ST-04 — Kafka "Log" implementation note · Required now (before P3) · 0.5 h

- **Link:** https://github.com/apache/kafka/blob/trunk/docs/implementation/log.md
- **Sections:** all. It is short; note the Reads, Deletes, and Guarantees parts.
- **Why it matters:** out-of-range errors (our `HistoryExpired`), retention by whole unit, copy-on-write segment lists, and truncate-on-recovery.
- **Exercise:** map each Kafka concept to its counterpart here (offset → seq/pos; segment → ring item/block; OutOfRange → HistoryExpired).
- **Check:** name the two corruption cases Kafka's recovery must handle, and say why a CRC catches the second.

### ST-05 — Reclamation background · Optional depth (before P4); JIT for R4 · 1 h

- **Links:**
  - Fraser TR-579 §5.2.3: https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-579.pdf
  - Hart et al. 2006 (abstract, §1): https://www.read.seas.harvard.edu/~kohler/class/aosref/hart06making.pdf
- **Why it matters:** why the single-threaded core can validate generations/checkpoints without a concurrent reclamation scheme, and why that reasoning does not transfer to threads.
- **Exercise:** describe a reader holding a recycled block reference. Apply the common checkpoint-before-dereference rule, then the defensive min-key/generation checks. Explain why neither an unproved generation recipe nor index-block EBR alone protects concurrently overwritten ring bytes.
- **Check:** state Hart et al.'s main conclusion in one sentence.

### ST-06 — Loser trees and heaps · Required now (before P5) · 1.5 h

- **Link:** Sanders, "Fast Priority Queues for Cached Memory": https://ae.iti.kit.edu/documents/people/sanders/papers/spqjea.pdf
- **Sections:** §2, the paragraph on k-way merging with loser trees; Appendix A.5 code.
- **Prerequisites:** binary heaps; ARCHITECTURE §5.7.
- **Why it matters:** the kernel layouts and their cost models.
- **Exercise:** for k = 8, count comparisons per output for:
  - (a) a loser tree;
  - (b) binary-heap replace-top when the new key is still the minimum (early exit);
  - (c) binary-heap replace-top in the worst case.
- **Answer key:** 3; 2 (find the smaller child, compare); 6 (2 per level × 3 levels).
- **Check:** explain "predictable memory access" in the loser tree and name one input shape where the heap should win.

### ST-07 — Galloping (CPython listsort) · JIT, Tier C (before P5.2c) · 0.75 h

- **Link:** https://github.com/python/cpython/blob/main/Objects/listsort.txt
- **Sections:** the "Galloping" discussion and `min_gallop`.
- **Why it matters:** run-skipping inside the merge.
- **Exercise:** tabulate linear (i + 1) vs galloping (2⌊lg i⌋ + 2) comparisons for i = 1…20.
- **Check:** reproduce the claim that galloping loses at i = 2 and 4 and wins from i = 6. Then explain why our boundary can be strictly `<` (positions are unique across partitions).

### ST-08 — Field reports on loser trees · Required now (before P5) · 0.5 h

- **Links:**
  - Prometheus PR #12878: https://github.com/prometheus/prometheus/pull/12878
  - PostgreSQL thread: https://www.postgresql.org/message-id/28f47336-84e2-445e-8216-d1ce7d3ddc3e%40iki.fi and https://www.postgresql.org/message-id/CANWCAZZ6KpsL%2BoEJFyQxqMMNv7FHRxPqUGafn9sqJzg_BmH5Qg%40mail.gmail.com
- **Why it matters:** baselines and input shapes decide which kernel "wins".
- **Exercise:** list two confounders in the Prometheus benchmark that our M1 design removes.
- **Check:** give two reasons a loser tree might lose to a heap.

### ST-09 — Tree partitioning and our optimizer model · Required now (before P7) · 2.5 h

- **Links:**
  - ARCHITECTURE §6 (primary).
  - Buchin & Selbach, abstract and §1.1: https://arxiv.org/abs/2001.00204
- **Prerequisites:** dynamic programming on trees (tree knapsack).
- **Why it matters:** this is the "exact optimizer" part of the project, and its claims must be defensible.
- **Exercises:**
  1. Recompute RESEARCH §1.3: total waste for the before (5,517,460,497 B), after (39,881,491 B), and optimal (30,029,491 B) layouts.
  2. Run H-KM by hand at T = 30 MB and T = 38.6 MB, and confirm which layout each produces.
  3. For a 3-node chain with b = 2 classes, list the DP states at each node and check the optimum against enumerating all 4 cut sets.
- **Check:**
  - (a) Why can a complete-subtree-cut model not express the figure's "after" layout?
  - (b) Why is the multiplier relaxation exact?
  - (c) Which quantity makes MASK-DP exponential, what measured class/tree counts make it practical, and how are unsupported instances reported?
  - (d) Why do rational input scaling, checked intermediates and γ′≥0 matter for the exactness claims? Why does a one-store threshold plateau need a finite search domain?

### ST-10 — Everett 1963 (abstract) · Optional depth · 0.25 h

- **Link:** DOI 10.1287/opre.11.3.399 (IDEAS record: https://ideas.repec.org/a/inm/oropre/v11y1963i3p399-417.html)
- **Exercise:** given per-partition cost curves, show why a γ sweep reaches only lower-convex-hull budgets.
- **Check:** what is reported for a budget between hull points?

### ST-11 — Google Benchmark user guide · Required now (before P5) · 1 h

- **Link:** https://github.com/google/benchmark/blob/main/docs/user_guide.md
- **Sections:** preventing optimization (`DoNotOptimize`/`ClobberMemory`); repetitions and aggregates; random interleaving; warm-up; output files; user counters.
- **Exercise:** write M1's parameter list and flags (VALIDATION §6.1).
- **Check:** what does `DoNotOptimize` **not** do, and how does a running output hash fix it?

### ST-12 — Benchmarking method · Required now (before P6) · 1 h

- **Links:**
  - LLVM benchmarking tips: https://llvm.org/docs/Benchmarking.html
  - Mytkowicz et al. 2009 (abstract): https://sape.inf.usi.ch/publications/asplos09
  - Kalibera & Jones 2013 (abstract): https://kar.kent.ac.uk/33611/
  - VALIDATION_PLAN §5.
- **Why it matters:** a hybrid laptop is a hostile benchmarking environment.
- **Exercise:** list the controls for P-core pinning on this CPU and say which need sudo (DEC-2).
- **Check:** explain why reciprocal throughput is not latency, and why runs are interleaved and repeated at process level.

### ST-13 — Sanitizers and libFuzzer · Required now (before P3.5) · 1 h

- **Links:**
  - https://llvm.org/docs/LibFuzzer.html
  - https://clang.llvm.org/docs/AddressSanitizer.html
  - https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html
- **Sections:** the fuzz target API; `-fsanitize=fuzzer,address,undefined`; `-max_total_time`; corpus and dictionaries; the maintenance-status note.
- **Exercise:** design F3's byte grammar (opcodes and operand encodings) and its oracle checks.
- **Check:** list the invariants F3 asserts after each op.

### ST-14 — Coordinated omission · JIT, Tier C (before T4) · 0.5 h

- **Link:** https://github.com/giltene/wrk2 (README)
- **Exercise:** requests are scheduled every 10 ms and the server stalls once for 1 s. Compute the latency samples a closed-loop measurement would record and the ones an open-loop measurement would record.
- **Check:** why must T4 measure from the scheduled arrival time?

### Roadmap JIT (only if R-items are approved)

| ID | Topic | Links | When | Time | Exercise / check |
|---|---|---|---|---|---|
| ST-15 | Crash consistency | ALICE (OSDI'14) §1–2: https://pages.cs.wisc.edu/~remzi/Classes/739/Fall2016/Papers/alice-osdi14.pdf · fsync failures (ATC'20) abstract and §5 observations 7–8: https://www.usenix.org/system/files/atc20-rebello.pdf · LevelDB log format: https://github.com/google/leveldb/blob/main/doc/log_format.md · man fsync(2) | Before R1 | 3 h | Write the syscall/manifest crash states. Explain why fail-stop is a policy, why EIO differs from EINTR, and why restart alone is not a storage-error recovery proof. |
| ST-16 | I/O measurement | Crotty et al. CIDR'22: https://www.cidrdb.org/cidr2022/papers/p13-crotty.pdf · man posix_fadvise(2), mincore(2), proc_pid_io(5) | Before R3 | 1.5 h | Design a cold-cache run with verification. Check: why can mmap not tell you physical reads? |
| ST-17 | C++ memory model and lifetimes | Boehm MSPC 2012 (DOI 10.1145/2247684.2247688); atomic_ref draft clauses (S58) | Before R4 | 4 h initial study; design effort separate | Propose both writer and reader accesses, lifetime/alignment and publication/reclamation rules, then justify them. §8 is an unresolved candidate design, not a proved fence recipe. Check why plain concurrent memcpy is unsafe and why TSan is not a proof. |

### Optional depth (never required)

- Knuth, *TAOCP* Vol. 3, §5.4.1 (tree of losers).
- LaMarca & Ladner 1996 (DOI 10.1145/235141.235145).
- Qd-tree: https://arxiv.org/abs/2004.10898
- Sun et al. 2014: https://amplab.cs.berkeley.edu/wp-content/uploads/2014/05/mod415-sun.pdf
- Demaine et al. SODA 2000: https://erikdemaine.org/papers/SODA2000/

These are reading only, about 4 h in total.

## 3. Schedule by tier (inside the IMPLEMENTATION_PLAN weeks)

| Week | Tier A | Tier B | Tier C |
|---|---|---|---|
| 1 | ST-01, ST-02 (1.75 h) | + RESEARCH §1 (2.5 h) | same as B |
| 2 | ST-03, ST-04, ST-13 (2.5 h) | + ST-05 optional (2.5–3.5 h) | same as B |
| 3 | ST-06, ST-11, ST-09 (5 h) | + ST-08 (5.5 h) | + ST-07 (6.25 h) |
| 4 | ST-12 (1 h) | ST-12 (1 h) | + ST-14 (1.5 h) |
| Total | ≈ 10 h | ≈ 12 h | ≈ 14 h |

## 4. Refresh reading and design exercises — 2026-10-17

Use these **instead of optional depth reading or just in time**, not as an expanding prerequisite syllabus. Required correctness changes are already in ARCHITECTURE/VALIDATION; their implementation belongs to an explicitly authorized phase.

| Item | Reading / estimated time | Concrete use and check |
|---|---|---|
| ST-18 — review counterexamples | ARCHITECTURE §13 and VALIDATION §13; 30–45 min before P3–P5 | Draw late block sealing, unrelated-message expiry and zero-output tail completion. Explain the revised contract without appealing to tests that have not run. Included in the v1.1 review allowance. |
| ST-19 — contemporary merge discussion | S49 official May2026 thread; optional 15 min replacing part of ST-08 | Identify regression cases and explain why OVC does not automatically help a scalar comparator. The linked ACM full text was inaccessible; do not claim its method was studied. |
| ST-20 — controlled drift | S50 abstract/§§2–3; JIT for Tier C L6, 30–45 min | Specify separate volume-skew and subscription-popularity changes, with seeds and a declared change point. Check that adaptation/calibration cannot use future test traces. |
| ST-21 — cost-aware layout evidence | S53 §2.4; S39 OReO and S51 abstracts; optional/JIT R3, 30–45 min | Distinguish estimated rank, measured rank, rewrite cost and amortization horizon. No new advisor/database package is required. |
| ST-22 — full write path | S52 abstract/§1 and §5.1; optional/JIT R3, 20–30 min | Draw WAL→pack→rewrite byte flows and define application write amplification. Explain why TiKV/consensus gains cannot be claimed for this single-process bus. |
| ST-23 — recent engineering lessons | S61 history/coalescing sections, optional 15–20 min; S59 handoff sections JIT R2; S60 retry/resource sections JIT R5 | Explain why identical trade values are distinct events. Draw repeated recovery fallback and identify overlap resources; for networking, show that a timeout actually releases/cancels the outstanding operation. These readings do not add a feature engine or network service to the core. |

Book references remain targeted and accurately labeled: Knuth §5.4.1 is optional and was not inspected. No newly discovered paper or book becomes required merely because it is recent.

## 5. F-01 study and review plan — 2026-10-26

**Research completed; implementation awaiting user approval.** The user requested source study for
work-budgeted replay/tail polling after the approved audit corrections. [RESEARCH §9](RESEARCH.md#9-f-01-research-work-budgeted-replay-and-tail-polling--2026-10-26)
contains the primary-source ledger, reading limits, immutable repository revisions, licenses,
proposed API/semantics, alternatives, validation gates and measurement plan. Older phase-status
statements above remain dated history; they do not govern this new research request.

The proposed first version caps **traversal inspections**, including rejected records and PAD.
Preparation, seeks, Auto planning, merge construction and allocation remain outside that cap and
must be measured separately. Review this scope before implementation; it is not a hard complete-call
CPU/time limit. A caller must still rotate between runnable consumers to offer other work a turn.

These exercises are review aids; **none has been executed as a feature test or benchmark**.
Estimated effort below is a planning estimate, not a measured delivery promise.

| Study item | Focused original reading | Exercise / pass condition | Estimate |
|---|---|---|---|
| ST-F01-01 — accounting and stop semantics | RESEARCH F01-S01/S02/S03: Aeron controlled poll, Agrona controlledRead, NAPI zero/exact-budget rules; pinned methods in §9.5 | Trace PAD, two rejects and a match under output limit 1 / inspection budget 2. Identify what is consumed, checkpointed and returned. Show why fragment/output counts alone do not prove the new bound. | 45 min |
| ST-F01-02 — work-producing boundaries | F01-S04/S06: Tokio accounting comments, DataFusion `coop.rs`/filter loop and official 2025 cancellation article | Show how filtering consumes without output and how replenishing a branch/range budget defeats composition. Specify one charge for a posting plus DATA fetch, rather than two. | 45 min |
| ST-F01-03 — continuation and retention | F01-P01 SaGe §§3.1–3.3; F01-S10 PIT comparison; current Replay constructor/Indexed loop/Index cursor validation | Prove why committing the globally minimum rejected candidate is safe. Separate processed progress from `last_delivered_`. Explain why a checkpoint neither pins bytes nor restores the old captured upper bound when a new Replay opens. | 60 min |
| ST-F01-04 — cooperative fairness and caller policy | F01-S05 Seastar helpers; F01-P05 cooperative fairness; Tokio runtime fairness/yield non-guarantees | Draw a round-robin caller with long and short readers. Contrast immediate-redrain. State which guarantees come from the library and which assumptions come from its caller. | 30 min |
| ST-F01-05 — quantum tradeoffs | F01-P02 Morsels §3.3, F01-P03 Self-Tuning §3.1, F01-P04 SEDA §3.4; optional P06/P07/P08 | Sketch throughput versus allowance without inventing measurements. Derive repeated K-partition setup cost; explain why equal record counts have unequal durations. Select experiments that could falsify the benefit. | 45 min |
| ST-F01-06 — contract and evidence review | RESEARCH §§9.6–9.10 and existing audit F-01 acceptance | Complete the decisions and matrix below. Separate old unlimited Q7 from budgeted intermediate stops/checkpoints. Completing the reading does not approve implementation. | 45 min |

Suggested order: ST-F01-01 → 02 → 03 → 04 → 05 → 06; approximately **4.5 hours** for a new reader.
Revision/section links avoid requiring full Aeron, DataFusion, Tokio or Seastar codebase study.
Recent hardware-preemption papers are optional context, not required frameworks.

### 5.1 Decisions to approve before coding

| Decision | Recommended proposal | Why the review matters |
|---|---|---|
| Scope | Inspection cap plus separately visible preparation cost | A loop counter does not bound seeks, estimates, initialization or allocation. A metadata-budgeted state machine is a larger option. |
| Unit | One Scan DATA/PAD item or one Indexed posting plus fetched DATA, matching or rejected | Fixes the audited rejection path and avoids byte-budget starvation/double-charge. |
| API | New explicit budgeted overloads; original signatures remain unlimited | Existing callers, statuses and historical comparisons retain their contract. |
| Return meaning | State plus reason: no-work, output cap, inspection cap, snapshot completion, tail caught-up or error | Zero output, exhausted budget and completion are different observations. |
| Zero/absent budget | Zero makes no progress and reports cached status with no-work reason; absence is unlimited | Avoid accidental unlimited work or a false fresh caught-up claim on Tail. Preserve lifetime/error checks. |
| Progress | Finite-budget calls commit consumed candidates; append matching output before committing it. Legacy/nullopt calls retain old rejecting-posting checkpoint behavior. | Prevent rejecting-prefix livelock without changing unlimited allocation-failure/checkpoint semantics. |
| Tail composition | One allowance and aggregate per-call counters across range rollover | Replay replacement cannot replenish the cap or erase completed-range work. |
| State reuse | Logical checkpoints and re-seek initially; no pinning or physical cursor/filter caching | Preserve existing retention and mutation safety. |
| Defaults | Opt-in only; evaluate a sweep before suggesting a deployment value | Upstream constants are not calibrated defaults for this workload. |

### 5.2 Review exercises with concrete expected outcomes

1. **Two rejects followed by a match.** With inspection budget 1, the first two positive calls can
   return no delivery, but each preserves processed progress. The third can deliver the match.
   A fourth must not reread it. Include Indexed and Scan; equal intermediate checkpoints are not required.
2. **PAD plus a record.** Budget 1 stops after PAD when it is the next traversed Scan item, charging
   it despite no output. Another positive call reaches DATA.
3. **Tail rollover.** Spend one of two units completing an old snapshot. A fresh range opened in
   that same poll has at most one left. Its telemetry includes both ranges. Then use exactly the
   last unit to complete the old range: later DATA requires `More + InspectionLimit` with fresh
   opening deferred; no later DATA permits `Done + CaughtUp` using head metadata alone.
4. **Allocation failure.** If appending a matching result fails, it stays unread; previously committed
   finite-budget rejects need not be retraversed. Legacy and nullopt calls must instead retain their
   old visible checkpoint after the same rejected prefix/failing append. Test both paths explicitly.
5. **Retention between calls.** Yield, publish enough to recycle a consumed block, then resume while
   unread progress remains retained. Contrast unread expiry, which must fail before dereference.
   Explain why a stale physical cursor can be unsafe even when a logical resume point is valid.
6. **Exact exhaustion.** Distinguish known completion from a cap-limited range without an extra
   inspection. Retain legacy More at exact output boundaries. A zero-budget query makes no fresh
   capture and does not establish that cached Done means the live Tail is caught up now.
7. **Setup amplification.** For N candidates, K partitions and allowance B, discuss roughly
   `K * ceil(N/B)` repeated seeks before output-limit stops. Seeks are binary; Auto estimates also
   traverse overlapping blocks. Identify what the inspection meter excludes.

### 5.3 Evidence required after implementation approval

Future implementation must satisfy RESEARCH F01-V01–V08: independent accounting, million-record
nonmatch progress, every boundary/PAD case, one Tail allowance, all kernels/modes, retained-history
equivalence, expiry/move/lifetime safety, allocation failure and unchanged unlimited behavior.
Random positive budgets supplement deterministic fixtures. Mutations that charge matches only,
ignore PAD, reset on rollover or lose rejecting Indexed progress must be killed.

The future performance study should hold inputs and caller schedule constant while varying budgets,
report complete-call timing and preparation separately, and measure short-reader/publisher service
delay alongside throughput. Include zero-output polls, large partition counts, Auto block estimates,
variable record sizes, process repetitions, raw non-ok outcomes and sample counts for tail statistics.
No responsiveness guarantee or speedup is inferred from the papers. The contract provides
deterministic inspection limits; the study determines their practical tradeoff.

**Stop point:** this is study material and a reviewable proposal. Production code, API, tests,
dependencies and historical results are unchanged. Begin F-01 only after user approval.

## 6. Approved implementation follow-through

The user approved F-01 on 2026-10-26. The prior stop point above is the historical
research boundary. The [implemented API contract](../report/POLL_BUDGET.md),
[compiled-source freeze](../../results/f01/source-freeze-final.json), and
[predeclared exact study plan](../../results/f01/study-plan-final.json) now track
the execution phase separately. No paper's timing result or budget constant is
adopted as a project default. Final correctness and measurement evidence is
required before feature closeout.
