# P4 API and transaction handoff review — 2026-10-18

**Design preparation only, while P3's timed F3 gate is pending. No P4 code or
acceptance is claimed.** Reuses [the earlier preparation](../p1/p4-review-prep.md),
ARCHITECTURE §§5.3–5.5/10 and VALIDATION V15–V20/V26/V37. The original-source
reading limits in [review-sources.md](../p1/review-sources.md) remain unchanged.
No new paper, dependency, concurrency mechanism or scope is proposed.

## Integration boundary

The existing `ring::Ring` already offers the necessary transaction primitives:
`dry_run(payload_bytes, minimum_tail)` returns immutable `Layout` values;
`plan_append(payload, minimum_tail)` also owns any alias copy; and
`commit(Plan&&,topic) noexcept` performs no allocation. Fixed checkpoint storage
is prepared at Ring construction. `minimum_tail` must be an existing retained
item boundary or head; `Layout` separately counts capacity and pressure loss.

Keep the new index independent of payload encoding, registry mutation and ring
physical layout. A minimal conceptual interface is:

```cpp
// Illustrative design, not compiled or mandated spelling.
prepare_append(partition, new_data_pos, prospective_tail, partition_count)
    -> PreparedAppend or NeedTailThrough{last_pos};
commit(PreparedAppend&&, published_pos, retained_data_count) noexcept;
seek(partition, lower_pos) -> Cursor{block, generation, entry, cached_pos};
advance(Cursor&) -> next cached position or exhausted;
stats(); recount(); check_invariants();
```

`PreparedAppend` contains IDs/values and guarantees target seek-list capacity,
heap capacity, free/reclaimable block availability and all generation changes.
It is single-use and cannot survive another mutation. Do not clone the pool,
heap or index for every publication. Lazy empty partition-state growth is fine:
reserve/construct it during preparation, before any published membership or tail
changes. The registry's P2 observer/ID rejection guarantees remain intact.
Existing Registry topic IDs are one-based (zero invalid), while partition IDs
are zero-based (zero valid). UINT32_MAX is the free-owner sentinel, not a valid
partition ID; default max_partitions counts possible IDs0…UINT32_MAX−1.

An Engine publication can use these steps without changing P3 semantics:

1. Validate the already interned topic ID and obtain its partition. Enforce an
   optional ITCH minimum before any mutation if using r_min32. Call Ring dry-run
   for the capacity-only layout; this also checks sizes and representation.
2. Ask index preparation about the prospective DATA position and capacity tail.
   If no fresh block is needed or one is already free/reclaimable, continue.
   A prepared RejectPublish failure occurs here, before eviction/reclaim/sweep.
3. ForceEvict first considers all already expired open blocks. If it still needs
   a block, index preparation returns the allocated block with minimum last_pos,
   considering both sealed-heap root and open blocks. Only this pressure path
   needs an O(P) sweep. A candidate last_pos≥prospective_tail is retained DATA, so Engine can
   prove its end via Ring at(last_pos), then rerun dry-run with that end as the
   minimum tail. Recompute target survival/allocation at the final tail.
4. Complete index preparation and create the final Ring plan. Either order of
   their remaining allocations is safe while both only prepare; no Ring mutation
   occurs during index preparation, so an aliased payload still copies safely.
5. Commit Ring and index with no intervening public callback and no remaining
   allocation/rejection. Ring commit followed by index commit is valid because
   index reclamation uses metadata positions, never evicted payload/header reads.
   Update index live count from old live − layout.data_evicted + 1, then verify
   against an independent retained-DATA scan in tests.

The final dry-run may repeat the small eviction-prefix walk. It must not copy
the complete ring. `is_boundary`'s linear validation is acceptable on explicit
pressure preparation; it should not turn normal append into a full-ring scan.

