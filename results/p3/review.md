# P3 independent review — 2026-10-18

Status: **complete — required P3 evidence independently verified; no outstanding
review finding.** This review is read-only for implementation. The parent phase
gate records the overall completion/handoff. No later-phase check is implied.

## Reviewed requirements and dependency

Read `MASTER_PROJECT_PROMPT.md`, `docs/plan/INDEX.md`, `PROGRESS.md`, the joint
P1–P5 execution prompt, ARCHITECTURE §§3.1–3.7, 5.3–5.4, 5.6, 9–10, VALIDATION
§§1–4/13, ST-03/ST-04/ST-13, and the ring/replay findings in the dated review,
research and findings inventory. P2's `results/p2/phase-gate.json` records a
passed dependency, with 52/52 tests in each required preset. The approved joint
instruction permits P3 now; it does not bypass this gate before P4.

Source reading is reused from the saved targeted original-source ledgers,
including `results/p1/review-sources.md` and `results/p2/oracle-driver-sources.md`.
No additional original paper or implementation was read for this audit, and no
new external implementation facts or Aria details are asserted. The ring's
eight-byte framing and common replay progress are independent project choices;
Aeron/Kafka supply background, not identical algorithms or guarantees.

## Audit checklist

| Area | Required property | Audit status |
|---|---|---|
| Ring configuration | Power-of-two C≤2 GiB; 16≤max_record≤C/2 aligned; 16-B generic DATA, 8-B PAD | Source and final preset tests inspected; passed |
| Publication transaction | Checked alignment/length/sequence/position and prepared checkpoint resources before eviction; rejection preserves published state | Source and final preset tests inspected; passed |
| Capacity retention | Whole-item maximal capacity-only retention, exact PAD placement, dense DATA sequences | Source, preset tests and CC2 inspected; passed |
| Sparse lookup | Generic-16 capacity bound; at most 256 DATA plus PAD from floor checkpoint/tail; valid boundary/sequence checks | Source and final preset tests inspected; passed |
| Replay snapshot | Captured upper excludes later publication; after≥upper recognized before +1; future checkpoint absent | Source, preset tests and CC2 inspected; passed |
| Replay progress | Positive exact-final call reaches Done before expiry; max=0 unchanged; output-budget More; exhausted/zero-output checkpoint at upper | Source, preset tests and CC2 inspected; passed |
| Expiry | HistoryExpired at open and conservative FellBehind before memory access, correct prefix/error fields | Source, preset tests and CC2 inspected; passed |
| Oracle independence | Raw-path matching, complete copied history and division/modulo retention; no production ring/matcher helpers | Inspected P2 code: satisfied |
| Seeded differential | Required trees/subscriptions/payloads/capacities/interleavings; invariants after every operation; outputs/status/checkpoints/errors all compared | Source and full release/sanitizer CC2 evidence inspected; passed |
| F3 grammar | Publish/open/batch/close, stateful concurrent replays, independent oracle, synthetic wrap/PAD/expiry seeds | Source, seed smoke and timed gate inspected; passed |
| Gate execution | Release+ASan units; 1,000×10,000 release + 200×10,000 sanitizer operations; ≥1,800 monotonic F3 seconds with final statistics and no unresolved crash | All required evidence inspected; passed |

The P2 oracle review confirms it uses only shared value types, not Registry,
CompiledSubscription, ring or production matcher code. Its model preserves the
checkpoint immediately after DATA (including a possible PAD boundary), returns
More at an exact output limit, and checks completion before subsequent expiry.
The P3 comparison must keep those independently stated semantics rather than
changing the reference to accommodate production behavior.

## Findings and executed evidence

Inspected `src/tiplog/ring/ring.{hpp,cpp}` and
`src/tiplog/engine/engine.{hpp,cpp}` in full, plus the initial engine unit tests.
No concrete source defect was found in checked ring arithmetic, framing,
capacity-only retention, pressure accounting, preflight alias protection,
nonallocating commit or sparse lookup. `Ring::at` explicitly requires a retained
item boundary; the engine uses a canonical sparse seek or proves a supplied
checkpoint is the end of the preceding DATA before reading at that position.
The supplied checkpoint may validly name PAD; forged/expired positions fall
back to a sequence seek. Passed unit cases for these distinctions are linked
in the executed-evidence table below.

The engine author then identified a missing valid checkpoint case, confirmed
independently in review: C=64/max_record=32 and payloads 10,4,8,0 leave tail=56
(PAD), tail_seq=3 and head=104. Supplied checkpoint `{2,56}` is retained and
valid even though preceding DATA seq2 expired. The initial constructor could
only prove PAD through retained preceding DATA and therefore fell back to64.
That changes conservative expiry if a subsequent append evicts only PAD.
The author fixed this before source freeze by accepting only a proven tail PAD
with `after+1==tail_seq` and end equal to canonical next DATA. Inspected
`V36RetainedTailPadCheckpointSurvivesPrecedingDataExpiry`: it asserts the retained
PAD checkpoint and the subsequent PAD-only eviction's FellBehind fields.
Both required final preset reruns passed this regression.

One initially unmet literal design requirement was sent to the engine author/root:
ARCHITECTURE §4 says debug builds assert Replay/Tail are closed before Engine
destruction. The initial weak lifetime guard safely rejects subsequent use but
did not assert at destruction. The author added an Engine-owned lifetime anchor,
active Replay bookkeeping, move ownership transfer, release safety guard and a
debug death test. The revised source and passed conditional tests were inspected.
This implements an existing requirement, not a scope addition.
The author subsequently delayed the active-count increment until successful
constructor completion/terminal returns, so an internal seek exception cannot
leave a leaked active count. Moved-from calls reject through the empty lifetime
anchor; move assignment releases the previous cursor exactly once.

