# Optional work-budgeted replay and Tail polling (F-01)

F-01 lets a caller limit how many records a reader examines in one turn, even
when those records produce no matching outputs. The caller can then serve other
work and resume the same reader. It is an optional extension of this project's
recovery API; it does not come from the original Jane Street project description.

For example, a Scan reader with one million nonmatching DATA records and no PAD
can previously examine all one million in one `next_batch(1, out)` call. With
`PollLimits{1, 1000}`, it examines at most 1,000 per call, saves its progress,
and finishes in 1,000 calls. The first 999 return `More + InspectionLimit` with
empty output; the final call returns `Done + SnapshotDone`. Total record
inspections remain one million. The caller must give other work a turn between
calls to obtain a scheduling benefit.

## API and caller behavior

The public declarations are in [engine.hpp](../../src/tiplog/engine/engine.hpp).
Both existing output-only APIs remain available:

```cpp
replay.next_batch(256, out);
tail.poll(256, out);
```

The new overloads return status, the reason the call stopped, inspections used,
and the `ReplayWork` delta for the entire public call:

```cpp
tiplog::PollLimits limits{256, 1024};
tiplog::PollResult result = tail.poll(limits, out);

// Consume or copy every borrowed payload before an Engine mutation.
for (const auto& message : out) consume(message);

if (result.stop == tiplog::PollStop::InspectionLimit ||
    result.stop == tiplog::PollStop::OutputLimit) {
  schedule_reader_for_a_later_turn();
} else if (result.stop == tiplog::PollStop::CaughtUp) {
  wait_for_a_publication();
} else if (result.stop == tiplog::PollStop::Error) {
  handle_recovery_error(tail.error());
}
```

The callback names above are application responsibilities, not library methods.
No scheduler, threads, timer, callback, or new runtime dependency is introduced.
The sample budget is illustrative; the library imposes no finite default.
`PollLimits{256, std::nullopt}` retains unlimited traversal and the legacy
checkpoint/exception behavior. Explicit zero is different from unlimited.

| Stop | Meaning |
| --- | --- |
| `NoWork` | Either limit is zero. Output is cleared; cached status is returned without progress or a fresh Tail capture. Lifetime is still validated. |
| `OutputLimit` | Output allowance reached. Status is `More`, including an exact final-record boundary. A subsequent positive call establishes completion. |
| `InspectionLimit` | Traversal allowance reached and work remains. Status is `More`; output can be empty. |
| `SnapshotDone` | Replay's captured range is complete. This Replay stays complete. |
| `CaughtUp` | A positive Tail call has observed the current head. A later publication can make more work available. |
| `Error` | A positive call encountered or returned a latched recovery error. Inspect `error()`. |

The output limit wins when one successful delivery reaches both limits.
Completion already known from metadata consumes no additional inspection.
Zero calls do not discover expiry or establish a fresh caught-up observation;
they may return cached `More`, `Done`, or `Error` with `NoWork`.

## What is bounded

One inspection is one Scan DATA or PAD, or one Indexed merged posting together
with its DATA fetch. Rejected candidates count. Indexed counts that posting and
fetch as one unit, although both existing telemetry fields increment. Auto uses
its effective Scan/Indexed mode. Bytes remain telemetry, not a second limit.

The allowance covers traversal. Opening, seeking, Auto planning, allocation and
merge initialization remain outside the inspection cap. Public poll timing in
the new benchmark includes that internal setup, and opening is timed separately.
Existing seek counters expose part of setup work; they do not count every Auto
metadata probe or merge operation. Large explicit Indexed partition counts can
make small-budget calls expensive even when they inspect just one candidate.
This API promises neither a millisecond deadline nor lower total CPU time.

Tail shares one allowance across the old captured range and any fresh range in
the same call. Its returned work delta sums both, including opening/seek work
for a fresh internal range. If the final unit finishes the old range while newer
DATA exists, Tail returns `More + InspectionLimit` and defers opening the fresh
range until the next positive call. If the head comparison already proves it
caught up, it returns `Done + CaughtUp` instead.

## Progress, retention and compatibility

Finite Indexed polling commits the logical boundary after rejected candidates,
so successive empty polls do not inspect the same prefix forever. This may
produce different intermediate checkpoints and different expiry timing from
unlimited polling. `last_delivered` still means the last matching output, not
the last rejected record processed. Matching output is appended successfully
before its checkpoint is committed; an allocation failure leaves that match
unread. Existing and new unlimited calls preserve legacy rejection-prefix
checkpoint behavior on allocation failure. As before, Tail's cached public
state can lag internal progress when a call throws; no `PollResult` is returned
for a thrown call, and a retry resumes its internal Replay.

The reader saves logical progress and re-seeks each batch. It does not pin
storage or retain physical index/filter/payload pointers across mutations.
An incomplete range may expire between calls; completed Replay remains done
after eviction. Consume/copy returned payloads before publishing or otherwise
mutating the Engine. Engine and readers remain single-threaded.

