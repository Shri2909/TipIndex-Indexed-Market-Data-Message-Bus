# P5 independent review — 2026-10-18

Status: **correctness and isolated-pilot evidence independently audited; final phase-gate recording remains with the root**. This reviewer owns documentation
only and runs no duplicate builds, differential campaigns, fuzzing or benchmarks.
P4's [authoritative gate](../p4/phase-gate.json) passed after its independent
[terminal audit](../p4/review.md). The user's joint P1–P5 authorization therefore
permits P5 automatically. P6–P8, Tier C and roadmap extensions remain excluded.

## Requirements and reading boundary

Reused the master/joint prompt, current INDEX/PROGRESS, approved ARCHITECTURE
§§3.6–3.7/5.6–5.7, IMPLEMENTATION P5 and VALIDATION CC1–CC3/RC3,
V13/V14/V18/V21/V23–V26/V35/V38 plus §§5–8. Read the bounded
[merge study](../p4/p5-merge-study.md), [engine study](../p4/p5-engine-study.md),
[benchmark handoff](../p4/p5-benchmark-handoff.md) and
[independent benchmark review](../p4/p5-benchmark-review.md).

Original-source inspections and read-depth limits remain those actually
recorded in these ledgers and earlier source reviews. The Sanders tournament
description informs independent initialization/replay; no paper implementation
is represented as copied. Jane Street's published observations, this project's
algorithms and performance hypotheses remain distinct. Unavailable ACM text and
unpublished Aria code supply no implementation evidence.

