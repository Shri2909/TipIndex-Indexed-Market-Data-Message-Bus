# P5 multi-partition replay, Auto, Tail and deterministic campaigns

Access date: **2026-10-18 (Asia/Kolkata)**. The joint P1–P5 instruction permits
P5 after [P4's passed gate](../p4/phase-gate.json). This source ledger records
implementation and actual reading boundaries; it does not assert acceptance
before the central command records and final P5 gate exist.

Read the joint execution prompt; current MASTER/INDEX/PROGRESS and the approved
ARCHITECTURE §§3.6–3.7, 4, 5.6–5.7, 9–10; IMPLEMENTATION P5;
VALIDATION V13/V14/V18/V21/V23–V26/V35/V38, CC1–CC3/RC3; FINDINGS
#9/#10/#16–20/#26/#29/#33/#34/#46/#47; and STUDY ST-06/ST-08/ST-11.
The bounded [P5 Engine study](../p4/p5-engine-study.md) supplied the specific
integration adversaries without changing approved semantics or scope.

Original-source inspections and revision/read-depth limits are reused from
[P3 Engine](../p3/engine-sources.md), [P4 Engine](../p4/engine-sources.md),
[P2 oracle/driver](../p2/oracle-driver-sources.md),
[P1 primary-source review](../p1/review-sources.md), and the P5 kernel owner's
source ledger. No new technical mechanism is inferred from unavailable paper
text. Kernel-specific primary-source inspection belongs to the kernel ledger;
this integration consumes its checked scalar-key API and independent kernels.

Jane Street's published total-order/hierarchical-subscription/index-location
statements remain published facts about its system. Our exact replay progress,
cursor re-seek, Auto policy and Tail state machine are independent designs.
The S61 history-versus-coalescing distinction requires preserving equal-valued,
distinct sequence-numbered events. No Aria implementation detail, external
source code reuse, concurrent lifetime guarantee, or performance gain is claimed.

| Source/finding → decision/invariant | Task → file/symbol | Validation → executed evidence/status |
|---|---|---|
| FINDINGS #29; S01 published merging and S03 canonical order; ARCH §5.6 and INV-Q1/Q2/Q5 | P5.1/P5.3 `Replay::{Replay,next_batch_into}` stores one selected partition ID, builds each positive batch's cursor heads below captured upper, and uses `merge::make_kernel` with `std::visit` for four real kernels | `EngineMerge.V21FourKernelsAndAutoEqualIndependentOracle`, V23 publication/upper-prefix test, V24 overlap/equal-event cases; final central tests and CC2 logs are authoritative |
| v1.1 analytical correction, FINDINGS #16–19, INV-Q3/Q4/Q7 | P5.3 common entry ordering remains lifetime/max0/terminal/completed-upper/expiry before index access. A full budget immediately returns More at the last DATA end; complete exhaustion advances to captured upper | All nine mode/kernel choices in V35 conservative irrelevant expiry, full-budget/final-expiry, empty-cursor and independent-oracle comparisons; CC2 compares exact output/status/error/checkpoint/upper |
| FINDINGS #26; consumed block can recycle while unread checkpoint remains retained | P5.1 `Replay::next_batch_into` re-seeks per partition at each positive batch; within a batch no publisher interleaves. No old cursor or block pointer persists between calls | V18 recycled delivered B1 block for all nine choices, followed by retained second record; stale unread outcomes in P4 tests and integrated F3 |
| P2 filter views invalidate on intern; new topics cannot have DATA below an old captured upper | P5.3 `Replay::partitions_` stores IDs; current `partition_filter` pointers are acquired only inside the noninterleaved batch; Tail reopens from current compilation state | V23 filter growth and upper exclusion; Tail re-arms previously exhausted/empty partitions and newly matching topics; wide new-partition case uses Scan |
| FINDINGS #33, ARCH §5.7/V38 | P5.1 `merge::pack` validates aligned positions below 2^51, k≤65535 and IDs≤65534. Explicit Indexed rejects unsupported k; Auto can select Scan. Sentinel is never decoded as a valid position | Merge unit suite covers direct near-limit/max-k/padding cases; Engine V38 tests checked no-mutation position failure, largest legal packed value, sentinel rejection and 129 selected partitions |
| FINDINGS #34; ARCH Auto policy is a design, calibration belongs to P6 | P5.3 `EngineConfig::{auto_max_partitions,auto_max_index_fraction}` exposes validated **uncalibrated** initial values 64/0.25. Replay chooses Scan for wide/index-off/count/density cases; explicit Indexed requires enabled index | `AutoPoliciesAreExplicitValidatedAndUncalibrated`, disabled-index/wide cases; campaigns record effective Indexed/Scan opens and actual execution batches. No threshold is described as measured or optimal |
| ARCH §3.7 and v1.1 zero-output progress correction | P5.3 `Engine::open_tail`, `Tail::{Tail,poll}` chain completed captured ranges using resume checkpoint rather than last output. Old range finishes before one fresh range within the remaining shared output budget; a caught-up head does not repeatedly open empty ranges | Tail V14 re-arm/shared-budget cases; V35 max0, zero-output, caught-up loops, future InvalidRange, initial HistoryExpired and late global FellBehind tests; independent Tail reference/fuzz is maintained separately by root |
| Completed checkpoint may be an expired PAD while all new DATA still exists | P5.3 Tail re-open delegates sequence-floor/canonical-boundary proof to Replay rather than rejecting a completed old byte position | Hand-derived C64/max32 payload10/4 then0/10/0: old checkpoint{2,56}, final head128/tail64/oldest3; `V35CompletedPadCheckpointMayExpireWithAllNewDataRetained` checks all new seq3–5 exactly once across nine choices |
| Existing-reader failures keep original requested floor/global last-delivered sequence | P5.3 `Tail::requested_after_`, `last_delivered_`; later internal HistoryExpired remaps to terminal FellBehind; initial HistoryExpired remains distinct | V35 zero-output/global-failure test retains requested0/last2 and later oldest; terminal re-polls preserve error and max0 preserves completed progress. On failed re-arm, the last completed Tail checkpoint remains available while the attempted captured upper advances |
| ARCH §4 non-owning reader lifetime | P5.3 Tail owns its current Replay, preserving the debug active-reader assertion; weak lifetime checks and default move transfer the one active range | Tail move construction/assignment and moved-from poll guard; inherited Replay debug-destruction/release-lifetime tests |
| CC2 independent reference and identical schedule across algorithms | P5.4 `tests/differential/campaign.*` uses the same seeded RNG calls and subscription/publish/open/batch schedule for Scan, Indexed×4 and Auto×4. Oracle still owns raw-path matching and independent retention. Ample generic16 pool sizing uses an independently bounded 41 registered partitions | Every operation checks invariants; every batch checks raw path/payload/seq/pos, status/errors/checkpoint/upper. JSON exposes effective opens, multicursor opens, actual execution batches and a canonical aggregate digest. Required full release/sanitizer campaigns run centrally |
| P2 deterministic driver, ARCH §3.7, honest failure accounting | P5.3 `tools/tiplog_sim/main.cpp` adds all modes/kernels and explicit Auto settings; real Tail starts before publication, max0 cannot capture a newer head, final drain reports checkpoint/error and aggregate hashes without payload logging | Central functional trace smokes and RC3 repeated GCC/Clang checks. Output labels policy uncalibrated and last captured range's effective mode. These functional runs are not throughput/latency benchmarks |

## Execution status

Implementation and focused tests are written. Root owns the central release,
ASan/UBSan and fuzz builds, required CC2 campaigns, fresh final timed F3, RC3 and
phase-gate records to prevent conflicting builds or duplicate expensive checks.
At this ledger's initial write these acceptance checks remain pending. Actual
failures/fixes and their logs are retained in `results/p5/commands.jsonl`; append
terminal evidence links after execution. P6 calibration/campaigns, Tier C and
roadmap features remain deferred.


## Accepted terminal execution — 2026-10-19

Earlier pending text is superseded by the [final gate](phase-gate.json). Both
release and ASan/UBSan passed157/157; CC2 passed90M+18M operations across all nine
configurations per preset with exact canonical output/outcome agreement and
positive actual multicursor execution. RC3 passed180 runs/170 equality checks.
Integrated F3 passed1805.0595 monotonic seconds/104457 executions; all38 frozen
source identities match. [CC2 audit](CC2-independent-review.json),
[RC3](rc3-summary.json), [F3 verification](fuzz-gate-verified.json). Auto remains
uncalibrated; P6 evaluation and roadmap extensions remain unrun.
