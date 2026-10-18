# P4 implementation preparation: transactional index publication

2026-10-17, read-only design audit while P1 gates run. **No P4 implementation or acceptance is claimed.** This restates ARCHITECTURE §§5.3–5.5 / INV-I*, INV-P*, DD-06/07/08/17 and V15–V20/V37. It adds no scope or source dependency. Source context and reading limits are in [review-sources.md](review-sources.md).

## Minimal implementation structure

- Fixed-size `BlockMeta[N]` plus separate `uint32_t entries[N*B]`, allocated at index construction with checked multiplication. Keep the 32-byte metadata layout and block-ID free list. Index cursors hold IDs/generations, never vector iterators or metadata pointers invalidated by reserve.
- Per partition: first/last block IDs and an ordered block-ID vector with a first-live offset. Binary search only its live window. Compact the dead prefix before a push when useful; uint32 moves cannot throw. Reserve growth during preflight. A custom circular vector is also valid, but is unnecessary for the first implementation.
- Expiry min-heap capacity can be reserved for **N entries once**: each allocated sealed block appears exactly once, and no stale duplicate heap entry is necessary. Heap node key is `(last_pos, block_id, generation)`.
- No separate sealed flag is required if carefully maintained: after a completed mutation a block is sealed iff it is full or has a successor. A partial block seals only when a prepared successor is allocated. An explicit side flag is also valid if counted in memory; do not silently enlarge the documented 32-byte metadata.
- Checkpoint storage is fixed at ring construction using generic minimum DATA=16, or the explicitly enforced ITCH minimum=32. Its capacity must be guaranteed before any publish commit.

## Publication preflight and commit

An implementable split is `plan_append(...) -> PreparedAppend` followed by a nonallocating `commit(prepared,...)`. The prepared object contains values/IDs, not copied whole index state. The single-threaded engine makes the prepared plan stable until its immediate commit.

Keep the normal path cheap: if the target has room or a free block already exists, inspect only that target/free ID plus the ring's eviction prefix. If a fresh block is needed with no free ID, the sealed heap root immediately proves whether any sealed block will expire at the proposed tail; scan open blocks only on the declared sweep/pressure path. Do not copy or scan the complete heap/pool for every publish. A rare global “allocated block has maximum generation” flag can trigger the extra generation-limit preflight scan only in near-limit states; ordinary generations need no all-pool pass.

1. Validate topic/partition ID, payload/alignment/max-record limits, final sequence/packed position and all arithmetic. Calculate PAD and final DATA position before inspecting index delta requirements. Unknown topic creation belongs to registry preflight; accepting an already interned topic ID makes index publication simpler.
2. **Dry-run capacity eviction** over ring headers, computing prospective tail position/sequence and DATA/PAD eviction counts without changing them. Call the result `capacity_tail`. Preserve this baseline so later pressure loss is distinguishable from ordinary overwrite retention.
3. Inspect index metadata against this prospective tail. Sealed blocks with `last_pos < prospective_tail` and fully expired open blocks are reclaimable. Determine whether the target's final block survives and accepts the new position/count, or whether one fresh block is required. Compute delta in uint64 before narrowing. Expired target open blocks are freed/replaced, never extended with a new distant record.
4. For **RejectPublish**, guarantee a free/reclaimable block, or conservatively reject now. A conservative rejection before hypothetical reclamation is allowed by the approved contract; an implementation that identifies safe reclaimable IDs accepts more requests. Rejected publication must not first evict/sweep/reclaim observable membership.
5. For **ForceEvict**, first include every already expired open block in the pressure sweep. If a new block is still unavailable, choose an allocated block with the smallest `last_pos` (heap root for sealed candidates; inspect open blocks). Advance the planned FIFO tail through the DATA at that last position so the block becomes entirely expired. This may discard records in other partitions: count that extra loss. Recompute target-block survival and block requirements against the final planned tail. N=0 is invalid configuration; if one new block is required, freeing one allocated block is sufficient.
6. Preflight generation increments for every planned free. `UINT32_MAX` cannot silently wrap; a synthetic near-limit state must reject with RepresentationLimit before any tail movement. Reserve the target block-ID vector's needed append slot and any partition-container growth; heap capacity is already N. Preflight checkpoint resources as well. Allocation failure here leaves sequence/retention/record/index membership unchanged.
7. Commit performs only header reads, memcpys, integral/ID updates, in-capacity vector pushes/compaction, and heap sift operations. Apply the planned tail, reclaim/sweep the planned blocks, write PAD/DATA, append the index entry, update checkpoint/head and counters. No resource rejection or allocation is permitted after the first eviction. Counters record separate capacity and pressure evictions. An internal assertion can check that the exact planned block and capacities are available.