The differential source compares copied outputs by sequence, position, raw path
and payload; compares exact batch status, error, checkpoint and captured upper;
compares all retention boundaries after publication; and calls invariants after
every operation. Its seeded paths span one to four segments, capacities span
4–64 KiB, and schedules include eight interleaved replay slots, dynamic topic
creation, overlap/wide/nonexistent subscriptions, empty-spec rejection,
zero/max/oversized payloads and zero-budget batches. `fell_behind_batches` counts
batch calls, including calls to an already terminal replay, not unique failures.

F3 independently compares the same observable outcomes and retention using four
replay slots, tiny-ring configurations and synthetic operation bytes. Review
found that its oversized-publication branch initially caught
`std::invalid_argument` while both implementations throw `std::length_error`.
This would have escaped the fuzz callback. Root corrected both catches before
the timed gate. No executed crash or passed fuzz run is inferred from this
source review.

Decoded all seven named synthetic files in `tests/fuzz/corpus/ops` against the
actual byte grammar. `pad8_wrap.ops` reaches the hand-computed 8-B PAD sequence;
`exact_final_evicted.ops` delivers the final snapshot output at budget one then
evicts it before the next positive call; `irrelevant_expiry.ops` expires only
the unrelated first event before replay; `future_zero.ops` covers zero output,
zero budget and UINT64_MAX future range; `late_topic.ops` creates a matching
topic after compilation and reopens after the old snapshot; `reject_unchanged.ops`
rejects an oversized record before wrap; `overlap_equal.ops` preserves distinct
equal-valued events and excludes post-open publication. The extra topic-number
operand for opcode 4 is present. No seed framing defect was found.

Inspected ring unit-test source covers hand-computed 8-B PAD, exact fit,
generic-16 records, byte-level little-endian headers/fill, full-state rejection
snapshots, near sequence/position bounds, abandoned prepared transactions,
ring-alias republish across overwrite/wrap, PAD-aware sparse seeks, generic-16
checkpoint ring reuse, independent declared pressure accounting and invariant
checks after randomized appends. These cases are appropriately nontrivial and
do not replace the required oracle campaign.
The final checkpoint backing changed to one eight-byte position per slot,
matching the approved memory model. Unused UINT64_MAX values are never decoded;
retained positions are checked before reading and DATA sequence identity proves
the floor checkpoint. The cached first decode avoids reading the floor twice;
invariants independently validate the DATA interval and modulo slot.

Inspected the production simulator's Engine backend: it chains only completed
snapshot checkpoints, drains the current captured range before opening the
final range, hashes every delivered event and reports explicit terminal error
fields/prefix. Its Replay optional is destroyed before Engine, satisfying the
new debug ownership check. No actual simulator result is claimed here yet.

Actual executed evidence follows. This review does not claim P4 implementation
or acceptance; the separate P4 handoff is design preparation only.

## Central execution audited

Independently inspected the exact command JSON and resulting logs, without
running duplicate builds/campaigns:

| Check | Actual evidence | Reviewed result |
|---|---|---|
| Final release build/tests | `release-build-final-20261018T033936.446330Z.*`, `release-tests-final-20261018T034022.019438Z.*` | Passed, 86/86 tests; final build warning-free |
| Final ASan/UBSan build/tests | `sanitizer-build-final-20261018T033939.871451Z.*`, `sanitizer-tests-final-20261018T034025.130173Z.*` | Passed, 86/86 tests; no report; leak checks retained |
| Release CC-2 | `differential-release-20261018T034047.389885Z.*` | Passed, seed base20191230, 1,000 seeds ×10,000 operations=10,000,000; digest1217005992737911606 |
| F3 named seed smoke | `fuzz-seed-smoke-20261018T034028.474170Z.*` | Passed, 7 corpus files /8 total runs, final stats saved |
| Sanitizer CC-2 | `differential-sanitizer-20261018T034107.454243Z.*` | Passed, seed base20191230, 200 seeds ×10,000 operations=2,000,000; digest14647895778461039806; zero sanitizer reports |
| Timed F3 scan | `F3-scan-segmented-gate-20261018T034111.719594Z.json` | Passed: 1,801.291782927 monotonic seconds, 15 successful segments, 216,843 executed units; all final statistics retained |

The initial release build's two misleading-indentation warnings were fixed and
the affected final build/tests rerun; the old logs remain. The short seed smoke
and the required timed fuzz check are reported separately.

The final timed gate was independently checked for all of the following:
duration≥1,800 and exact segment-duration sum; every segment status passed/exit0;
positive final executed-unit counts and exact total; every log SHA-256 matching
its record; current binary and runner hashes matching the saved configuration;
all current corpus checkpoint hashes matching; enabled leak/UB checks; no
sanitizer error in any segment log; and an empty artifact directory. All twelve
checks passed. Maximum wall/monotonic discrepancy was 0.000004715 seconds, so
the earlier P1 clock-discontinuity caveat does not affect this gate. The verified
binary SHA-256 is
`17e2b354772002e4bed42dc80d7518f6372f2372ff3cae75681283e6bc99d62a`.

Source-freeze audit also matched all nine file identities in
`F3-initial-sources.json`: target, fuzz CMake and seven named seeds. The current
ring/engine headers and sources, differential source and ring/engine unit sources
all predate the final fuzz binary; their content was inspected after the final
pre-freeze fixes. The initial record does not contain every production-source
hash, so no claim of a broader initial hash comparison is made. The unchanged
binary proves the timed segments used the same compiled implementation; the
parent's final implementation manifest records the complete source snapshot.

Required P3 correctness evidence is met. The parent can record the passed P3
gate and continue to P4 under the existing joint authorization; no routine user
confirmation is needed. No P6–P8/Tier C/roadmap authorization is inferred.