This reviewer additionally reopened the original S18
[Sanders PDF](https://ae.iti.kit.edu/documents/people/sanders/papers/spqjea.pdf)
on 2026-10-18 and inspected §2's loser-tree paragraph (PDF page5), Appendix A.2
(page20), and the complete Appendix A.5 (pages23–24). The update loop fixes the
traversed ancestor path from the prior winning leaf even as compared candidate
identities change. This supports the source audit below; no code was copied and
no historical UltraSPARC performance/branch result is transferred to this build.

## Review and gate checklist

| Area | Required property | Status |
|---|---|---|
| Packed keys | Checked aligned position <2^51, k≤65,535, IDs≤65,534, UINT64_MAX exhaustion only; widest legal key is MAX−1 | Source/tests inspected; central execution pending |
| Four kernels | Genuine StdPQ pop+push; inline BinHeap early exit; Quad padding/alignment arithmetic; loser initialization and fixed old-winner path, including empty/singleton/padded leaves | Source/tests inspected; central execution pending |
| Snapshot equivalence | Scan, four Indexed and four Auto configurations share output/order/status/progress/errors, max0 and exact-final behavior | Source/units inspected; full CC2 passed and independently audited |
| Cursor/filter safety | Re-seek after publishers/recycling, reacquire filters after intern, captured upper, overlap deduplication preserves distinct equal events | Source/tests inspected; central execution pending |
| Auto | Explicit validated uncalibrated thresholds, wide/count/density fallback and effective mode visibility | Source/tests inspected; central execution pending |
| Tail | Old range first, re-arm all partitions, resume after zero output, no empty re-arm loop; max0 unchanged; future start rejected; global expiry fields and terminal failure | Source/reference/tests inspected; central execution pending |
| Independent reference | Raw-path oracle/retention independent of packed keys/index state; Tail reference independently chains snapshots | Source inspected; integrated fuzz execution pending |
| CC1 | Required release and ASan/UBSan checks: zero failures/reports | Integration release157/157 and ASan157/157 passed; final compiled engine/reference source freeze verified unchanged |
| CC2 | Each of nine effective mode/kernel configurations: release≥1,000×10,000; sanitizer≥200×10,000 | Passed90M release+18M sanitizer operations; independent record/coverage audit passed |
| RC3 | Repeat digests and GCC/Clang release agreement on deterministic engine schedules | Passed180 saved child runs; independently audited current identities |
| CC3/V26 | Fresh final P5 F3≥1,800 confirmed monotonic seconds with final stats and regression accounting | Passed1805.0594934080023 confirmed seconds/104457 executions; independent terminal audit passed |
| M1/M1-touch/M2 | Complete Tier B harness variables, fair setup and sinks, real full-ring publish state and actual touch footprint | Source, full-profile functional checks and representative actual pilot independently audited |
| Pilot | Isolated release/CPU2/AC runs after fuzzing, actual Git/source/input identities, required micro flags and raw repetitions, time/CPU and declared simulated fallback | Passed3 blocks/285 individual repetitions/369 function invocations; independent terminal audit passed |

## Benchmark review position

The limited pilot may use k=64 uniform/geometric-64 across all four kernels,
k=64 uniform M1-touch, and representative fixed-workload M2 index-on/off pairs.
Full experiment-matrix campaigns and P6.2 noise calibration remain deferred.
Fresh Engine per M2 invocation, both on/off registrations in one fixed-profile
process, a prefill past real eviction, untimed setup/counter reads, and adaptive
15-repetition/0.2s warm-up/0.5s min-time/random-interleaving preserve the planned
measurement boundary. A fully initialized 1 GiB touch array must report its
actual address span/cache-line footprint; allocation size alone is insufficient.

## Findings during implementation

Initial inspection of `merge/kernels.{hpp,cpp}` found the packed-key bounds,
genuine StdPQ pop+push, binary early exit, Quad three-word child-group padding,
and loser bottom-up initialization/fixed old-winner update path consistent with
the design. This source pass is not unit or generated-code evidence.

Reported one low-level move-state robustness issue to the author: Quad's original
default move transferred its allocation but left the source size nonzero, so
source `empty()` and `top()` disagreed with its null storage; `logical_base()`
also added padding to a null pointer. The source now exchanges size and padding
to zero and makes `logical_base()` null-safe. The new geometry test checks the
moved-from object. This source resolution still awaits central execution.

Also supplied a Tail re-arm adversary before implementation: C64/max32, old
payloads10/4 finish at head56, Tail starts after2, then payloads0/10/0 yield
PAD8 at56, new DATA at64/80/112 and head128/tail64/tail_seq3. Only the old PAD
checkpoint expired; every new sequence3–5 remains. Reopening at the sequence
floor must succeed rather than falsely treating the completed old PAD position
as an unread live range. This refines an existing v1.1 case, not new semantics.

No P5 acceptance check has executed in this review. Actual central evidence will
be appended as implementation lands.

The kernel owner also corrected Loser's moved-from state by exchanging its
active count to zero, with a regression for move construction/assignment. Its
empty/top behavior is now consistent with moved vector storage. The M1 error
path breaks after `SkipWithError` rather than calling `ResumeTiming` on an
already skipped State. These changes await central execution.

### Continued source pass

Inspected the current `Replay`/`Tail` implementation and the merge unit tests.
The positive-budget common expiry check precedes all index metadata access;
batch-local cursors and filter pointers are rebuilt after that check, so topic
creation between batches cannot leave a retained filter pointer dangling.
Partition IDs are captured for the snapshot; fresh Tail ranges recapture the
compiled filters. Full output budgets return at the delivered DATA end, and
exhausted ranges advance to captured upper bounds. The Tail loop has a completed
head check and consumes the old range before opening a fresh range. A zero
budget returns before re-arming. Error remapping preserves the Tail's original
requested floor and last delivered sequence. No concrete correctness defect was
found in this pass; this is source reasoning, not executed evidence.

The merge tests compare all four kernels and both Quad padding layouts against
an independent balanced `std::merge` reference, including 65,535 inputs, sparse
empty leaves, near-limit keys and a loser-path identity-change case. Production
Engine, driver and benchmark targets do not link `tiplog_ref`; only test,
differential and fuzz targets do. Subsequently inspected the new EngineTail
tests: the supplied C64 PAD-only expiry fixture agrees with the independently
computed head128/tail64/oldest3 and new sequences3–5; old-plus-fresh shared
budgets, zero-output progress/global failure fields, initially empty/recycled
partitions, terminal failure, future starts and moved-from lifetimes have
explicit cases across all nine mode/kernel choices. The CLI opens Tail before
publication and drains to the final head checkpoint, consuming borrowed outputs
before the next publication. Tail reference/fuzz integration and central
execution are still being completed by the owners.

Inspected M1 generation, timing and verification. Its touch case initializes
all 1 GiB with nonconstant deterministic values; positions stride 256 bytes and
the output hash includes the loaded 8-byte value. Metadata separately reports
the address span, distinct 64-byte line footprint and loaded bytes. The same
seeded lists and independent sorted-union hash serve all kernels. Kernel reset,
offset reset and construction occur while timing is paused; generation and
array initialization precede the timed loop. No explicit fixed iteration count
overrides the required adaptive min-time. Geometric transitions choose a
different owner and report nominal/observed means, including the k=1 degeneracy.

Inspected M2's full harness matrix and initial implementation. It enforces a
32-byte minimum DATA size before applying that sizing bound and includes the
unused depth-one registry partition in `P+1`. Each invocation builds one fresh
Engine, generates no inputs inside timing, and prefills through a genuine DATA
eviction. Both on/off arms consume the same deterministic schedule/payloads and
perform the same sequence sink work. Reported one evidence gap to the root:
the initial output lacked prefill count, measured start/end sequence/head/tail,
before/after eviction counters and high-water levels. Requested an untimed
invocation-state record so its warm-state and differing-prefix interpretation
are independently auditable. The root added these fields to invocation
`details`, rejects any prefill pressure before entering timing, and labels
adaptive runs as different-length prefixes of the same cyclic schedule.
Inspected the fix; central execution remains pending.

Inspected `tests/ref/oracle_tail.hpp` and its five direct tests. Its live model
walks ScanOracle's copied full history and raw paths, finds item boundaries
independently, and does not import production Engine/index/merge helpers. It
retains the original global request/last-delivered fields across range changes,
preserves completed checkpoints on failure, and independently handles an old
completed PAD boundary expiring while all new DATA remains retained. No defect
was found in the source pass. This does not establish integrated F3 success.

### Integrated F3 source audit

Inspected the root's integrated `TIPLOG_FUZZ_MODE=all` target. Snapshot and Tail
opens consume explicit mode/kernel bytes; opcode8 opens Tail,9 polls it,10
closes it and11 polls all active Tails. Existing op7 zero-budget checks include
both kinds of reader. Every successful poll compares ordered locators, raw path,
payload, status, complete error fields, progress checkpoint and captured upper
bounds with the independent references. Future Tail starts are rejected in both
implementations without replacing a pre-existing active object. All references
are declared after their owner, so destruction order preserves lifetime rules.

The ordinary grammar has a real two-partition subscription, B1/2/4 and
C64…8192, plus Auto count/density threshold variants that permit effective scan
and indexed execution. Its dynamic paths remain in the existing `md/future`
partition; the independently ample pool prevents intentional pressure from
silently changing the capacity-only oracle's retention. The high-bit branch
separately runs the one-block pressure fixture for all four kernels, checking
literal golden tails, generations, payloads and rejection state. No engine tail
is supplied to the oracle. No reference bug was found in this source audit.

Noted that integrated opcode1 consumes two more bytes than the old P3/P4 open
grammar. Earlier corpus inputs remain useful arbitrary fuzz inputs but cannot
establish their prior named semantics under the new decoder. Requested freshly
decoded P5 named seeds and a manifest distinguishing those from corpus reuse.
The root subsequently added17 fresh named seeds in
[`named-corpus.json`](named-corpus.json), with literal decoded bytes and hashes.
Independently decoded all nine multi-partition mode/kernel seeds and the
forced-count/density Auto, true-pressure, completed-PAD, zero-output/global
expiry, last-matching expiry and rejection cases. Their operation schedules and
hand-computed outcomes agree with the grammar. Requested a minor max0 wording
or schedule correction in `tail_future_topic_zero_output`: its initial version
issued the zero-budget call only after the future event had been delivered,
while the description claimed an initial empty Tail max0 check. The root added
an op7 immediately after the initial publication, before capturing that range;
the named hash now starts `bae3894a…`. The17-seed smoke
`integrated-named-seed-smoke-20261018T160019.405342Z` passed18 initialization
runs with final statistics and no sanitizer report. A fresh timed all-mode F3
started at16:01:10UTC; it remains pending until its full1800 confirmed monotonic
seconds and final identity verification pass.

### Central evidence inspected so far

Read the saved command JSON/logs for
`release-build-integration-20261018T155427.261626Z`,
`sanitizer-build-integration-20261018T155436.147976Z` and
`fuzz-build-integration-20261018T155436.161793Z`: all exited0, and these three
integration build logs have no compiler warning/error diagnostics. The retained
earlier initial release log contains a dangling-else warning; it is historical,
not silently discarded.

`release-tests-integration-20261018T155700.707669Z.json` and its log, plus
`sanitizer-tests-integration-20261018T155840.807045Z.json` and its log, each
report **157/157 tests passed**, exit0. This includes the new merge,
EngineMerge, EngineTail and independent OracleTail cases. The sanitizer command
retains `detect_leaks=1:abort_on_error=1` and
`print_stacktrace=1:halt_on_error=1` in its saved environment, with no sanitizer
report in the log. Full CC2, RC3, fresh timed F3 and the isolated pilot remain
pending; these integration results do not themselves pass the final P5 gate.

Inspected `scripts/run_p5_pilot.py` before execution. It preserves the required
15 repetitions,0.2s warm-up,0.5s minimum and random interleaving; uses60s
monotonic settling before every block; checks AC throughout; verifies actual
child CPU2 endpoints; and keeps the observer off CPU2/3. Actual Git, source,
binary, input, environment and compiler identities precede settling. It saves
raw repetitions and actual function invocation order, flags frequency endpoints
more than10% from the session median while retaining all outcomes, and states
the visible-process/operator-declaration limit honestly. No machine setting is
changed. Pilot execution evidence remains pending.

Read `rc3-summary.json`, `rc3-integrity.json`, the RC3 checker source and all180
saved child records. Independently recomputed equality groups directly from
each record's raw stdout:45 case/mode groups each contain four equal repeated
GCC/Clang results (only synthetic elapsed time excluded). The four real-trace
scenarios agree across all nine mode/kernel configurations on every field
except explicit mode/kernel/effective-mode labels. Successful runs complete at
checkpoint10000; expiry runs retain nonempty prefixes and explicit FellBehind
fields. Synthetic digest `8683377447309583604` is also identical across all nine
configurations. Rehashed the summary's current production/reference/checker
source files and both builds' Engine CLI/differential binaries; identities
match. The command record `RC3-repeated-crosscompiler-20261018T155807.046453Z`
and independent saved integrity audit exited0. This passes RC3 for these
declared deterministic scenarios, not every possible workload.

### Representative release generated code

Executed the read-only `review-assembly-20261018T160549.494817Z` extraction
through the command recorder; exit0. [`assembly-review.json`](assembly-review.json)
stores every actual `nm -S -C`/`objdump -d -C --start-address=…
--stop-address=…` argv, output SHA-256, compiler command and source identity.
Nine symbol dumps (both touch variants of all four kernels plus StdPQ's
replacement wrapper) are saved under [`assembly/`](assembly/). This is no timing
run. Binary inspected: `build/release/merge_bench`, SHA-256
`7ae9d903b4b19f036416556db5d33934ff0e242a9659a697c6b06e1d3fb2533d`;
GCC15.2.0/Ubuntu15.2.0-16ubuntu1, `-O2 -g -march=x86-64-v3 -DNDEBUG`;
GNU Binutils2.46. The binary hash is checked unchanged across extraction.

Inspected the four non-touch merge routines, StdPQ's wrapper and the Loser
touch loop. Narrow observations for this exact binary:

| Inspected code | Actual observation | Limit |
|---|---|---|
| Loser non-touch,0xf8a0…0xf8bc | Opponent selection/winner update use conditional moves; the ancestor loop ends in `jne` | Validation, exhaustion and outer-loop branches remain; the whole routine is not described as branch-free |
| BinHeap non-touch,0x1048f…0x104d8 | Child minimum selection uses conditional moves; `cmp`/`jb` at0x104ca/0x104cd continues descent only when needed | Observed early exit gives no measured branch-miss or runtime benefit |
| Quad non-touch,0x10840…0x108a4 | Scalar child loads/comparisons and conditional moves are followed by loop/early-exit branches | Three-word padding geometry does not establish measured cache misses, SIMD work or lower runtime |
| Loser touch,0xf9ce and0xfa88 | A64-bit indexed array load survives and its loaded register feeds the output hash | This proves a load in this build, not cache residency, unique line fetches or latency |
| StdPQ non-touch,0x10c5f | GCC emits a direct call to its out-of-line `StdPQ::replace_top`; custom update routines are inlined in their merge loop | No artificial `noinline` annotation exists. This compiler choice must be disclosed and cannot be isolated as a performance cause from this source inspection |

No cross-compiler, all-architecture or hardware-counter conclusion follows.
If the final benchmark binary differs, these addresses describe only the saved
binary and must be rechecked before attaching machine-code claims to a new one.

### Terminal CC2 evidence audit

`CC2-all-configurations.json` passed all18 children: nine configurations each
at1000 seeds×10000 operations in release and200×10000 under ASan/UBSan,
**90,000,000+18,000,000 operations** total. The independent read-only
`review-CC2-20261018T160918.692105Z` command exited0 and saved
[`CC2-independent-review.json`](CC2-independent-review.json). It reopens every
child command/log, checks exact seed/operation/mode/kernel argv and successful
payload counts, checks retained leak/UB sanitizer settings and absence of
reports, and recomputes identical observable results across the nine
configurations within each preset.

The common release digest is`1217005992737911606`; the common sanitizer digest
is`14647895778461039806`. These differ because the prescribed seed counts
differ. Each requested Indexed and Auto kernel has positive **actual indexed
execution batches** and multi-partition opens; Auto also has positive actual
Scan execution. For example every release Auto arm executes44039 indexed and
31633 Scan batches. This verifies coverage beyond naming a kernel in an argv.
The current release campaign binary matches its RC3 identity, and all RC3
production/reference/campaign/checker source identities still match. No
differential campaign was rerun by this reviewer. Fresh timed F3 and the
isolated benchmark pilot remain required before the P5 gate can pass.

### Benchmark functional and audit preparation evidence

Inspected `M1-full-pilot-functional-20261018T160201.375404Z` (exit0) and its15
JSON rows: three full2^22-output profiles, each across four kernels plus the
second Quad layout. Each profile has identical input and independently expected
output hashes across all five arms. The touch rows record1,073,741,824 initialized
bytes,1,073,741,576 address-span bytes,268,435,456 distinct64-byte-line footprint
bytes and33,554,432 loaded bytes. These are distinct quantities, not a claim that
every byte of the array is fetched during the merge.

Inspected `M2-full-matrix-functional-20261018T160504.287611Z` (exit0) and its60
profile rows: fixed12/32/64/256 and empirical lengths, P1/100/10000,
uniform/Zipf1.1, B256/1024; each verifies both index arms, so120 arms total.
Each uses65536 publications and an explicitly reduced65536-byte functional ring.
These are functional checks, not full-capacity timing results. The limited
timed pilot still must use the declared1GiB ring and raw required repetitions.

Inspected `scripts/check_p5_pilot.py`, the recorded747-case digest self-test and
three synthetic saved-artifact audit checks. The independent M2 formula follows
`h[n]=rotl(h[0],7n) XOR Σ_XOR rotl(seq[j],7(n−1−j))`: grouping j modulo64 makes
each group's rotation constant, with constant low six sequence bits and a
consecutive high58-bit XOR range. This is mathematically independent of the
production recurrence implementation. The checker validates each adaptive
invocation's own count/digest and hand-computed fixed64 prefill state. It also
checks M1 against saved independent functional hashes and distinguishes bulk
GBench rows from invocation order instead of inventing an exact calibration
mapping. The self-tests are synthetic algebra/artifact validation, not an actual
pilot. The real post-pilot audit remains pending.

### Terminal F3 independent audit — 2026-10-19

Executed a separate read-only standard-library Python audit through
`.venv/bin/python -`; exit0. It does not import the gate runner's verifier or
launch any fuzz, build, test or benchmark process. The audit result and every
segment log identity are saved in
[`F3-independent-review.json`](F3-independent-review.json). The root's separate
`verify_fuzz_gate.py` result remains independent evidence.

The terminal gate
[`F3-integrated-segmented-gate-20261018T160110.829382Z.json`](F3-integrated-segmented-gate-20261018T160110.829382Z.json)
has status `passed`, no active attempt or resumption, and15 successful segments.
Recomputed their accumulated **1805.0594934080023 monotonic seconds** and
**104457 executions** from all15 exit0 records and independently parsed terminal
statistics. Every log has exactly five final statistics and a `DONE` record;
each SHA-256 matches, with no sanitizer/fuzzer failure diagnostic. Every segment
retains CPU6 pinning, full65536-byte inputs with length control disabled, final
statistics,2GiB RSS ceiling and10s timeout. The saved environment retains
`TIPLOG_FUZZ_MODE=all`, leak detection and halt-on-UB outside tracing. Segment
wall/monotonic discontinuities are below1ms; the gate uses the confirmed
monotonic sum rather than elapsed wall time. Peak recorded RSS is805MiB.

Rehashed the final fuzz binary
`cf050fa28039bd171ef951ea89ca3cd60c1f9a988b961216822637880d92ac6a`,
runner, all38 frozen compiled source/build files and the exact1357-file terminal
corpus. All identities match the saved records. The dedicated failure-artifact
directory is empty. This passes the final P5 integrated F3 requirement for the
declared source boundary. It makes no exhaustive-correctness claim and does not
replace the separately required isolated benchmark pilot. Earlier pending
statements in this review describe the stage when they were written; this
terminal finding supersedes them for F3.

### Terminal pilot independent audit — 2026-10-19

The actual saved session [`pilot-latest.json`](pilot-latest.json) passed all
three serial blocks: M1/M1-touch225 individual rows across15 cases, and
M2-B256/M2-B1024 each30 rows across the index-on/off pair. All19 cases retain
15 distinct repetition indices: **285 measured rows**, plus the complete
**369 function invocation** log including warm-up/calibration. The outer command
`isolated-pilot-20261019T005945.699984Z` exited0. Every child retains15
repetitions, random interleaving,0.2s warm-up and0.5s adaptive minimum, without
a fixed-iteration override. Each block settled for at least60 confirmed
monotonic seconds. AC stayed online at all saved observations; all invocation
CPU endpoints are2. Per-process ASLR disable succeeded and the raw Benchmark
contexts report it disabled. The observer excludes CPU2/3.

Executed a separate read-only `.venv/bin/python -` audit, exit0, saved as
[`pilot-independent-review.json`](pilot-independent-review.json). It checks
raw profiles, repetition groups, invocation order, input/output hashes, M1
touch footprint, M2 full1GiB steady-state prefill/eviction fields, command
flags, settling, power, frequency and raw-file identities. Rehashed all84
recorded source/build identities and both benchmark binaries; unchanged.
The source revision is `aa13c1824ba5a7a3593a0f63c6f455cac851e822`, with the
actual dirty state retained. The root's separately executed
[`pilot-audit.json`](pilot-audit.json) passes3821 checks, including fresh
large-input hashes and independent per-adaptive-prefix digest verification.
This review inspected those records rather than hashing the6GiB inputs again.

Recomputed all744 frequency endpoint samples and their4,162,566kHz session
median. **128 samples exceed10% deviation; every associated outcome remains
saved.** No constant-frequency or host-exclusive claim follows. Recorded
quiescence has no visible offenders before/after, and the operator declaration
states its namespace/host limits. Benchmark1.9.5 does not expose its random
interleaving seed. Actual invocation order is saved; bulk JSON does not identify
an exact calibration-to-measured-row mapping. These limitations remain visible
instead of excluding inconvenient rows.

Also rehashed the separate Cachegrind artifacts and independently reconciled
the raw event summary with
[`cachegrind-summary.json`](cachegrind-summary.json). The exit0 diagnostic
checks15 reduced4096-output profiles with a1MiB touch array. Its simulated
cache/branch counts cover the **whole process**, including setup, independent
reference generation, allocations, every case and teardown. They supply no
per-kernel hardware-counter or hot-loop attribution.

This passes the limited P5 pilot acceptance requirement. Full experiment
matrices, confidence intervals, calibrated Auto thresholds and P6 noise
calibration remain unrun. No kernel-winner or causal performance claim is
accepted from these representative medians. Earlier pilot-pending statements
record their historical stage; this terminal finding supersedes them.
