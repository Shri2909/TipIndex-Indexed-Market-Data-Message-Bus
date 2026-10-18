# P4 block pool/index: sources, contracts and traceability

Inspected 2026-10-18 (Asia/Kolkata). P3 passed its gate before these P4 files
were created. P4 belongs to the jointly authorized P1–P5 sequence. No concurrency,
durable storage, tagged postings or Tier C feature is introduced.

Consulted ARCHITECTURE §§5.3–5.6/10 (DD-06/07/08), IMPLEMENTATION P4,
VALIDATION V15–V20/V26/V37, FINDINGS rows 22–28 and STUDY ST-05's optional status.
Reused the saved research/dated review and their source-reading limits, plus
`results/p1/p4-review-prep.md`, `results/p3/p4-handoff-review.md` and the separately
hand-computed pressure fixture. Optional reclamation background introduces no
concurrency algorithm into this single-threaded phase.

## Original source sections actually inspected

- S01 [Nicholas Yang, Jane Street, 2026-10-05](https://blog.janestreet.com/scaling-and-benchmarking-a-critical-message-bus/):
  re-opened the original rendered article on 2026-10-18, specifically “Filtering
  messages was overloading our servers” and “Using a block pool to store the
  indexes.” The published design describes two-segment partitions, location
  indexes, and a shared pool with 1024-entry blocks that become reusable after
  all their messages expire. No Aria code was available, inspected or copied.
- Installed libstdc++ original source, **GCC Ubuntu 15.2.0-16ubuntu1 / 15.2.0**:
  `/usr/include/c++/15/bits/stl_heap.h` lines 128–183 (`__push_heap`/`push_heap`),
  224–268 (`__adjust_heap`/`__pop_heap`), and 332–378 (`__make_heap`);
  `/usr/include/c++/15/bits/vector.tcc` lines 64–101 (`reserve`). The heap
  algorithms move values within iterator ranges; vector construction/reserve
  controls backing allocation. SHA-256: `stl_heap.h`
  `4cd107c49adb58a1a31735b16bbc65ed8bd2d81967f2cecc651caa1beaaff5ef`;
  `vector.tcc`
  `e835a64b6db1cf843a2c4e2d56cc5abad6452deda0d03d8fe9ad167edc90961f`.
  These are inspected implementation revisions; no code was copied.

The published block-pool description motivates the representation. Its 32-byte
metadata, 32-bit deltas, expiry heap, generations, transaction API, pressure rule
and accounting are **independent approved project design**. The article does not
disclose these internals. S40 retains its earlier abstract-only/not-read status
and supplies no implementation details. No external code was reused and no
published speedup is claimed for this implementation.

## Finding → decision/invariant → task → symbol → validation

| Finding/source | Decision/invariant | Task/code | Check and executed evidence |
|---|---|---|---|
| S01 shared 1024-entry blocks; findings 22–23 | Fixed shared pool; ordered partition postings; P1/P2/I1–I3 | P4.1 `index::Index`, 32-byte `BlockMeta`, separate u32 `deltas_`, intrusive free/partition links and ordered seek lists in `src/tiplog/index/index.*` | V15 initial pool and repeated B1 reuse; V16 independent history/random postings and binary seek; execution pending central gate |
| Finding 24 / wide arithmetic | Compute 64-bit `(pos-base)>>3`, compare before narrowing, recompute new base; I3 | P4.2 `needs_new_block`, `commit`, `decode`; production 32-bit delta and explicit reduced test hook | V37 exact 32-GiB overflow boundary and reduced span; execution pending |
| Finding 25 / late seals | Expiry min-heap keyed by `(last,id,gen)`; strict `last<tail`; I4/I5 | P4.2 `seal`, `reclaim`, `heap_greater` | V37 old A last64 seals after full B last128; tail72 expires A first and preserves B; tail equality case; execution pending |
| Finding 26 / cold blocks and stale cursors | Lazy target expiry; cadence/pressure sweep; one generation increment per free; position guard before metadata | P4.2/P4.3 `sweep_open`, `free_front`, `seek`, `validate_cursor`, `advance` | V15 generation exhaustion before mutation; V17 cold open/replacement; V18 B1/B2 recycling guards; execution pending |
| Finding 27 / rejection | Preparation reserves resources; commit cannot allocate; pressure exposes minimum candidate | P4.2 `Preparation`, `PreparedAppend`, `prepare_append`, `commit`; Engine owns policy/ring integration | V19 abandoned plan and pressure candidate preserve membership; Engine fixture and rejection checked centrally; execution pending |
| Generic DATA16 differs from ITCH32; finding 14/27 | Sizing uses declared minimum, production span and partition bound; smaller pools retain explicit policy | P4.2/P4.4 `sizing_blocks` | V19 generic16/enforced32 synthetic schedules at adequate bound; Engine enforces selected minimum; execution pending |
| Finding 28 / postings omit overhead | Exact live/stale/open/sealed/free slots, heap/list/side/control capacities; P4/P5 | P4.4 `Gauges`, `Memory`, `stats`, independent `recount`, `check_invariants` | V17 seal/expiry/resize/reuse comparisons; external per-operation high-water maximum; execution pending |

`tests/unit/index_test.cpp` contains **18 focused cases**. Random verification
maintains its own complete `(partition,position)` history, counts retained
positions using an independently supplied tail, checks every partition cursor,
and tracks allocation high-water outside the Index. Sizing schedules exercise
30,000 appends across generic16/enforced32 and B1/B2/B16. These checks do not
replace Engine's full oracle campaigns or the timed F3 gate.

## Transaction and accounting boundaries

Preparation changes no sequence, retained ring data, block owner/generation,
posting, heap membership or free-list membership. Empty partition control states
may be constructed/reserved before a later failure; their used/reserved storage
is exposed. The rare `generation_preflight_scans` diagnostic counts actual
near-limit scans, including a rejected attempt. V19's immutable observables are
sequence, retention, contents and index membership. Reservation does not count
as a block allocation or high-water event.

Normal append inspects the target/free head/heap root and the prospective tail
supplied by Engine. A declared cadence sweep or pressure scans partition
controls; a generation-near-limit flag triggers rare full-block preflight.
There is no whole-pool/heap copy or routine per-publication all-pool scan.
Sealed maintenance costs O(log N_sealed), with explicit push/pop/seal counts.

`N*B = live + expired_allocated + open_slack + sealed_partial_slack + free_slots`
is checked against a separate traversal of the free list, partition chains, raw
entries and heap. Recount computes byte fields independently of `memory()`.
Tests track historical high-water externally; a current snapshot cannot reveal
its historical maximum.

Reserved bytes include metadata, deltas, flags, heap capacity, partition state
capacity, list capacity including dead prefixes, and Index control storage.
List used bytes count live IDs. Allocator headers/arenas are **unmeasured** and
explicitly excluded. This exact requested/reserved subtotal is never called
process RSS.

Central build/test/differential/fuzz logs and the final gate will be linked
below after execution. At this handoff checks are **implemented, not yet
represented as passed**.

## Executed acceptance checks — 2026-10-18

The parent integration run built the final release, ASan/UBSan and fuzz sources
with no warnings. Release and sanitizer suites each passed **121/121 cases**,
including the 18 index cases above. Sanitizers kept leak detection enabled and
reported no errors. Exact commands, environment and results:

- [Release build](release-build-acceptance-20261018T102040.526332Z.json) and
  [121-case release suite](release-tests-acceptance-20261018T102114.926835Z.json).
- [Sanitizer build](sanitizer-build-acceptance-20261018T102040.535818Z.json) and
  [121-case sanitizer suite](sanitizer-tests-acceptance-20261018T102159.962687Z.json).
- [Indexed k=1 release campaign](differential-release-20261018T102114.926562Z.json):
  **1000 seeds × 10,000 operations = 10,000,000 operations**, 1,520,290 effective
  indexed opens, 335,905 declared wide-term scan opens; aggregate digest
  `6829017336242550623`. All outcomes, including rejected inputs and expiry,
  were checked against the independent reference.
- [Indexed k=1 sanitizer campaign](differential-sanitizer-20261018T102212.890026Z.json):
  **200 seeds × 10,000 operations = 2,000,000 operations**, 303,957 effective
  indexed opens, 68,316 declared scan opens; aggregate digest
  `16949707518257013035`. Different seed counts intentionally produce different
  total digests; these are not an RC-3 cross-build comparison.
- [Named synthetic indexed seeds](fuzz-named-seeds-final-20261018T102323.967306Z.json):
  nine seeds / ten libFuzzer runs passed, including the independently derived
  N1/B1 pressure fixture. This smoke check does not replace timed fuzzing.

The [49-file source freeze](implementation-freeze.json) identifies the compiled
implementation. Fresh 30-minute indexed F3 acceptance is **running, not passed**
at this documentation update:
[F3 segmented gate](F3-indexed-segmented-gate-20261018T102347.429747Z.json).
P4 completion remains conditional on its terminal result and independent
statistics/hash verification. No later phase is represented as implemented.

Root also executed a separate, explicitly bounded allocator diagnostic using
fresh single-thread glibc 2.43 processes, 1-MiB nominal ring sizing, 100,000
publications and 100 partitions. B256 observed a 500,256-byte allocator charged
delta versus 495,497 requested/reserved bytes, a 4759-byte difference;
[B256 command/result](memory-allocator-B256-20261018T102300.009793Z.json).
B1024 observed 1,109,344 versus 1,103,561 bytes, a 5783-byte difference;
[B1024 command/result](memory-allocator-B1024-20261018T102300.026336Z.json).
The boundary covers the Index object and allocations, excluding Ring/Registry.
The difference includes chunk rounding and retained freed/tcache chunks and can
be affected by reuse from the baseline. It measures neither per-object headers
nor RSS and supplies no portable allocator guarantee. `Memory` continues to
label its portable exact capacity subtotal with
`allocator_overhead_measured=false`; these separate observations do not change
that flag or redefine its coverage.
