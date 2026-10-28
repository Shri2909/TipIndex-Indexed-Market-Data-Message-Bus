# Independent second pass: runtime engine and core

Date: 2026-10-26. No production code was changed.

## Scope and verification

Read in full: `src/tiplog/types.hpp`, both files under each of `engine/`, `ring/`,
`index/`, `topics/`, `subs/`, `merge/`, and `driver/` (15 production files).
Reviewed related unit-test coverage, prior AUD-001–013 and audit pressure/equivalence tests.
Rechecked prepare/commit rejection ordering, ring framing and limit arithmetic,
index generation/reclamation, captured upper bounds, resume sanitization, Tail chaining,
merge identities and moved-from/lifetime handling. No new defect was demonstrated in
ordinary publication/replay correctness under the existing documented contract.

Executed the eight existing release core test binaries: **124 tests passed**.
Their logs are the `*_test.log` files in this directory. These used existing build artifacts.
For stronger provenance, the new performance probes were also compiled directly from
all current production `.cpp` files, and produced identical output (`probe_fresh.log`).

Reproduction commands (from repository root):

```sh
c++ -std=c++20 -O2 -DNDEBUG -Isrc audit/second_pass/core/probe.cpp \
  src/tiplog/engine/engine.cpp src/tiplog/ring/ring.cpp \
  src/tiplog/topics/registry.cpp src/tiplog/subs/compiled.cpp \
  src/tiplog/index/index.cpp src/tiplog/merge/kernels.cpp \
  -o /tmp/tiplog-audit-core-probe-fresh
/tmp/tiplog-audit-core-probe-fresh

c++ -std=c++20 -O2 -DNDEBUG -Isrc \
  audit/second_pass/core/observer_reentrancy.cpp src/tiplog/topics/registry.cpp \
  -o /tmp/tiplog-audit-observer-reentrancy
/tmp/tiplog-audit-observer-reentrancy
```

## C1 — Auto can choose a full scan because its block estimate includes excluded history

**CONFIRMED; LOW performance defect/opportunity, no output correctness failure.**

Locations: `src/tiplog/index/index.cpp:370` (especially 383–385);
`src/tiplog/engine/engine.cpp:216` (especially 218–225).

Trigger: selected partition A has 1,023 old postings; after those, publish 4,000 records
in partition B, then one A record. Open replay after the first 1,023 records. The default
1,024-entry block contains both the old A postings and the sole A posting in the requested
range. `estimate_count` counts its whole 1,024 entries, although only one is in range.

Executed result (`probe_fresh.log`): range 4,001 records; estimated selected postings 1,024;
actual selected postings 1. With the default fraction 0.25, Auto chooses Scan and fetches
**4,001 records / 64,016 bytes** before its first delivery. Explicit Indexed fetches
**one record / 16 bytes**, delivering the same result. These are deterministic traversal
counts, not hardware timing/speedup claims. The fixture has no eviction and uses ordinary
default block size and Auto threshold.

This is an intentionally conservative, metadata-based estimate per ARCHITECTURE §5.6;
the finding is its demonstrated selectivity failure at a partial boundary, not a claim
that the implementation violates that specification. It especially affects recent-range
recovery/tailing after a formerly active partition becomes sparse. It is distinct from
calibrating the threshold and from prior deep-path/fan-out findings.

Recommendation: binary-search the posting deltas in the first and last overlapping blocks,
count only their in-range entries, and use full counts for interior blocks. First measure
the extra estimate cost against the avoided traversal on representative recent ranges.
No change to output semantics is required.

Regression validation: the above sparse recent range; first=last block; lower/upper exactly
at a posting; empty range; partial expired first block; multiple boundary blocks; ensure
all modes still agree on outputs/checkpoints/errors. Existing estimate tests cover whole
ranges but do not assert partial-block selectivity.

## C2 — A positive output limit does not bound poll work

**CONFIRMED missing latency-control capability; MEDIUM if the library is used on a shared
single-threaded event loop, otherwise an enhancement. Existing contract is obeyed.**

Locations: `src/tiplog/engine/engine.cpp:275`, indexed loop at 318–344, scan loop at
354–373, Tail forwarding at 413. Interface `src/tiplog/engine/engine.hpp:79`.

