# core audit findings

Findings are recorded before corrections.

## CORE-01 — Tail expiry error loses a prefix delivered before allocation failure

- Severity: **medium correctness**, terminal recovery diagnostics after partial delivery.
- Status at recording: **confirmed, unfixed**. Reproduction executed before production edits.
- Locations: `src/tiplog/engine/engine.cpp:518`–`538`, specifically updating
  `Tail::last_delivered_` only after its delegated Replay call returns normally,
  then using that stale value for the next terminal FellBehind error.
- Trigger: an output append succeeds, a subsequent append in the same Tail poll
  throws `std::bad_alloc`, publication evicts the unread suffix, and the caller
  retries the Tail. All three APIs (legacy, unlimited, finite) share this path.
- Root cause: Replay correctly commits the successfully appended prefix before
  throwing. Tail preserves its documented public exception caches but also
  fails to preserve its private delivery accounting, although the caller has
  received the prefix in `out`. On retry Tail replaces Replay's correct
  `last_delivered` with its stale private value.
- Impact: the returned, latched `FellBehind` error misreports the last delivered
  matching sequence. A recovery caller trusting this field can replay already
  delivered messages. This is separate from the documented temporary cached
  checkpoint/status lag during the thrown operation.
- Evidence: `evidence/core/tail_partial_expiry.cpp`, compiled directly against
  the unchanged assigned core using GCC Release flags; output in
  `evidence/core/tail-partial-expiry-before.log` reports
  `delivered_prefix=1 error.last_delivered=0` for Scan, Indexed and Auto.
  No timing/performance claim is made by this probe.
- Proposed correction: when delegated replay throws, retain only the last
  successfully appended output sequence in Tail's private delivery accounting
  and rethrow. Preserve public cached status/checkpoint/error and unread retry
  behavior. Normal returned error semantics become accurate without an API or
  documented polling-contract change.
- Required validation: regression for legacy, unlimited and finite overloads in
  all modes/kernels; first versus later partial failures; eviction before retry;
  exact requested/last-delivered/oldest-retained fields; latched error and zero
  limits; existing allocation-retry/F-01 tests and final sanitizer matrix.

### CORE-01 remediation and focused verification

Status: **fixed; focused verification passed**. The terminal error now retains
the actual delivered prefix while the public caches during the thrown call
remain compatible. `Tail::poll_into` catches a delegated exception, records
`out.back().seq` only when that delegation appended successfully, then rethrows.
It does not commit an unread failed match or change inspection charging.

`PollBudget.TailExpiryAfterFailedAppendReportsActuallyDeliveredPrefix` covers
12 mode/kernel combinations × three API forms × first/second output allocation
failure = **72 cases**. For all cases it verifies the unchanged exception cache,
the real prefix, a subsequent zero-work call, eviction before retry, the full
terminal error fields, empty output, zero retry work, and error latching.

Before correction, the new regression was compiled directly with the unchanged
engine (its SHA-256 equalled the frozen source) and failed 72 assertions in the
36 partial-prefix cases. Both assertions per case compare the immediate and
latched error. After correction a fresh direct compile passed **all 24 focused
polling tests**, including the pre-existing first/second allocation failure,
normal unread-match retry, finite/nullopt/legacy equivalence, exact accounting,
PAD, metadata recycling, expiry, moves, and outlived-reader checks. Evidence:
`evidence/core/poll-regression-before.log` and
`evidence/core/poll-regression-after.log`.

The independent allocation probe also passed every injectable failure before
the first successful operation in **74 bounded configurations**: registry
registration with a live subtree observer, aliased publication under ForceEvict
pressure, and Replay/Tail polling in every mode/kernel/API combination. The
probe verifies unchanged ring range/membership and accounting after rejected
publication, registry rollback, working retries, and exact accumulated output
sequences after partially successful polling. It compiles all six runtime
implementation files directly, with C++ assertions enabled. Source and output:
`evidence/core/allocation_probe.cpp`, `evidence/core/allocation-probe.log`.
This is a bounded allocation-failure experiment, not proof for all allocations.

Root owns the final fresh Debug/Release/ASan-UBSan/fuzz builds and complete
campaigns. The direct focused runs above are newly executed Release/assertion
checks; they are not sanitizer or leak-check claims. Root has independently
reviewed the fix and regression. The Python audit agent independently reviewed
both delegated specializations, private/public exception state, and the full
regression matrix and found no blocking issue (source review, without duplicate
test execution). No performance speedup is claimed by this diagnostic fix.

## Reviewed coverage and remaining uncertainty

Read all **15** runtime/core/driver source/header files: `types.hpp` and both
files under `engine`, `ring`, `index`, `merge`, `topics`, `subs`, and `driver`.
Read the architecture's runtime/layout/failure contracts, F-01 polling contract
and measurement report, prior core audit, and core remediation. Inspected
related unit tests/reference interfaces and F-01 benchmark callers. Generated
results and prior measurements were treated as historical evidence, not a
substitute for these fresh checks.

