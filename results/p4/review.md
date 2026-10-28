# P4 independent review — 2026-10-18

Status: **required P4 evidence independently verified; no unresolved gate defect**.
This review owns documentation
only and does not run duplicate builds, campaigns or benchmarks. The joint
P1–P5 authorization permits P4 after the passed P3 gate; P5 still waits for P4.

## Dependency and requirements

Inspected `results/p3/phase-gate.json` and independently matched all **42/42**
files in the frozen P3 implementation manifest before P4 edits. INDEX/PROGRESS
record P0–P3 complete and P4 in progress. Reused the master/joint prompt and
approved v1.1 ARCHITECTURE §§3.6/4/5.3–5.6/10, IMPLEMENTATION P4,
VALIDATION V15–V20/V26/V37 plus CC1–CC3, the dated research limitations,
[P4 transaction handoff](../p3/p4-handoff-review.md) and
[independent pressure derivation](../p3/p4-pressure-fixture-plan.md).

Core source reading is reused from the recorded original-source ledgers. The
bounded allocator-API inspection below adds a measurement method, not an Aria
detail or another system's implementation guarantee. Jane Street's shared-block
observation supplies context. The project
expiry heap, generation checks, transactions and recount algorithms are
independent design choices governed by the approved contracts.

## Required source and evidence audit

| Area | Required property | Current status |
|---|---|---|
| Layout/config | 32-B SoA metadata, u32 entries, checked allocation products and ID sentinels, power-of-two B | Source and preset evidence inspected; passed |
| Publication | Checked sizes/positions, all resources/generation changes prepared before retention or membership changes; commit cannot allocate/reject | Source and preset evidence inspected; passed |
| Expiry | Min-heap keyed last_pos/id/gen, late partial seals, equality retained, stale open sweep and declared work | Source and preset evidence inspected; passed |
| Cursor safety | Common completion/expiry before metadata access, generation checks, stable IDs and reacquired filters after intern | Source, preset and CC2 evidence inspected; passed |
| Sizing/pressure | Generic16 vs enforced32; adequate bound tested; ForceEvict loss independently checked; RejectPublish unchanged observables | Source, unit and golden fixture evidence inspected; passed |
| Accounting | Exact live/stale/open/sealed/free slot identity, metadata/heap/list reserved bytes and high-water; independent entry/ring recount | Source, preset and allocator-observation evidence inspected; passed |
| V15–V20/V37 | Release and ASan/UBSan required unit/regression cases, zero failures/reports | 121/121 passed in each preset |
| CC2 | k1 indexed 1,000×10,000 release and 200×10,000 sanitizer operations | Full required campaigns passed |
| V26/F3 | Fresh indexed ≥1,800 monotonic seconds, final stats; actual pressure/recycling seed and independent expected states | Named-seed smoke and final timed gate passed; independent terminal audit below |

The hand-computed N1/B1/C64 fixture was independently checked before code:
payloads10,4,8,0,8 yield DATA starts0,32,64,88,104 and tails0,32,56,88,104.
Capacity loss is zero; cumulative pressure bytes0,32,56,88,104 include PAD8 at
step4. A stale unread/empty-candidate replay must FellBehind; an exact-final
checkpoint{1,32} must become Done even after tail56 exceeds its upper32. These
are now implemented and exercised by unit/smoke checks; the separate timed gate
also passed as audited below.

## Findings

Read `index/index.{hpp,cpp}`, all 18 index unit cases, `engine/engine.{hpp,cpp}`,
17 engine-index cases, the adapted differential campaign and F3 pressure fixture.
The SoA/min-heap, strict expiry, wide-before-narrow deltas, generation preflight,
prepared nonallocating commits, per-batch cursor seek/filter reacquisition and
independent slot/ring recount are implemented consistently with the contracts.
No concrete valid-state defect was found in these mechanisms during this pass.
Historical high-water is tracked separately in tests; recount does not pretend
to recover history from current arrays. The generation preflight counter may
record actual rejected-attempt work; record/retention/membership stays unchanged.