Trigger: exact subscription with no matching messages, but its partition is busy. In a
16 MiB ring holding one million 16-byte DATA records, a single `next_batch(1, out)` call
fetches **1,000,000 records / 16,000,000 bytes**, outputs zero, and then returns Done.
This was executed for Scan, Indexed, and Auto; Indexed visits one million postings as
well. Reducing the positive output limit does not reduce the work. Wide subscriptions
and arbitrary larger configured rings have the same property. Because publication cannot
interleave inside a batch, a caller cannot cooperatively service the publisher until
the call returns. The ring limit makes work finite, but does not give the caller an
operational latency/work bound.

**Recommended single additive feature:** deterministic work-budgeted replay and tail
polling. Preserve the output limit and add an optional bytes/records/postings work cap,
with an explicit resumable cooperative-stop reason. Optionally accept cancellation or
a deadline later. Deterministic work caps fit the project's reproducibility requirements
better than relying solely on elapsed time.

Acceptance: one poll never exceeds the declared inspection budget except a documented
single-record allowance; an empty-match query makes monotone resumable progress; repeated
bounded polls produce exactly the current unlimited output with no skips/duplicates;
PAD, eviction between polls, exact output-budget boundaries, no-op max=0, and all kernels
are covered. Indexed stopping must account for entries consumed but not delivered before
constructing a safe resume position. Existing overload behavior and Q7 remain unchanged
when the extra cap is absent. With the new cap, define intermediate checkpoint/status
semantics explicitly: per-mode physical work differs, so identical per-call checkpoints
across Scan and Indexed cannot simply be assumed.

This feature has a stronger demonstrated need than adding unrelated persistence,
networking, multithreading or a dashboard to a deliberately single-threaded research core.

## C3 — Reentrant public observer callbacks corrupt topic identity

**CONFIRMED; LOW public extension API correctness issue.**

Locations: `src/tiplog/topics/registry.cpp:155` reserves IDs from current size;
`registry.cpp:226` calls user `prepare`; `registry.cpp:231` commits stale reservations.
The public observer interface is `src/tiplog/topics/registry.hpp:42` and public registration
is `registry.hpp:107`. There is no reentrancy guard or documented no-reentrancy precondition.

Trigger: register a custom observer rooted at `r/s`. Its first `prepare()` calls
`registry.intern("r/s/inner")`, guarded against infinite recursion. Then call
`registry.intern("r/s/outer")` externally.

Executed result (`observer_reentrancy.log`): both inner and outer topics acquire TopicId 3
and local ID 1. `find("r/s/outer")` and the outer `intern()` return 3, but `get(3).path`
is `r/s/inner`; `all_topics()` contains duplicate IDs. Ordinary engine/CLI callers use
the built-in CompiledState observer, which never reenters, so that ordinary path is
unaffected. The severity is limited to callers implementing the exposed observer API.

Recommendation: reject nested mutations with an RAII mutation guard spanning preparation
and commit, or make observer implementation/registration internal and explicitly document
the restricted contract. Rejecting before the nested mutation is simpler than trying to
merge/rebase stale topic/filter transactions.

Regression validation: nested interning during prepare is rejected without registry/filter
mutation; if observer catches the rejection, the outer operation succeeds consistently;
otherwise outer rollback remains intact. Check path↔ID round trips, unique IDs/local IDs,
partition counts and live subscription filters afterwards.

The same logical defect reproduced in an ASan+UBSan build directly from current source
(`observer_reentrancy_sanitize_no_lsan.log`), with no memory/UB diagnostic. The first sanitizer
run could not finish because this environment prevents LeakSanitizer under ptrace;
the second explicitly disabled leak detection. No claim of leak coverage is made.

## Deliberately not reported as new defects

- Prior AUD-001/002/003/004/008 and pressure/generation findings were not duplicated.
- Ring ForceEvict walks the records it is already evicting; no new asymptotic defect shown.
- Indexed per-batch vectors/kernel rebuild are real fixed costs, but were already disclosed
  by the first pass and no new isolated performance measurement justifies a new finding.
- `compile()` may intern earlier valid term roots before a later representational failure.
  No compile-level all-or-nothing registry contract was found, so this was not promoted to
  an additional correctness finding.
- Driver hashes payload/path bytes and scans configured pauses every tick; these are explicit
  reproducibility/scheduling costs. No correctness issue was demonstrated, and no throughput
  claim is made without profiling its actual use.