Preparation may increase unused vector capacity before a later allocation
fails. Report that reserved capacity honestly; V19's unchanged observables are
sequence, retention, contents, index membership and delivered history. Never
count a capacity reservation as an allocated/live block or conceal membership
mutation behind a preparation name.

## Pool, expiry and generation details

Use fixed SoA `BlockMeta[N]` (static_assert32 B) plus u32 delta entries[N*B].
Check every allocation-size multiplication and B power-of-two configuration.
Free blocks use owner=NONE and the documented free-list link; generation advances
once per actual free. Per-partition ordered block IDs can use a vector with a
first-live offset and nonallocating compaction, plus intrusive `next` links.
Binary search ignores the dead prefix. Reserve its append slot in preparation.

Reserve heap storage for N sealed blocks at construction. Key by
`(last_pos,block_id,generation)`; each sealed block appears exactly once. A full
block seals immediately; a partial block seals only when its successor is
prepared for delta overflow. Deriving sealed status from full-or-successor is
valid, or count explicit side flags in memory. Check uint64 subtraction/shift
before narrowing, then recompute delta against a newly allocated base. A u32
entry represents delta<2^32, covering a 32-GiB byte span.

Reclaim only `last_pos < tail`; equality remains live. After sealed-prefix
reclamation, a fully expired open block must be the partition's sole block.
Preparation reasons about that prospective state; it must not demand the old
unreclaimed chain already be a singleton. Commit reclaims sealed prefixes before
detaching expired opens. Sweep on declared eviction cadence
and before pressure, with sweep counts/work exposed. Normal append can use the
target/free head/heap root without scanning all N blocks. Generation exhaustion
must be preflighted for every block about to be freed; a global near-limit flag
may trigger a rare full scan while ordinary generations need none. Do not wrap
generation or discover an unfreeable maximum generation after Ring commit.

The sufficient no-pressure bound is `ceil((C/r_min)/B)+2P+1` with production
delta span>C. P is the configured/registered partition bound used for the claim,
not an unexplained workload estimate. Dynamic partition growth must update the
reported bound; small pools remain valid under their explicit pressure policy.
Generic opaque records use r_min16. Claiming r_min32 requires enforced minimum
record sizing. Reduced test-only delta spans intentionally invalidate this
no-pressure argument and must be labeled accordingly.
P1's volume-table P counts message-bearing partitions. Registry ancestors can
also create unused one-segment partitions (for example `itch`), so do not
silently substitute the volume-table count for a bound on registered state.

## Cursor and replay integration

P4 needs one-partition indexed replay and empty/exhausted cursor handling. Store
IDs/generation/index and cached logical position, not invalidatable vector
iterators. Seek first by a live block's last_pos, then by decoded entries.
Likewise, do not retain a `CompiledSubscription::filters()` span or
`PartitionFilter*` across registry mutations: P2 explicitly invalidates these
views on `intern()`. Between batches new topics may grow/reallocate filters.
Store partition IDs and reacquire the filter from owned compiled state when
needed; no mutation interleaves within a single batch.

Every positive batch performs P3's completion-before-expiry and conservative
unread checkpoint check **before** cursor metadata access. Cached position<tail
also means stale; generation must match before advance or following links.
Cursor exhaustion does not authorize budget-boundary look-ahead: a full output
batch still returns More immediately after its last delivered DATA, while an
exhausted positive batch advances to captured upper. Preserve the retained-tail
PAD checkpoint regression added in P3. Do not alter oracle matching/retention
to accommodate index behavior.

P5 owns multi-partition kernels/Auto/Tail. Its later Tail re-arming must seek
freshly for the next captured range; a permanently exhausted old cursor cannot
silently miss new entries or topics. Wide terms remain served through scan.

## Recount and adversaries

Keep this exact slot identity:

`N*B = live + expired_allocated + open_slack + sealed_partial_slack + free_slots`.