One campaign declaration defect was found and corrected before gate runs: its
39-partition bound counted three roots/twelve symbols but omitted two partitions
interned by `Exact(absent/symbol/family)`. The author raised the bound to41 and
corrected the source ledger. Full CC2 must use the rebuilt campaign. F3's
separate ample-pool bound still covers its smaller declared topic universe.

The pressure fixture matches the independent golden heads/tails, generation and
DATA/PAD loss arithmetic, uses genuine N1/B1 ForceEvict/RejectPublish, and checks
stale-reader/empty-candidate expiry plus exact-final Done before expiry. Review
requested fresh Scan and Indexed delivery checks after each forced publication
to compare the latest expected seq/pos/topic/payload; structural checks alone
would not establish pressure-specific output bytes. Root added those checks
before the final named-seed smoke and timed binary freeze; they were inspected.

Independent decoding found two historical P3 seed names no longer match their
meaning under the P4 selector map `[0,1,4,5,6]`: `late_topic.ops` selects md/A
rather than the newly created future descendant, and `overlap_equal.ops`
selects the future subtree rather than its repeated A events. Core grammar can
still generate future/equal cases and the full CC2 generator tests overlapping
terms. Root was asked to preserve those historical files and add corrected
indexed future/equal seeds, then smoke the additions. Root added
`late_topic_indexed.ops` (choice3, completed zero-output snapshot then reopen at
its checkpoint) and `equal_events_indexed.ops` (choice0, eight equal A events
with captured-upper/batching checks). Both bytestrings were independently
decoded and their isolated smoke passed3 runs over2 files. The binary/frozen
source did not change; normal corpus growth loads the added inputs into later
timed segments. [Seed identities](seed-selector-review.json) and
`indexed-selector-seed-smoke-20261018T102831.576885Z.*` preserve this correction.
Genuine N1/B1 pressure and B2 block-recycling seeds also decode correctly. The
copied overlap filename is not evidence of Indexed overlap coverage; unit/CC2
checks supply that evidence.

## Allocator measurement boundary

The exact portable `Memory` subtotal and false measurement flag are honest, but
do not by themselves satisfy VALIDATION §8's full `index_bytes` metric or the
brief's explicit allocator-overhead measurement. Preparation notes cannot waive
that requirement. Root added a separate supported process diagnostic while
leaving ordinary Index allocation/accounting portable.