| Area | Review and verification focus | Outcome |
| --- | --- | --- |
| Ring | Header/PAD framing, fill, physical wrap, whole-record eviction, seek/checkpoint identities, capacity/position/sequence limits, aliased-source prepare/commit | No further defect confirmed; alias+pressure failure probe passed; focused poll tests include PAD/expiry. |
| Index | Delta widths, u32 sentinels, pool pressure/reclaim/sweep, generation preflight, cursor stale-position guard, retained-range count boundaries, capacity accounting, nonallocating commit | No further defect confirmed; independent publication failure checks preserve membership/accounting and invariants. |
| Registry | Bounded paths/IDs/locals, ancestor transaction staging, observer reentrancy, observer and prepared-update lifetime, registration failure rollback | No further defect confirmed; fail-every-allocation observer/registration probe passed. |
| Subscriptions | Normalization, segment boundary matching, future subtree growth, wide fallback, filter pointer reacquisition and shared ownership | No further defect confirmed; allocation probe and focused registry-growth tests passed. |
| Merge | All four kernels, monotone replacement, slot identity, sentinel/packed position limits, aligned ownership and moved-from behavior | No further defect confirmed; all kernels exercised by focused tests and independent allocation probes. |
| Replay/Tail | Snapshot floors/uppers, conservative retained checkpoint, actual delivery prefix, finite work charging, exact output/completion boundaries, shared Tail allowance, retry/error/move/lifetime | CORE-01 fixed; 24 focused tests and all per-allocation fixtures pass. |
| Driver/callers | Dense-sequence validation, digest field bytes, pause arithmetic/cadence, payload lifetime, old API preservation | No further defect confirmed; final full driver tests remain root-owned. |

Deliberately rejected hypotheses and accepted tradeoffs:

- Tail's public cached checkpoint/status may lag when a call throws. F-01
  explicitly preserves this legacy behavior; CORE-01 changes only later error
  correctness and private accounting.
- Indexed polls reconstruct cursors/filter pointers/merge structures each call.
  Their costs are measured in preserved F-01 results and explicitly outside the
  inspection limit. No new architectural cache or changed cap was introduced.
- `Ring::at` requires a proven boundary; arbitrary locators use `at_checked`.
  That documented precondition was not reclassified as unsafe input behavior.
- Compiling a multi-term subscription can intern earlier valid roots before a
  later representational failure. No compile-level all-or-nothing contract was
  found, so this was not promoted to a missing requirement.
- Control vectors may retain additional reserved capacity after preparation
  fails. Logical membership and publication remain unchanged by design.

Peer review outside core: independently checked the Python parser/writer/
quiescence corrections and C++ CLI alias-preflight changes; no blocking issue
was found in those fixes. Reviewed the root's maintained F-01 validator and
demonstrated a one-record wrapped-variable leading-PAD model edge using the
actual benchmark. Root corrected that edge; the independent rerun now accepts
all nine positive rows. Numeric cross-review additionally demonstrated a
high-u64 cutoff/search boundary error in Python `retained_layout`; the Python
owner recorded and corrected it within PY-05. A newly executed independent
scalar append/evict comparison passes **2,046 bounded cases**, including all
sequences of length zero through four at capacities 8, 16, 64, 2^53, 2^54 and
2^63, with valid and overflowing totals. Source/evidence:
`evidence/core/retention_review.py`,
`evidence/core/python-retention-review-before.json`, and
`evidence/core/python-retention-review-after.log`. These reviews are
supplemental; the owning reports record their full test results.

Remaining limits: single-threaded core contracts were audited; unsupported
concurrent mutation, persistence/network extensions, hostile concurrent
pathname replacement, all possible allocation interleavings, and arbitrarily
long uint64 telemetry accumulation were not proven. No claim that all possible
bugs are eliminated is made. New artifact/source hashes and toolchain identity
are in `evidence/core/manifest.json`; existing uncommitted source and historical
artifacts were preserved.

## Reproduction commands

From the repository root (write new binary/log names when repeating):

```sh
g++ -std=c++20 -O2 -g -march=x86-64-v3 -DNDEBUG -Isrc -Itests/ref \
  -isystem build/release/_deps/googletest-src/googletest/include \
  tests/unit/poll_budget_test.cpp src/tiplog/engine/engine.cpp \
  src/tiplog/ring/ring.cpp src/tiplog/topics/registry.cpp \
  src/tiplog/subs/compiled.cpp src/tiplog/index/index.cpp \
  src/tiplog/merge/kernels.cpp build/release/libtiplog_ref.a \
  build/release/lib/libgtest_main.a build/release/lib/libgtest.a -pthread \
  -o audit/independent-20261027T041900Z/evidence/core/poll-regression-REPEAT
audit/independent-20261027T041900Z/evidence/core/poll-regression-REPEAT

g++ -std=c++20 -O2 -g -march=x86-64-v3 -Isrc \
  audit/independent-20261027T041900Z/evidence/core/allocation_probe.cpp \
  src/tiplog/engine/engine.cpp src/tiplog/ring/ring.cpp \
  src/tiplog/topics/registry.cpp src/tiplog/subs/compiled.cpp \
  src/tiplog/index/index.cpp src/tiplog/merge/kernels.cpp \
  -o audit/independent-20261027T041900Z/evidence/core/allocation-probe-REPEAT
audit/independent-20261027T041900Z/evidence/core/allocation-probe-REPEAT
```

The first command's GoogleTest/reference libraries are auxiliary build inputs;
all production runtime `.cpp` files are freshly compiled by the command.