Recount independently walks free IDs, partition chains, entries and heap; it
does not call incremental gauge helpers. Separately enumerate retained Ring
DATA and compare exactly one entry per record/partition. Report fixed metadata,
entry capacity, free storage, heap used/reserved, partition/list used/reserved,
side arrays, control objects, allocations/frees/seals/sweeps, requested/reserved
bytes and high-water. Portable container capacity is not measured allocator
overhead; label its coverage/unknowns or separately measure an explicitly
supported allocator/process boundary.

| Check | Required concrete adversary |
|---|---|
| V15 | B1/B2, tiny N, repeated free/reuse, free+allocated=N, generation increments exactly once; near generation exhaustion rejects before retention/membership changes |
| V16 | Multiple partitions, wrap/PAD, full and partial blocks; independent retained Ring records equal decoded postings, each once |
| V17/V37 late seal | With reduced test span, A open last64, B later fully sealed last128, then A append256 seals its old partial block last64. Heap expires A before B despite reversed seal order |
| V17 boundary/open | tail==last_pos remains retained; tail just beyond expires; a cold sole open block is swept; target's expired open block is replaced instead of extended |
| V17 accounting | Before/after full seal, partial seal, reclaim, sweep, reserve growth and pool reuse, recount every slot/byte gauge and high-water; include expired allocated entries separately |
| V18 | Cursor references a B1/B2 block later freed/reused for another partition. Replay returns common FellBehind before dereference; new owner data is never delivered |
| V19 rejection | No free block, temptation to evict/reclaim first, RejectPublish. Snapshot head/tail/sequences/retained payloads/index membership/generations before and after; no commit-stage rejection |
| V19 force | Hand-computed tiny pool loses extra whole records from other partitions; count extra DATA and PAD bytes separately from ordinary capacity loss |
| V19 sizing | Generic16 and enforced32 synthetic workloads at adequate production-span bound have zero pressure; smaller generic records are rejected by enforced32 configuration before mutation |
| V20/V26 | Ample-pool k1 oracle campaign at fixed CC2 counts, release/sanitizer, invariant checks after every operation, plus required fresh30min F3 indexed gate |

Pressure verification must be independent: either separately model the declared
policy, or hand-check a supplied pressure schedule's boundary. Copying the
engine's reported tail into the oracle would hide an incorrect policy. Keep
the ample-pool differential campaign's independently derived capacity retention
and use separate strong tiny-pool pressure tests. No acceptance threshold is
changed by this handoff.
The F3 seed specification also explicitly names pool pressure/recycled blocks.
Ensure a pressure seed actually reaches a pressure case: use an independently
modeled policy or a separately hand-checked explicit pressure schedule/fixture
branch. An ample-pool-only target cannot claim pressure coverage merely from a
seed's filename. Capacity-based block recycling is still useful independent
coverage, but does not replace this declared pressure adversary.

## Independently checked proposed pressure fixture

Reviewed [the fixture plan](p4-pressure-fixture-plan.md) before P4 code exists.
For C64/max32/N1/B1, alternating A/B payloads10,4,8,0,8 produce DATA
sizes32,24,24,16,24; starts0,32,64,88,104; heads32,56,88,104,128; and forced
tails0,32,56,88,104. Capacity floors0,0,24,40,64 never exceed the old tail,
so capacity evictions are zero. Cumulative pressure DATA bytes are
0,32,56,80,96; evicting PAD56–64 at step4 makes total pressure bytes
0,32,56,88,104. These expectations come from arithmetic and the declared
one-block policy, not an index implementation's answers.

With an explicitly initialized generation0, block generation=step−1,
allocations=step, frees=step−1 and high-water1. An A replay left unconsumed at
step1 must FellBehind after step2; an empty B candidate must use that same
conservative unread checkpoint. An exact-budget A replay at checkpoint{1,32}
must become Done after step3 even with tail56>upper32. RejectPublish step2 has
physical space still available and thus isolates pool pressure; it must retain
seq1 and unchanged index membership/generation. These are planned fixture
assertions only, not executed results.