Inspected installed `/usr/include/malloc.h` with runtime **glibc2.43**, the
[official glibc manual §3.2.3.10](https://sourceware.org/glibc/manual/latest/html_node/Statistics-of-Malloc.html)
(mallinfo2 fields/API), its [malloc tunables section](https://sourceware.org/glibc/manual/latest/html_node/Memory-Allocation-Tunables.html)
(cache/reservation behavior; no tuning proposed), and Linux man-pages6.19
[mallinfo DESCRIPTION/BUGS](https://man7.org/linux/man-pages/man3/mallinfo.3.html).
The manual separates arena/free/mmap allocation fields; the man-page warns about
visibility beyond the main arena. A fresh, single-thread child avoids the
multi-arena interpretation. An attempted raw glibc2.43 source-tag URL returned
404: no allocator source code or unverified code revision was inspected/copied.

Reviewed `tools/tiplog_index_memory.cpp`: all parsing/output setup precedes a
mallinfo2 baseline; a heap-owned Index and fixed publication schedule are the
only dynamic work inside the boundary; the second snapshot precedes stats,
recount and serialization. It reports raw snapshots, Δ(uordblks+hblkhd),
Δ(arena+hblkhd), exact requested/reserved Index bytes including its heap-owned
control object, and their signed difference. This is an observed allocator
process delta including retained cache/chunk effects, not exact per-object
headers, RSS or a portable guarantee. ASan/preloaded allocators are excluded.
No negative difference is silently clamped. Actual observations are audited
below; they apply to their recorded profiles and do not supply universal
per-object allocator overhead constants.

Review requested power-of-two capacity validation and explicit checked arithmetic
for delta sums/subtraction before source freeze. Root implemented both and the
revised source was inspected. Those are small diagnostic robustness fixes, not
a new dependency or core semantic change.

## Actual central evidence inspected

| Check | Exact record | Result |
|---|---|---|
| Release units | `release-tests-acceptance-20261018T102114.926835Z.*` | 121/121 passed |
| ASan/UBSan units | `sanitizer-tests-acceptance-20261018T102159.962687Z.*` | 121/121 passed, leak/UB checks retained, no report |
| Release indexed CC2 | `differential-release-20261018T102114.926562Z.*` | 1,000×10,000=10,000,000 operations, digest6829017336242550623; 1,520,290 effective Indexed opens |
| Sanitizer indexed CC2 | `differential-sanitizer-20261018T102212.890026Z.*` | 200×10,000=2,000,000 operations, digest16949707518257013035; 303,957 effective Indexed opens; no report |
| Final named F3 smoke | `fuzz-named-seeds-final-20261018T102323.967306Z.*` | 9 named seeds/10 runs passed with final stats |
| Allocator observation B256 | `memory-allocator-B256-20261018T102300.009793Z.*` | Exit0; charged500,256 − reserved495,497 = observed4,759 bytes |
| Allocator observation B1024 | `memory-allocator-B1024-20261018T102300.026336Z.*` | Exit0; charged1,109,344 − reserved1,103,561 = observed5,783 bytes |

Allocator observations each use a fresh glibc2.43 process, logical C1MiB,
100,000 publications and100 partitions, with no GLIBC_TUNABLES present. Raw
snapshots independently reproduce both charged deltas and signed differences.
B256 Δuordblks29,216 + Δhblkhd471,040 =500,256; B1024
19,808+1,089,536 =1,109,344. No RSS/per-object/generalized-overhead conclusion is
drawn. The ordinary portable subtotal remains explicitly separate.

## Final indexed F3 audit

At 2026-10-18 10:54 UTC, independently audited
`F3-indexed-segmented-gate-20261018T102347.429747Z.json` after its terminal
`passed` checkpoint. Actual accepted time was **1,801.3472198700003 monotonic
seconds**, across **15** clean segments and **81,399** executed units. There
were no interrupted/failed segments, active attempt or failure artifacts.

Executed a read-only Python audit importing `scripts/run_fuzz_gate.py` and
calling `verify_completed(summary)` and `verify_corpus(corpus, checkpoint)`.
Additional explicit assertions checked terminal status/time, every segment's
exit0/positive final statistics, required final-stats flag, phase/CPU6,
`TIPLOG_FUZZ_MODE=indexed`, ASan `detect_leaks=1:abort_on_error=1`, UBSan
`print_stacktrace=1:halt_on_error=1`, runner/binary identities and all frozen
source hashes. The audit exited0:

- All15 completed log SHA-256 hashes and final-stat dictionaries matched.
- All964 checkpointed corpus files survived with their recorded hashes,
  including the corrected indexed future/equal seeds added during the run.
- The immutable fuzz binary matched
  `8daeabbdae26f69ddcd97d8b4e0001c6c85158d96252d332686b2bdfdf37f241`.
- The runner matched
  `4ac054b12770d91726813ef79fd53788536a5adce61314aa6eed421ac43e12cc`.
- All **49/49** files in `implementation-freeze.json` still matched, before
  any P5 source edits. Peak recorded RSS was717MiB; the largest absolute
  wall/monotonic discrepancy was0.000004532s, with no material clock jump.

The timed gate supplements the already audited release/sanitizer units, full
CC2 campaigns, exact recount and bounded allocator observations. No required
P4 check remains unrun in this review. Root records the authoritative phase
gate before automatically starting the authorized P5 scope.