Preflight reserve may increase unused backing capacity even if a later preparation allocation fails; this is not published record/index membership. If memory gauges expose that capacity change, record it honestly rather than asserting byte-for-byte equality of all allocator state. V19's required unchanged observables are log sequence/retention/content/index membership/history, with no commit-stage resource rejection. Successful reserve must never be confused with block allocation/high-water membership.

## Late seals, expiry and generations

- Compute `(new_pos-base_pos)>>3` in a wide type. Seal when it reaches the configured span limit or count B, then append a prepared successor. Recompute delta for that successor.
- Do not use a seal FIFO. Example: old open A has last position 64; newer B fills/seals with last position 128; later append to A at 256 exceeds a reduced test-only span, sealing old A with last position 64. The heap must expire A before B despite insertion order.
- At `reclaim(tail)`, pop only entries with `last_pos < tail`, assert the recorded generation/current first block, detach exactly once, increment generation exactly once, and put the ID on the free list. Equality at tail remains retained.
- An expired open block must be its partition's sole block. Sweep on configured eviction cadence and before declaring pressure. The sweep cadence and O(P) work are explicit counters/configuration, not hidden free work.
- Validate cursor common replay checkpoint before touching index memory; cached minimum position and generation are additional defenses. A cursor that references a recycled block cannot consume its replacement entries.
- The sizing bound `ceil((C/r_min)/B)+2P+1` applies only when C is below the **production** delta span. Reduced test-only delta width intentionally allows more partial blocks and does not inherit that no-pressure guarantee. Report that test configuration separately. Enforced min payload/record size must reject smaller records before mutation if r_min=32 is selected.

## Exact slot gauges and independently checked memory

Use the following global conservation identity, including free capacity:

`N*B = live_entries + expired_allocated_entries + open_slack + sealed_partial_slack + free_block_slots`.

- `allocated_entries = sum(count)` over allocated blocks; `live_entries` equals retained DATA count; `expired_allocated_entries = allocated_entries-live_entries` because every retained DATA has exactly one entry. This permits O(1) global accounting per eviction without decoding a partition entry for each evicted record.
- `open_slack = sum(B-count)` over open blocks; `sealed_partial_slack = sum(B-count)` over sealed blocks; full sealed blocks add zero. `free_block_slots = free_blocks*B`. Increment allocation/free/seal gauges from metadata counts, and maintain block high-water separately from cumulative allocation/free counts.
- Account **reserved** storage, including free blocks, not only used entries: metadata array capacity, entry array capacity, heap capacity, per-partition state/container capacity and dead-prefix/vector capacity, control objects and extra test/flag arrays. Expose current sizes and reserved capacities so heap/list slack is not hidden.
- A brute-force recount must walk free list, partition chains, all allocated entry positions and heap nodes independently of incremental gauge helpers. Separately scan retained ring DATA to prove one matching partition entry per record. Check ownership/disjointness, generations, heap membership/minimum, strictly increasing chains, and exact slot conservation after mutations.

**Allocator measurement boundary:** portable C++20 does not expose per-allocation allocator headers/arena overhead. Required requested/reserved bytes and slot gauges can be exact. For later memory reporting, capture allocator usable-byte slack with a compatible explicitly owned allocator, or a declared process-level allocator measurement; include its coverage/limitations. Do not label `vector.capacity()*sizeof(T)` as measured allocator overhead or silently call the resulting subtotal total process memory. This is a measurement-method choice to document, not grounds to change the index contract or add a dependency.

## Gate cases to insist on

| Test | Required adversary/evidence |
|---|---|
| V15 | Tiny N/B, repeated allocate/free, free+allocated=N, no duplicate ownership, exact generation increments and synthetic generation exhaustion |
| V16 | Brute retained-ring listing versus decoded index entries after wrap, multiple partitions, full and partial blocks |
| V17/V37 | The late partial seal above; tail equal to last_pos; stale sole open block; every gauge versus independent recount and exact slot conservation |
| V18 | B=1/2, cursor block reused, common FellBehind before dereference, stale generation never read |
| V19 | Reject after hypothetical capacity/pressure eviction would be tempting: before/after seq/tail/content/index equality. ForceEvict counts its extra whole-record loss. Adequate sizing avoids pressure with generic16 and enforced-ITCH32 workloads |
| V20/V26 | Indexed k=1 versus independent oracle, required seeded operation count and 30-minute F3 phase gate, in release/sanitizer configurations as specified |

Keep pressure-policy verification independent too: an oracle can independently model the declared tiny-pool policy, or use an explicitly supplied pressure-eviction operation in a schedule whose expected boundary is separately hand-checked. Simply setting oracle retention to whatever tail the engine reports would hide an incorrect pressure decision. The ample-pool differential campaign still exercises independently computed capacity retention; separate tiny-pool V19 cases must cover the intentional shortening and rejection policies.

No additional scope amendment is required for these routine choices. Do not introduce concurrency reclamation, tagged entries or a different feasible representation to simplify P4.