Keep polling the same Replay to finish its captured upper bound. Opening a new
Replay from its checkpoint captures a new upper bound; it does not restore the
old snapshot. While the required history remains retained, finite positive
polls deliver the same eventual ordered sequence, topic and payload as unlimited
polling. Scan, Indexed and Auto need not yield at identical intermediate points.

## Validation, measurements and reproduction

F-01 is complete. At the feature-acceptance freeze, the separate [feature gate](../../results/f01/phase-gate.json),
[acceptance manifest](../../results/f01/acceptance.json) and
[passing verifier](../../results/f01/checks.json) bound that freeze's sources to
executed evidence. The [measurement report](POLL_BUDGET_RESULTS.md) contains the
observed responsiveness/throughput tradeoff and its limits.
Subsequent corrections and current-source acceptance are recorded in the
[independent audit](../../audit/independent-20261027T041900Z/REPORT.md).

Final checks passed: **229 CTests in each of four presets**, **302 Python/script
tests**, **108 million legacy differential operations**, **12 million new-model
operations**, and a further **two million Release operations** matching the
sanitizer build's complete counters and digest. All four fuzz targets completed
10,000 executions each with ASan/UBSan and leak detection. The 23 focused contract
tests pass; all four deliberate contract mutations are killed. The evidence
verifier also has 43 positive/negative selftests, including complete result
serialization with bound evidence.

| Research gate | Executed coverage |
| --- | --- |
| V01–V02 | Independent DATA/PAD/candidate accounting and progress traces; million-record no-match/final-match studies at budgets one and 1,000 in every mode. |
| V03–V04 | Zero/maximum/output ties, empty/future/complete states, PAD, shared Tail allowance, final-unit rollover, deferred opening and aggregate work. |
| V05–V06 | Independent payload/order/range oracle, all kernels/modes, dynamic topics, wrapping, ForceEvict/recycled blocks, moves, expiry and lifetime. |
| V07–V08 | Failed first/second output allocation, unread-match retry, inherited Tail exception cache, legacy/nullopt equivalence, full old suites and preserved historical identities. |

The initial sanitizer run failed because the new test allocator did not pair
scalar nothrow allocation with its replacement delete. The test hook was fixed;
all four final suites pass with allocation-mismatch and leak checks enabled.
Failed/interrupted development attempts remain separate from accepted evidence.
The first final-checker invocation exposed a file-path serialization defect;
the corrected checker and its new regression are covered by the final Python run.
Four completed differential pair runs from before the interruption are reused
only after exact command/log and compatible frozen-source verification; their
production/campaign inputs are identical. All other required campaigns completed
against the final freeze. No old P1–P8 or remediation gate was regenerated.

The approved design and primary-source review are in
[RESEARCH §9](../plan/RESEARCH.md#9-f-01-research-work-budgeted-replay-and-tail-polling--2026-10-26).
The predeclared [benchmark protocol](../../results/f01/protocol.json) covers
rejection-heavy, late-match, sparse, dense, variable-size/PAD and partition-width
cases; [the feature baseline](../../results/f01/baseline.json) preserves previous
source and acceptance identities. Historical P1–P8 and remediation measurements
are separate evidence.

Build and run focused correctness checks:

```bash
cmake --preset release
cmake --build --preset release --parallel 4
ctest --test-dir build/release -R '^(poll_budget|poll_differential)\.' --output-on-failure
build/release/tiplog_poll_differential --seeds 1000 --operations 10000
```

The new independent logical model compares per-call output bytes, checkpoints,
errors, stop reasons and exact traversal counts under publication, wrapping,
topic growth, expiry, zero limits and changing allowances. It uses copied oracle
history and raw path matching, not production index/merge/filter helpers.
Replay Auto campaigns use the engine's observed effective mode to choose which
independent traversal model to apply; deterministic tests separately verify Auto
fallback/accounting. Randomized Tail modeling uses explicit Scan/Indexed, with
Auto Tail covered by deterministic tests. `fuzz_poll_budget` uses the same new
operation grammar/model; existing fuzz grammars remain intact.

Produce a fresh benchmark file (existing outputs are refused):

```bash
build/release/tiplog_poll_bench --records 1000000 --cases no-match \
  --modes scan,indexed,auto --budgets legacy,unlimited,1000 --reps 3 \
  --output results/f01/my-demo.jsonl
.venv/bin/python scripts/f01_summary.py results/f01/my-demo.jsonl \
  --output results/f01/my-summary.json
```

The completed [study](POLL_BUDGET_RESULTS.md) contains 2,274 accepted timing rows
from 758 arms, each in three fresh processes, and six separate resource controls.
The benchmark is a synthetic static Replay experiment. Its victim reader and
publisher use separate engines, so it measures caller scheduling opportunities,
not concurrent same-engine mutation or Tail latency. Round-robin arms perform
more service operations when they yield more often; both total drain cost and
poll-only cost are reported. Immediate-redrain is an explicit control: repeatedly
polling the same reader without serving others defeats that scheduling benefit.
