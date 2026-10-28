# RC-3 deterministic engine reproduction — 2026-10-18

Requirement: `docs/plan/VALIDATION_PLAN.md` §1.1 RC-3 and its release-build
instruction: repeat deterministic engine runs and compare GCC and Clang output
digests. This is a functional correctness check, not a performance experiment.

The implementation is the original project helper `scripts/check_rc3.py`.
No paper or third-party implementation code was needed or copied for this
check. Current compiler versions and flags come from the actual compiler
executables, CMake caches and generated compile commands captured in the
machine-readable summary, rather than assumptions about installed versions.

## Contract and traceability

| Finding / requirement | Design decision / invariant | Implementation task and symbol | Validation | Executed evidence |
|---|---|---|---|---|
| VALIDATION §1.1 RC-3; release cross-compiler instruction | Same deterministic input and schedule produce the same complete observable output on repeated GCC/Clang runs | P5 reproducibility; `scripts/check_rc3.py:main`, `run`, `compare` | Two repeats per compiler for Scan and Indexed/Auto with StdPQ, BinHeap, Quad and Loser | `rc3-summary.json` and each linked child record |
| v1.1 replay progress / outcome-aware comparison | Status, delivered prefix, checkpoints, retention boundaries and explicit error metadata participate in equality | P5 Tail functional driver; `tools/tiplog_sim/main.cpp` | Success and nonempty-prefix FellBehind cases, each on a two-symbol basket and a wide subtree | All simulation JSON fields retained; only explicit requested/effective mode and kernel labels excluded in the additional cross-configuration comparison |
| Tier B wide terms require Scan; narrow eligible terms can use Indexed | Exercise both effective execution paths, including uncalibrated Auto | P5 engine mode policy; `Replay::effective_mode`, `Tail::effective_mode` | Narrow basket final range Indexed for requested Indexed; full `Subtree(itch)` final range Scan for all requested modes | Actual `effective_last_range_mode` recorded, never inferred solely from requested mode |
| Reproducibility provenance | Preserve actual source, binary, input, compiler, flags and Git identities | P5 `source_manifest`, `build_manifest` | SHA-256 before/after checks; fixed trace checksum; actual Git commit and dirty flag | Summary manifests plus configure/build records |

## Configurations

The real input is the approved H-spec 2019-12-30 09:30–10:00 trace, SHA-256
`6062bdb96ec8354ecf650cdfb979574530b2120aa06047fa48d14a78e5936f70`.
Each child publishes its first 10,000 records with seed 20191230. This is a
selected prefix correctness test. It does not establish performance or
full-day engine coverage. The original source lacks a BinaryFILE terminator;
its `incomplete=true` provenance remains recorded in the P1 manifest.

The narrow subscription is the union of `Subtree(itch/AAPL)` and
`Subtree(itch/MSFT)`. The wide subscription is `Subtree(itch)`. Success cases
use a 1 MiB ring. Expiry cases use a 4 KiB ring with deliberate consumption
pauses; error metadata and the nonempty delivered prefix remain observable.
All cases use an ample 16,384-block pool with 64 entries per block, and assert
zero pressure eviction so ring-capacity expiry is the isolated mechanism.
Exact schedules and CLI arguments are saved per child.

The synthetic check runs the independent differential harness for five seeds
of 5,000 operations for each of the nine mode/kernel configurations, twice
with each compiler. It compares all reported fields except the explicitly
nondeterministic `elapsed_monotonic_seconds`. Each such run also checks
production outputs against the independent reference.

The functional children are pinned to CPU 7, away from the timed fuzz CPU 6.
No pilot or benchmark is run by this helper. Execution durations are retained
only as command bookkeeping and are not analyzed as performance data.

## Evidence status

**Passed.** `rc3-summary.json` and the immutable dated copy
`rc3-summary-20261018T155807.085443Z.json` record 180 successful child runs and
170 successful equalities, including unchanged source and binary identities.
The outer command record is
`RC3-repeated-crosscompiler-20261018T155807.046453Z.json` (exit 0).
All 144 real-trace checks and 36 synthetic checks passed. Actual compilers were
GCC 15.2.0 and Clang 21.1.8; both use
`-O2 -g -march=x86-64-v3 -DNDEBUG -std=c++20` plus the project strict warnings.
Clang configure and both initial/final target builds passed without warnings.

The additional evidence audit
`RC3-evidence-audit-20261018T160108.154970Z.json` passed and saved
`rc3-integrity.json`: all 180 unique child records were parsed, exit and
diagnostic status checked, comparison results checked, each record hashed,
and current source/binary hashes reconciled with the execution manifest.

Representative identical outcomes across both compilers, repeats and all
applicable mode/kernel combinations:

| Case | Delivered | Replay FNV-1a diagnostic digest | Final outcome / progress |
|---|---:|---:|---|
| AAPL/MSFT success | 13 | 4574550065396610122 | Done; checkpoint after_seq=10000, next_pos=533328; 9991 batches / 3331 snapshots |
| AAPL/MSFT expiry | 6 | 2983668916145548967 | FellBehind; requested_after=0, last_delivered=1812, oldest_retained=2225; checkpoint after_seq=1999, next_pos=106408 |

The complete wide-case and synthetic outputs remain in the linked child
records. FNV-1a digests are deterministic diagnostics, not cryptographic
identity claims; input/source/binary identity uses SHA-256. The actual Git
commit at execution was `d4e5b8323dd43a77c5d5f97fc46f2be25f5a0006`, with
`git_dirty=true` recorded honestly alongside the exact source manifest.
