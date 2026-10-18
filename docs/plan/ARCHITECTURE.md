# ARCHITECTURE — semantics, interfaces, invariants, data layouts, algorithms

Plan version **v1.1** · 2026-10-17 · **Tier B design approved; P0 complete; P1–P5 jointly authorized and executing in dependency order.** P6–P8, Tier C and roadmap work remain outside this authorization. Labels follow RESEARCH §0: [A] article, [V] verified, [I] inference, [D] design choice, [S] assumption, [H] hypothesis, [Q] open question. Source IDs (S01…) refer to the RESEARCH ledger. §13 records this refresh and supersedes the corrected v1.0 contracts. Current implementation and executed gate evidence are in [PROGRESS](PROGRESS.md); design descriptions alone do not establish completion.

Working name: **`tiplog`** (C++ namespace `tiplog`, Python package `tiplog_py`). The name can be changed at approval.

---

## 1. Scope and execution model per milestone

| Milestone | Execution model | Claims allowed after its gate | Explicitly not claimed |
|---|---|---|---|
| **Core (P0–P8)** | **Deterministic, single-process, single-threaded engine.** Publisher and subscribers are in-process objects driven by a trace-replay driver. Offline C++ optimizer; Python tools. | Correct exact/subtree catch-up against an oracle; CPU-work and timing comparisons on one pinned core; memory accounting; modeled storage-layout costs | Networking, concurrency, durability, crash safety, measured disk I/O |
| R1 | Same engine plus a write-ahead log (WAL) on disk; still single-threaded | Recovery returns a prefix of the published stream under the tested crash-state model; fsync discipline | Power-loss safety (unless R8); multi-process access |
| R2–R3 | Plus compaction into subtree store packs, manifest, disk recovery and handoff to the tip; measured I/O | Measured cold/warm recovery cost per layout | Distributed guarantees |
| R4 | One writer thread and N reader threads in one process | Concurrent catch-up correct under TSan-instrumented stress; measured scaling | Cross-process or network |
| R5 (optional) | TCP service | Wire protocol and slow-consumer policy as tested | Production readiness |

Roadmap milestones are **not authorized** by approving this plan (see IMPLEMENTATION_PLAN §7).

---

## 2. Workloads, topic hierarchy, consumers

### 2.1 Primary hierarchy: derived from the ITCH spec's section structure [D]

Topic = `itch/<SYM>/<family>/<type>`, where the families mirror ITCH 5.0 §1.2–1.8 (S05). A user who follows the spec's own grouping would plausibly choose this tree without knowing anything about storage internals.

| ITCH | Topic | | ITCH | Topic |
|---|---|---|---|---|
| R | `itch/<SYM>/stock/directory` | | E | `itch/<SYM>/modify/executed` |
| H | `itch/<SYM>/stock/trading_action` | | C | `itch/<SYM>/modify/executed_px` |
| Y | `itch/<SYM>/stock/reg_sho` | | X | `itch/<SYM>/modify/cancel` |
| L | `itch/<SYM>/stock/mp_position` | | D | `itch/<SYM>/modify/delete` |
| K | `itch/<SYM>/stock/ipo_quoting` | | U | `itch/<SYM>/modify/replace` |
| J | `itch/<SYM>/stock/luld_collar` | | P | `itch/<SYM>/trade/noncross` |
| h | `itch/<SYM>/stock/op_halt` | | Q | `itch/<SYM>/trade/cross` |
| A | `itch/<SYM>/add/anon` | | B | `itch/<SYM>/trade/broken` |
| F | `itch/<SYM>/add/attributed` | | I | `itch/<SYM>/noii` |
| S | `itch/_market/system_event` | | N | `itch/<SYM>/rpii` |
| V | `itch/_market/mwcb/decline_level` | | O | `itch/<SYM>/dlcr` |
| W | `itch/_market/mwcb/status` | | | |

**Routing rules.** The spec does not put a symbol string in every message [V].

| Message types | Routing |
|---|---|
| S, V, W (locate 0, market-wide) | `itch/_market/...` |
| K (locate "Always set to 0", has a symbol) | By its **symbol** |
| E, C, X, D, U, B (locate only) | Through the locate → symbol directory built from `R` messages |
| A, F, P, Q, I, N, O, H, Y, L, J, h, R (locate and symbol) | By locate. The symbol is cross-checked against the directory and mismatches are counted (expected 0, measured). |
| Unknown locate | `itch/_unmapped/L<locate>/<type>`, counted (expected 0) |

**Segment encoding.** Trailing spaces are trimmed. Characters outside `[A-Z0-9.]` are percent-encoded; the spec allows "." delimiters in symbols (App. B).

**Partition.** A partition is the first two segments, so there is one per symbol (`itch/<SYM>`) plus `itch/_market`. Topics with fewer than two segments form their own partition.

### 2.2 Why not `itch/<SYM>/<type>` (and what the baseline really does) [D]

With a three-segment tree like `itch/AAPL/add`, the article's three-segment rule (A15) already puts every exact topic in its own store. Exact-topic filtering waste is then zero by construction, and adaptive splitting can only *merge* stores (fewer stores, more waste). This plan **never claims waste reduction for that hierarchy**. It appears only as sensitivity case **H-flat** (L5).

Under the primary hierarchy, the baseline stores are one per `(symbol, family)`, plus `noii`, `rpii`, and `dlcr` per symbol. The `modify` store mixes E, C, X, D, and U:

- An **execution-tape** consumer reads E and C, so it must filter out X, D, and U. Whether D, U, and X dominate `modify` bytes is **[H], to be measured in L1**; no number is assumed.
- A **status** consumer reads `stock`, which includes start-of-day R and L spins.
- **Book** consumers read whole families, so they waste nothing under the baseline. Adaptive layouts can hurt them by touching more stores.

That two-sided trade-off is the experiment.

**Splitting is confined to each two-segment partition (one symbol).** Stores never span symbols in the core model (I-6). Cross-symbol bundling of cold partitions is a *different feasible set* (R10) and is never mixed into core results.

### 2.3 Consumers and subscriptions

| Class | Purpose | Terms for symbol S |
|---|---|---|
| BOOK | Reconstruct the complete Nasdaq order book for S | `Subtree(itch/S/add)`, `Subtree(itch/S/modify)`, `Subtree(itch/S/stock)`, plus `Subtree(itch/_market)` |
| TAPE | Executions and prints (TCA, VWAP, realized volatility) | `Exact(itch/S/modify/executed)`, `Exact(itch/S/modify/executed_px)`, `Subtree(itch/S/trade)` |
| AUCT | Open/close auction analytics | `Exact(itch/S/noii)`, `Exact(itch/S/trade/cross)` |
| STAT | Halt, LULD, and Reg SHO monitor | `Subtree(itch/S/stock)` |
| REPLAY | Multi-instrument full replay (research infrastructure) | `Subtree(itch/S)` for each S in a basket |

Book reconstruction needs data **from session start** (orders added earlier are otherwise unknown). Executions follow the spec: E + C + P are non-cross executions and Q carries crosses, and downstream code must honor C's printable flag. Trade-only data, such as Binance, **cannot** reconstruct books.

**Workload sets for the optimizer [S]:** chosen to span plausible mixes. Results are always reported per workload, never for "the" workload.

| Set | Definition |
|---|---|
| W0 | Article lens: every non-empty topic read once by an exact read |
| W1 | Uniform: for every symbol, one BOOK, TAPE, AUCT, and STAT consumer (f = 1) |
| W2 | Activity-skewed, by message-count rank r: BOOK and TAPE f = 10 (r ≤ 100), 1 (r ≤ 1000), else 0; AUCT f = 1 (r ≤ 1000); STAT f = 1 for all |
| W3 | Replay-heavy: REPLAY baskets (top-100 and random-100) plus W1 at weight 0.1 |

### 2.4 Secondary workload: Binance spot trades [D]

- Topics are `bnc/<SYM>/trade/{buy,sell}`, with the aggressor side derived from `isBuyerMaker` (`true` means a seller-initiated trade). Partitions are `bnc/<SYM>`.
- The global order is **constructed** by (time µs, symbol, trade id); it is not an exchange sequence.
- Use it for tip-index experiments with many partitions and heavy skew (T1/T3/T5 variants). It is **not** used for book reconstruction or for split studies, because a two-leaf tree per partition makes them degenerate.
- Tier C only (IMPLEMENTATION_PLAN §1).

### 2.5 Dataset facts and resource limits [V] (S08, S47)

- **Primary dataset:** `12302019.NASDAQ_ITCH50.gz`, 3,524,013,057 B gzip (listing rechecked 2026-10-17). Its exact decompressed size is unknown: gzip ISIZE is per member modulo 2³², not a bound or a two-candidate choice (S54). P1 measures the complete stream; it is never stored uncompressed.
- **Optional second day:** `S120825-v50.txt.gz` (8.78 GB gzip; DEC-3).
- **Local disk:** 30 GB free, so raw files, trace windows, and results fit with a margin.
- **RAM:** 14 GiB, so rings are capped at 2 GiB and a typical experiment uses 1 GiB of ring plus 1–2 GiB of trace.
- **Coverage:** Nasdaq's own book only (S05). The sample's license status is unknown, so there is **no redistribution** (RESEARCH §3.2).

How skew will be **measured** (not assumed) is specified in VALIDATION_PLAN L1: per-topic and per-symbol counts and bytes, CCDF and Lorenz curves, Gini, family composition per symbol, same-partition run-length distribution in the global stream, per-second burst profile, and per-partition tree size and class count.

---

## 3. Semantics (core engine)

### 3.1 Publication and ordering
- A single publisher calls `publish(topic, payload) → seq`. Sequence numbers are **dense, global, and start at 1**, and they define the canonical total order (as in Aria, S03).
- Payloads are opaque bytes. For ITCH, the payload is the original ITCH message.
- **Position.** Each record also gets a logical byte position `pos`: 64-bit, monotonic, 8-byte aligned, **never recycled**. Within one engine, `pos` and `seq` are strictly co-monotone.

### 3.2 Topics and matching
- A topic is a `/`-separated path of non-empty segments. Topics are created on first publish, or interned when a subscription names them.
- `Exact(t)` matches messages published on `t` only.
- `Subtree(p)` matches messages on `p` itself and on any topic whose path extends `p` at a segment boundary. `itch/AAPL/**` matches `itch/AAPL/add/anon` but not `itch/AAPLX/...`.
- Subtree terms automatically include topics created **after** the subscription.

### 3.3 Subscriptions, overlap, duplicates
- A subscription is a non-empty set of terms with **union semantics**: a message is delivered **at most once per subscription**, however many terms match it.
- Different subscriptions are independent streams, so a message matching two subscriptions appears once in each.
- **Normalization:** drop `Exact(t)` if some `Subtree(p)` with p ⊑ t is present, and drop `Subtree(q)` if some `Subtree(p)` with p ⊏ q is present.
- **Wide terms**, meaning `Subtree` rooted shallower than two segments, can span partitions created later. They are served by scan (§5.6).

### 3.4 Sequence numbers, gaps, positions
- The engine's global sequence has no gaps. A filtered stream naturally skips sequence numbers; that is not loss.
- Loss is **never silent**. A replay either delivers exactly the matching set over its range, or it ends with an explicit error, having delivered a correct prefix (INV-Q3).

### 3.5 Retention
- **Byte-capacity ring, overwrite-oldest** [D] (A3, S12). A record is retained while it lies within the last `C` bytes of the logical log, including padding.
- Eviction is **whole-record** and FIFO.
- Retained range: `[tail_seq, head_seq)` and `[tail_pos, head_pos)`.

### 3.6 Replays: boundaries, outcomes, errors

```
open_replay(sub, after_seq, mode) → Replay   // delivers seq ∈ (after_seq, upper_seq]
```

- **Captured upper bound.** `upper_seq = head_seq − 1` and `upper_pos = head_pos` are captured at open. Records published later are never delivered by this replay (INV-Q5).
- **`HistoryExpired{requested, oldest_retained}`.** Raised at open if `after_seq + 1 < tail_seq`. Nothing is delivered.
- **Common retention checkpoint [D, corrected v1.1].** Every mode keeps `unread_pos` and `resume_after_seq`, independently of `last_delivered`. At entry to a non-complete, positive-budget `next_batch`, raise **`FellBehind{last_delivered, oldest_retained}`** if `unread_pos < tail_pos`, before dereferencing ring or index memory. This intentionally conservative rule includes eviction of irrelevant records and is identical in Scan/Indexed/Auto.
  - Publisher calls cannot interleave inside a batch in the single-threaded core. A full batch checkpoints immediately after its last delivered DATA record; an exhausted snapshot checkpoints at `upper_pos/upper_seq`, including when it delivered nothing.
  - `max = 0` makes no progress. Before checking expiry on a subsequent positive-budget call, return `Done` if already complete **or `unread_pos == upper_pos`**. Thus consuming the final record at an exact output-budget boundary cannot later turn into an expiry error. When a budget fills, all modes may return `More` at the same checkpoint without mode-specific look-ahead; on exhaustion before filling it return `Done`. Completion/checkpoint semantics are uniform across modes.
  - Cached minimum-key and generation checks remain defensive invariants. Tagged entries (R9) do not change expiry semantics without a separate amendment.
- **`Done{upper_seq}`.** Signals completion.
- Requesting from `after_seq ≥ upper_seq` returns `Done` immediately; make this check before computing `after_seq+1` so extreme input values cannot wrap.
- A future-start snapshot (`after_seq > upper_seq`) is an empty query and supplies no reusable progress checkpoint. `open_tail` rejects a future start as `InvalidRange`; it must never lower the requested sequence floor when chaining.

### 3.7 Slow readers and the live tail
- A subscriber's live stream is a **chain of snapshots**: finish the current captured range before opening another at the current head. Resume from `resume_after_seq`, not `last_delivered`; a completed zero-output snapshot still advances to its upper sequence. Cursor reuse/re-arming is permitted only when it is observationally equivalent to this contract.
- Preserve distinct sequence-numbered events even when their payloads/prices are equal or net book state is unchanged. Union deduplication removes duplicate delivery of the **same record**, not equal-valued events (S61).
- **Chaining is exact** (INV-Q6): the concatenation of polls equals one replay over the union range.
- A reader that falls behind `tail_seq` gets `FellBehind`. In the core, recovery is then impossible (no disk), and the error is final for that cursor. With R2, the client switches to disk recovery (§7.6).
- The driver models slow readers as consumption budgets per publish tick, or as pauses followed by catch-up.

### 3.8 Disk recovery → live tip handoff (full version, R2)
Given a request `(sub, after_seq = s)`:
1. Serve `(s, d]` from compacted store packs, then uncompacted WAL segments.
2. After each disk chunk, if `d + 1 ≥ tail_seq`, open a tip replay `after_seq = d`. If the ring has moved past `d + 1` in the meantime, continue from disk. The WAL holds every record ≥ `tail_seq` because of INV-D5.
3. Correctness is the oracle's filtered set over `(s, final_upper]`: no duplicate at the switch (strict `seq > d`), and no gap (every stage covers a contiguous sequence range completely).

### 3.9 Not guaranteed
- In the core: durability, cross-process access, networking, and fairness among concurrent readers.
- In any milestone: exactly-once across process restarts unless R1/R2 tests demonstrate it under the stated crash model.

---

## 4. Module architecture

```
                    ┌──────────────── tools (C++ CLIs) ────────────────┐
                    │ tiplog_sim   tiplog_bench   tiplog_layout          │
                    └──────┬───────────────┬───────────────┬───────────┘
                           │               │               │
 trace files ──► trace_reader ──► engine ◄── merge kernels  layout (model, evaluator,
 (Python converter)          │  ├ ring                     enum, mask-DP, baseline,
                             │  ├ block_pool + part_index  KM-greedy, global alloc)
                             │  └ topics + subscriptions          ▲
                             │                                    │ topic-volume tables
 tests only:  ref::ScanOracle (independent matching + retention model)   (Python analysis)
 roadmap:     storage/ (wal, manifest, compaction, store_pack, disk_reader)
```

| Module | Owns | Depends on | Threading | Resource bound |
|---|---|---|---|---|
| `topics` | Topic registry (path ↔ id, parent, depth, partition, local id) | — | single | O(#topics × (path + ~48 B)) |
| `subs` | Compiled subscriptions (per-partition filters, wide flag) | topics | single | O(#partitions involved + topic bitsets) |
| `ring` | Byte buffer of capacity C, head/tail, checkpoints | — | single | C + (R_max/2^L)·8 B |
| `index` | Block pool, per-partition block lists, sealed-block expiry min-heap | ring positions | single | N_blocks·(4B + 32) B plus expiry heap, per-partition lists, and allocator overhead |
| `merge` | Kernels over k cursors | index cursors | single | O(k) |
| `engine` | All of the above; replay objects reference the engine (non-owning) | all | single | sum of the above |
| `trace` | Trace v1 reader (mmap or read) | — | single | Window size |
| `layout` | Offline model, solvers, evaluator | — | single | O(\|V\|·K·2^b) per partition (DP) |
| `ref` | Oracle (tests) | — | single | Whole trace in memory |

**Ownership and lifetimes:**
- The `Engine` owns the ring, pool, indexes, and registry.
- `Replay` and `Tail` objects hold a non-owning engine reference plus their own cursor state. Debug builds assert they are closed before the engine is destroyed.
- `Delivered.payload` spans are valid **until the next mutating engine call**. Tests and benchmarks copy or checksum immediately.

**Dependencies (planned):**
- C++20 standard library only for the core library.
- Tests: googletest 1.17.0. Microbenchmarks: Google Benchmark v1.9.5.
- Optional: HdrHistogram_c **0.12.1**, subject to reviewing its pinned commit and smoke checks in the authorized Tier C phase; 0.12 releases contain relevant correctness fixes (S57).
- Python: use an explicitly recorded project interpreter/venv. The 2026-10-17 read-only refresh found Python 3.14.4, numpy 2.3.5, matplotlib 3.11.0, and pytest 9.0.2; validate compatibility and freeze dependencies in P0. Historical v1.0 environment claims are not current pins.

---

## 5. Data layouts and algorithms

### 5.0 Trace format v1 (Python writes, C++ reads) [D]

```
FileHeader (64 B, little-endian):
  magic[8] = "TPLTRC\0\1" | version u32 = 1 | flags u32 | record_count u64
  dict_offset u64 | dict_length u64 | source_sha256_prefix u64 | reserved[16]
Record (8-byte aligned):
  topic_id u32 | payload_len u16 | flags u16 | ts_ns u64 | payload[payload_len] | zero pad to 8
Dictionary: u32 n, then n × { topic_id u32, path_len u16, path bytes }
```

- `ts_ns` is ITCH nanoseconds since midnight, or Binance µs × 1000.
- The converter also writes `<trace>.meta.json` (source URL, sizes, SHA-256 of source and trace, window, hierarchy, counts).
- The reader validates every length and offset. It is fuzzed (F1).

### 5.1 Topic registry
- Interning creates missing ancestors.
- The partition of a topic is its ancestor at depth min(2, depth).
- `local_id` is dense per partition (u16) and drives per-partition filter bitsets; reject exhaustion before registration mutation or explicitly select a wider configured representation.
- A topic-creation hook notifies subscriptions whose `Subtree` roots are ancestors (≤ depth lookups) so their filters gain the new local id.

### 5.2 Subscription compilation
- Normalize (§3.3).
- Each term at depth ≥ 2 maps to exactly one partition. Each partition gets a filter: `all` (if a `Subtree` covers the partition root) or a bitset of local topic ids.
- Wide terms set `wide = true`, which forces scan mode.

### 5.3 Ring (tip store) [D] (S11)

Capacity `C = 2^c` bytes (default 1 GiB, maximum 2 GiB on this machine). Records start at 8-byte-aligned logical positions; physical offset = `pos & (C−1)`. **Core precondition:** `16 ≤ max_record ≤ C/2`, aligned to 8. This makes `pad + need ≤ C` in the append algorithm; reject larger records without mutation. Generic zero-payload DATA occupies 16 B, even though valid ITCH records here occupy at least 32 B.

```
RecordHeader (16 B):
  word0  u32  bit31 = PAD; bits[30:3] = size/8 (size multiple of 8, includes header);
              bits[2:0] = fill (alignment bytes after payload, 0..7)
  topic  u32  (DATA only)
  seq    u64  (DATA only)
payload_len = size − 16 − fill
PAD item: only word0 is meaningful; minimum PAD size is 8 B (word0 + 4 reserved bytes)
```

Record sizes for ITCH payloads (16 + payload, rounded up to 8):

| Bytes | Message types |
|---:|---|
| 32 | S, W |
| 40 | D, B, X, Y, N, h |
| 48 | H, L, K, E |
| 56 | R, V, J, A, F, C, U, Q |
| 64 | P, O |
| 72 | I |

**Append and eviction:**
```
publish(topic, payload):                      // returns seq
  need = checked_align8(16 + len(payload)); require need ≤ max_record ≤ C/2
  room_to_end = C − (head_pos & (C−1))         // multiple of 8, ≥ 8
  pad = (room_to_end < need) ? room_to_end : 0
  preflight checked sequence/position limits using pad + need
  prepare/guarantee required block, heap/list and checkpoint capacity; no published-state mutation
  ensure_space(pad + need)                     // evict whole items from tail
  if pad: write PAD{size=pad} at head_pos; head_pos += pad
  write header{size=need, fill, topic, seq=head_seq} + payload at head_pos
  index.append(partition(topic), head_pos)     // dense entry
  ckpt.note(head_seq, head_pos)                // every 2^L seqs
  head_pos += need; return head_seq++

ensure_space(n):
  while head_pos + n − tail_pos > C:
     h = header at tail_pos
     if h is DATA: tail_seq = h.seq + 1
     tail_pos += h.size
  if tail_pos == head_pos: tail_seq = head_seq   // ring empty
  index.reclaim(tail_pos)
```

**Properties:**
- **No record ever straddles the physical end** (INV-R3).
- **Publication transaction:** resource/representation rejection happens before any change to sequence, retention, record/index membership or delivered history. Preflight may conservatively reject under `RejectPublish` if it cannot guarantee resources; commit must not later reject or throw an allocation failure. ForceEvict must determine and account for its pressure policy before commit. The following index pseudocode assumes these prepared resources; V19 checks rejected publication leaves observable log/index state unchanged.
- Eviction reads one header per evicted item. That is O(1) per item, though often a cold cache line; the cost is measured in M2.
- *Alternative considered:* a mirrored virtual-memory ring (`memfd` mapped twice) removes PAD items but is Linux-specific, page-granular, and complicates huge pages. Rejected for the core.

### 5.4 Sequence ↔ position
- **Checkpoint fast path:** resume with `ResumeCheckpoint{after_seq, next_pos}` from §3.6; `next_pos` is an item boundary, possibly PAD or the snapshot's upper boundary, not necessarily a DATA start. Validate range, sequence/boundary consistency, and expiry before using it. A delivered `(seq,pos)` remains a record locator, not a completed-range checkpoint.
- **Seq-only path:** a sparse checkpoint ring stores the position of every 2^L-th DATA seq (L = 8). Lookup jumps to the floor checkpoint, or to `tail_pos` if that checkpoint expired, then scans at most 2^L DATA records **plus intervening PAD items**. Size checkpoint storage from the configured minimum record (16 B generic; 32 B only under an enforced ITCH minimum).

### 5.5 Block pool and partition index [D] (A12, I-1)

```
struct BlockMeta {            // 32 B, array meta[N_blocks]
  u64 base_pos;               // pos of entry 0
  u64 last_pos;               // pos of last entry
  u32 count;                  // entries used (≤ B)
  u32 partition;              // owner, or NONE when free
  u32 gen;                    // +1 on every free → stale-reference detection
  u32 next;                   // next block of same partition (or free-list link)
};
u32 entries[N_blocks][B];     // entry = (pos − base_pos) >> 3  (covers 32 GiB span per block)
```

- Entries are SoA, separate from meta, so scans touch only entry lines. B is a power of two (default **1024** as in A12; sweep 64…4096 in T5). One entry costs **4 B per retained record**.
- Each partition keeps its block ids in order (an intrusive `next` list for iteration, plus a small ring-vector for binary search on seek).

```
append(p, pos):
  b = last block of p (or NONE)
  if b open and meta[b].last_pos < tail_pos:          // all its entries expired
       detach b from p (it is p's only block — INV-I5) ; free(b) ; b = NONE
  delta64 = (pos - meta[b].base_pos) >> 3 if b != NONE else 0
  if b == NONE or meta[b].count == B or delta64 ≥ 2^32:
       if b ≠ NONE and not sealed: seal(b)
       b = alloc_prepared(p, base_pos = pos)            // guaranteed by publish preflight
  delta64 = (pos - meta[b].base_pos) >> 3    // recompute for newly allocated block
  require delta64 < 2^32 before narrowing to u32
  entries[b][meta[b].count++] = u32(delta64); meta[b].last_pos = pos
  if meta[b].count == B: seal(b)

seal(b): sealed_expiry_heap.push({meta[b].last_pos, b, meta[b].gen})
reclaim(tail_pos):
  while !sealed_expiry_heap.empty() and sealed_expiry_heap.min().last_pos < tail_pos:
     {last,b,g} = pop_min; assert meta[b].gen == g; assert b == first block of its partition
     detach; free(b)                                                  // gen++, push free list
```

- **Expiry order [D, corrected v1.1].** Use a min-heap keyed by `(last_pos, block_id, gen)`. Full-block sealing follows global append order, but a later delta-overflow seal can have an older `last_pos`; a FIFO is therefore invalid for the stated algorithm. Seal/free maintenance costs O(log N_sealed), not the v1.0 O(1) claim, and still never reads evicted records. M2/T5 must measure this cost and heap storage.
  - *Alternative considered:* eagerly drop an index entry per evicted record, which needs the evicted record's partition (a cold header read) and per-record work.
- **Open blocks of cold partitions** expire lazily on that partition's next append, or via `sweep_open_blocks()`, which runs on pool pressure and every N evictions. The sweep is O(P).
- **Sizing rule (no pool pressure).** Let `R_max = C / r_min` be the maximum number of retained records and P the partition count. Use `r_min = 16` for the generic opaque-byte API; `r_min = 32` is valid only for a configuration enforcing the validated ITCH minimum. With C below the 32-GiB delta span, a per-partition tail-straddling sealed block and open block are covered by the 2P allowance. The proposed `N_blocks ≥ ⌈R_max/B⌉ + 2P + 1` bound must include allocated stale open blocks; sweep expired open blocks before declaring pressure, and check the bound in V19/P5. It is a proposed sizing argument, not a measured result.
  - Example: C = 1 GiB, r_min = 32 B (ITCH), B = 1024, P = 10⁴ gives 32,768 + 20,001 blocks, about **218 MB** (≈20% of C). Typical use is lower; T5 measures it.
  - Smaller pools trigger the **pool-pressure policy** [D]: `force_evict` (default; advance the tail until a block frees, counted as retention loss) or `reject_publish`. The configuration is validated at startup.
- **Partially filled block overhead:** open slack = Σ over open blocks of `(B − count)` entries, at most P·(B−1)·4 bytes. Report unused capacity in delta-sealed partial blocks and expired-but-allocated entries separately; these are not included in open slack. Total index memory also includes the expiry heap and per-partition seek/list structures. Incremental gauges must match a brute-force recount (V17).
- **Reader safety (single-threaded).** A cursor stores `(block, gen, idx)` and the cached key `pos` in the merge structure.
  - A block is freed only when all its entries are below `tail_pos`, so a recycled block always shows up as a cached key below the tail. Checking the **minimum key against `tail_pos`** therefore detects every stale cursor without touching recycled memory (INV-Q4).
  - On advance, `meta[b].gen == gen` is asserted.

### 5.6 Replay execution

**Scan mode (baseline: the article's original linear pass, A5):**
```
next_batch entry: apply common checkpoint/error rules of §3.6
cur = start_pos (position of first seq > after_seq; §5.4)
while cur < upper_pos and budget:
   if cur < tail_pos: return FellBehind
   h = header(cur); if !PAD and sub.matches(h.topic): deliver
   cur += h.size
```

**Indexed mode:**
```
open: for p in sub.partitions: c = seek(p, start_pos)   // binary search blocks, then entries
      if c.pos < upper_pos: kernel.push(key(c.pos, c.id))
next_batch(max):
  apply common checkpoint/error rules of §3.6 before touching cursor memory
  while delivered < max and !kernel.empty():
     (pos, ci) = kernel.top()
     if pos < tail_pos: return FellBehind              // min-key check covers all cursors
     rec = ring.at(pos); assert rec.seq > last_seq     // ordering + no duplicates
     if sub.filter[ci](rec.topic): deliver(rec)        // intra-partition filtering fetches the record
     pos' = cursor[ci].advance()                       // gen check; block chaining via meta.next
     if pos' < upper_pos: kernel.replace_top(key(pos', ci)) else kernel.pop()
```

**Auto mode:** chooses scan if `wide`, or if `k > K_max`, or if the estimated indexed entries in the range exceed `ρ_max ×` the records in the range. The estimate is cheap, from block metadata. `K_max` and `ρ_max` are configuration values to be **calibrated from T1/T3**; no defaults are claimed now.

### 5.7 Merge kernels (concrete C++ layouts) [D]

**Packed keys.** A key is one `uint64_t`: `((pos >> 3) << 16) | cursor_id`. Reserve `UINT64_MAX` for exhausted inputs, require `k ≤ 65,535` with ids 0…65,534, and require every position/boundary to remain below 2^51. Preflight `head_pos + pad + need` with checked arithmetic and return `RepresentationLimit` before mutation on exhaustion; do not mask or wrap positions. The core's bounded run lifetime is explicit. A wider `{pos,cursor_id}` representation is a separate measured alternative, not silently interchangeable. Cursor state remains separate; comparisons use inline integer keys.

| Kernel | Layout | Replace-top cost | Notes |
|---|---|---|---|
| `StdPQ` | `std::priority_queue<uint64_t, vector, greater>` with pop + push | ~2·log₂k compares + 2 sifts | Reference |
| `BinHeap` | Implicit array `h[0..k)`; custom `replace_top` sift-down | ≤ 2 compares/level; **early exit** when the new key ≤ min child (O(1) on runs; S23) | |
| `Quad` | 4-ary heap, children 4i+1..4i+4 form a 32-B group; base alignment alone does not prevent cache-line crossing | log₄k levels × (3+1) compares; front-padding variants measured | LaMarca–Ladner (S20) |
| `Loser` | `u64 node[K2]`, K2 = next power of two ≥ k; checked sentinel `UINT64_MAX`; `node[0]` = winner | log₂K2 tournament min/max steps on a predictable path; emitted branch behavior must be inspected | Sanders App. A.5 (S18) |

```
// loser-tree replay after the winner's cursor ci produced key x
i = (K2 + ci) >> 1
while i > 0: lo = min(node[i], x); node[i] = max(node[i], x); x = lo; i >>= 1
node[0] = x
```

**Galloping (run-skipping) wrapper.** Tier C, applicable to every kernel.
1. After the same cursor wins `g` consecutive times (adaptive, starting at 7 as in S24), compute the **boundary β = the minimum key among all other cursors**. For a binary heap that is min(h[1], h[2]); for a 4-ary heap, the minimum of h[1..4]; for a loser tree, the minimum of the losers on the winner's leaf-to-root path.
2. Exponentially search the winner's current block entries for the last entry with position < β, then emit that run in bulk (prefetching its records).
3. **Correctness:** positions are unique across partitions, so `< β` is a strict boundary that preserves the competing cursors' order (INV-M3). The run never crosses `upper_pos`, and it never starts below `tail_pos` because the run's first element is the global minimum, which has just been checked.

**No presumed winner.** Do not assume loser trees win. M1 measures all kernels on the same inputs (RESEARCH §3.5).

### 5.8 Complexity and constant factors [H unless noted]

| Operation | Complexity | Dominant constant-factor cost (to be measured) |
|---|---|---|
| publish | Payload-copy work + evictions + ordered seal/free maintenance; sweeps can cost O(P) | Copy bytes, header reads, prepared resources, heap/list maintenance; measure all components rather than claiming unconditional O(1) |
| scan replay | O(bytes in range) | Sequential header reads (prefetch-friendly), topic check |
| indexed replay | O(E log k) for E entries in subscribed partitions | Record fetch per entry (likely cache/DRAM miss for narrow subscriptions); merge compares mostly in L1 |
| seek per partition | O(log #blocks + log B) | — |
| reclaim | O(log N_sealed) per heap removal, plus any separately counted O(P) open-block sweep | Heap traffic, block unlink/free and accounting |

---

## 6. Storage-layout optimization (formal)

### 6.1 Model M-store [D]

This applies **per partition p** and **per compaction window Ω** (default: one trading day of ITCH, matching A13's "since start of period" recoveries).

- **Tree.** T = (V, E), rooted at the partition topic r. V holds r plus every topic of p with positive subtree volume in Ω; zero-volume subtrees are pruned, which preserves optimal costs (they can join their parent's store at zero cost).
- **Volumes.** w(v) ∈ ℕ = bytes stored for messages published exactly on v in Ω (record framing included). Internal topics may have w > 0 (as A has in the figure).
- **Layouts** = cut sets X ⊆ E. The stores are the connected components of (V, E∖X); each store's root is its topmost node. This is exactly the residual-store model (I-4): a hot child can be isolated while its parent and cold siblings stay grouped in a residual store. **No replication**: each topic is in exactly one store. A store is *materialized* iff W(C) = Σ_{v∈C} w(v) > 0.
- **Workload.** Consumer classes j = 1..b, each with weight f_j ≥ 0 and terms Θ_j (Exact/Subtree, possibly a basket of many terms, possibly rooted above r). Match set: M_j = topics of V matched by some term in Θ_j.
- **Reads.** Per node, m(x) = {j : x ∈ M_j} if w(x) > 0, else ∅. Class j reads store C iff j ∈ reads(C) = ∪_{x∈C} m(x). A store is read **once per request** however many of the class's topics it holds, so baskets are never double-counted.
- **Cost.** For a materialized C: cost(C) = (α·W(C) + β)·F(reads(C)) + γ, with F(S) = Σ_{j∈S} f_j.
  - α = cost per byte read; β = fixed cost per store read (open, seek, merge cursor); γ = per-store overhead per window.
  - Bytes read by class j: R_j = Σ_{C: j∈reads(C)} W(C). Useful bytes: U_j = Σ_{x∈M_j} w(x). Waste_j = R_j − U_j.
- **Problems:**
  - **P1(K):** minimize J(X) = Σ_C cost(C) subject to #materialized stores ≤ K.
  - **P1-pen(γ):** no budget; minimize J with the per-store penalty γ.
- **Time ranges [corrected v1.1].** The core optimizer models whole-window requests only. Scaling f_j by a read fraction also scales β incorrectly. A partial-window extension must separately model useful/read byte fractions and the probability of touching each store, leaving fixed β charged per actual store read; sparse indexes alone do not establish proportional I/O.

**Choices for experiments (L2):**
- β/α ∈ {0, 64 KiB, 1 MiB}, i.e., a store read costs like reading that many extra bytes. These are **sensitivity values, not measurements**, until R3 measures α and β.
- γ is swept; K is either the baseline's per-partition store count (same-budget comparison) or swept.

### 6.2 What the model includes and excludes

- **Includes:**
  - the article's baseline (cut every edge from r to its children; §6.6) and the figure's "after" layout;
  - any partition of the tree into connected stores, including isolating a hot child while its parent and cold siblings stay together.
- **Excludes:**
  - non-connected groupings (for example, two cold siblings in one store without their parent's messages);
  - cross-partition stores (R10);
  - replication;
  - layouts that change within a window;
  - intra-store topic indexes (which would change the cost model);
  - real disk effects beyond α and β (measured in R3).
- **Complete-subtree cuts are narrower.** They cannot place an internal topic's own messages (A's 28.5 MB) in a residual store while a child is isolated. They would therefore miss the figure's "after" layout. We do not use them, and we call nothing "globally optimal" outside M-store.

### 6.3 Exact method A: enumeration (ENUM)
- Iterate over all 2^{|E|} cut sets (Gray-code order).
- For each: union-find components, then W, the reads bitmask, and the cost. Keep the best layout for each store count.
- With bounded single-word masks, bounded/precomputed F, and a linear tree traversal per cut set, evaluation is O(|V|); account separately for mask/weight preprocessing and any multiword bitset work. A union-find implementation adds its own overhead. The initial cap |E| ≤ 22 means about 4M candidate layouts, not a measured runtime guarantee; impose a work/time budget and report exact coverage.
- ENUM is the **ground truth** for any workload, including baskets, and validates everything else.

### 6.4 Exact method B: class-mask DP (MASK-DP)

**Relaxation.** Give each component a *multiplier set* Λ ⊇ reads(C) and charge (α·W(C) + β)·F(Λ) + γ. Because f ≥ 0, this is ≥ the true cost, with equality at Λ = reads(C). Minimizing over Λ is therefore exact. The constraint reads(C) ⊆ Λ is **local**: m(x) ⊆ Λ for every node x in C.

**State.** For node v, consider the open component O_v (the component containing v within subtree T_v).
- **k** = number of materialized **closed** components inside T_v (k ≤ min(K, |T_v|));
- **Λ** ⊆ {1..b} = the open component's multiplier;
- **z** = [W(O_v) > 0].

**Value.** D_v(k, Λ, z) = the minimum over partial layouts of T_v consistent with the state of (Σ cost over closed components) + α·F(Λ)·W(O_v).

**Recurrence.**
```
init (v alone):   D_v(0, Λ, [w(v)>0]) = α·F(Λ)·w(v)   if m(v) ⊆ Λ, else ∞
for each child c (sequentially):
  close_c(t) = min_{k+z'=t, Λ'} D_c(k, Λ', z') + z'·(β·F(Λ') + γ)
  join: N(k1+k2, Λ, z1∨z2) ← D(k1, Λ, z1) + D_c(k2, Λ, z2)      // same Λ: c's open part joins v's
  cut:  N(k1+t,  Λ, z1)    ← D(k1, Λ, z1) + close_c(t)
  D ← N
answer(K) = min_{k+z ≤ K, Λ, z} D_r(k, Λ, z) + z·(β·F(Λ) + γ)    // also yields the whole curve c(k), k ≤ K
```

**State sufficiency.** Cost is additive over components, and closed components inside T_v are final. The rest of the tree interacts with T_v's configuration **only** through:
1. the open component's multiplier Λ, which future nodes must also satisfy (local check), and which prices their bytes;
2. whether that component already has volume (z), which decides materialization and its β, γ charge;
3. the store count k (budget).

The open part's byte cost α·F(Λ)·W(O_v) is already charged and is linear given Λ. Two partial layouts with the same (k, Λ, z) are therefore interchangeable for every completion, so keeping the minimum is sufficient.

**Correctness sketch.**
- Every DP path corresponds to a valid cut set plus a feasible Λ per component.
- Every cut set, with Λ = reads(C) for each component, is reachable.
- Hence DP optimum = min over layouts of the true cost = OPT(P1(K)), for every K at once.

**Reconstruction.** Store, per (v, child index, state), the argmin decision: join or cut, k2 or t, and for cuts the child's (k, Λ', z'). Unwind top-down from the root's argmin. Memory O(|V|·K·2^b) entries.

**Complexity.**
- Arrays are capped at min(K, subtree size). For merge sizes a,c, use φ(s)=s² when s≤K and φ(s)=2Ks−K² otherwise. The inequality `min(K,a)·min(K,c) ≤ φ(a+c)−φ(a)−φ(c)` telescopes over child merges to O(|V|K). This is independent reasoning for this recurrence, not a theorem borrowed from the related edge-cost problem S34.
- Total time **O(|V|·K·2^b)**; memory O(|V|·K·2^b) with reconstruction, O(K·2^b·depth) for value only.
- The bound counts arithmetic operations with precomputed F, bounded masks, capped store counts, and constant-size z states. Actual |V| and b depend on routing/workload choices and must be measured in P1/P7; small W1/W2 class counts are a design assumption, not a verified runtime.
- **Limits.** Exponential in b. W0 (one class per topic) may exceed the initial b≈16 cap and then tries ENUM only within ENUM's own limits; neither method is presumed to cover every instance. Related weighted tree-partition problems in S34 are NP-hard, but that is not a hardness proof for M-store. No general polynomial algorithm is claimed.

**Arithmetic [corrected v1.1].** Inputs α, β, γ and f_j must be nonnegative integers or explicitly encoded rationals. Normalize rational inputs to common integer scales and use the same scaled objective in both evaluators. Check every product, accumulation, and infinity sentinel against `unsigned __int128` bounds before solving; reject overflowing configurations. This integer type is a GCC/Clang target extension, not portable ISO C++20. Arbitrary floating-point inputs cannot support exact-equality claims; quantized measured costs give exactness only for that quantized model. Byte volumes remain uint64.

### 6.5 Global store budget across partitions
- Partitions are independent given their store counts. The DP returns each partition's whole cost curve c_p(k).
- **Penalized form:** for γ′ ≥ 0, choose k_p minimizing c_p(k) + γ′·k. The resulting point is optimal for its own **at-most** total budget. Negative penalties do not justify that statement. Nonnegative sweeps expose supported efficient points, not every budget or necessarily the entire convex hull (S36).
- For an unsupported budget B, report the best feasible layout and lower bound `Σ_p min_k(c_p(k)+γ′k) − γ′B`, with γ′ ≥ 0. If no feasible point was evaluated, say so. An exact multiple-choice knapsack DP (O(P·K_total·k_max)) is optional.
- **Certificate precondition:** own-budget exactness needs actual per-partition minima over the declared feasible count domain. A global lower bound needs exact minima or certified lower bounds for **every** partition term. Incomplete curves and timed-out feasible incumbents do not supply such certificates; report no global exactness/bound unless those conditions are satisfied.
- **Same-budget comparison:** k_p = the baseline's per-partition store count. Every method is evaluated on J with the same k_p. This is a true optimality-gap comparison.

### 6.6 Heuristics (independently designed; labeled as such)

**H-BASE (article's old rule, A15).** Cut every edge (r, c) for children c of r. This gives one store per child subtree plus r's own messages. Under H-spec this is one store per (symbol, family) and per leaf `noii`/`rpii`/`dlcr`.

**H-KM(T): threshold greedy with hot isolation** (Kundu–Misra style, S33):
```
1. hot = {x : w(x) > T}: cut (parent(x),x) and every (x,child) → each hot x is a singleton store
2. post-order on the remaining forest: R(v) = w(v) + Σ_{uncut children} R(c)
   while R(v) > T: cut the uncut child with the largest R(c); R(v) −= R(c)
```
- It is **exact for its own problem** P_T: the minimum number of stores such that every store has W ≤ T or is a single topic.
  - Hot singletons are forced, because any store containing x has W ≥ w(x) > T.
  - The rest is the Kundu–Misra MinNum problem (S33, S34).
  - Optimality **must be validated** against brute force in the authorized phase (V30); no check has run.
- count(T) is non-increasing if H-KM implements the stated optimal threshold/count solver; V30 must check both the implementation and this property. Use deterministic node-id tie-breaking for equal child weights, exclude zero-only stores from the count, and report K=0 infeasible for positive volume. Related-problem NP-hardness in S34 is not a hardness proof for M-store.

**Bisection variants for budget K** (the article's "greedy + binary search" is ambiguous, RESEARCH §1.3):
- **Search domain:** integer T ∈ [0, W_total], for nonempty positive-volume partitions; handle empty partitions separately. This finite domain is necessary because the one-store plateau otherwise has no largest threshold.
- **H-KM-min:** T_min = min{T : count(T) ≤ K} within that domain.
- **H-KM-max:** the largest T in that domain with count(T) = count(T_min). In the worked example it reproduces the figure's layout. These labels name threshold endpoints, not a general finest/coarsest refinement relation or a proved min-max solution under hot-singleton exemptions.

Both are O(64·|V| log |V|) per partition using integer bisection. **They are heuristics for P1** and are compared to MASK-DP/ENUM on the same J and the same per-partition budgets.

**H-LS (Tier C, optional):** first-improvement local search over single-edge toggles, starting from H-KM-min.

### 6.7 Worked example (RESEARCH §1.3)

Workload W0 (uniform exact reads), α = 1, β = γ = 0, budget 4:

| Layout | Stores | Waste (B) |
|---|---|---:|
| Baseline | 4 | 5,517,460,497 |
| Figure's "after" (= H-KM-max) | 4 | 39,881,491 |
| ENUM/MASK-DP optimum (= H-KM-min here) | 4 | **30,029,491** |

A subtree read of A favors the "after" layout (2 stores touched, no waste) over the W0 optimum (3 stores, 148,000 B waste). This instance becomes regression test V32 and a study exercise.

### 6.8 Validation hooks
V28 (two independent evaluators), V29 (MASK-DP = ENUM on ≥10⁴ random tiny trees, every k), V30 (KM vs brute-force minimum count), V31 (baseline construction), V32 (worked example). See VALIDATION_PLAN §3.

### 6.9 Claims discipline for the optimizer
- **"Exact"** means optimal for M-store with the stated workload, scaled nonnegative costs, and budget, per partition. ENUM validation is required in P7 and has not run. Set explicit state/time limits for ENUM and MASK-DP and report per-workload coverage; W0 can exceed both methods' practical limits. Such rows are heuristic-only, without an exact optimality gap.
- It is not optimal for excluded layout models or unmodeled costs.
- Greedy-vs-exact gaps are reported only on identical objectives and feasible sets. Anything else is labeled "not an optimality gap".

---

## 7. Disk path (full version; roadmap R1–R3, not authorized)

### 7.1 Global WAL segments [D]
This **deliberately deviates** from the article's per-partition chronological segments (A14). With about 10⁴ symbol partitions, per-partition append streams mean 10⁴ open buffers and scattered small writes. One global sequential log is simpler to make crash-consistent. The splitting stage restores per-partition locality.

```
wal/<first_seq:020>.wal
SegmentHeader (64 B): magic "TPLWAL\0\1" | format_version u16 | flags u16 | header_len u32
                      first_seq u64 | created_ns u64 | build_id u64 | reserved | header_crc32c u32
Record: crc32c u32 (masked; over all following bytes of the record) | len u32
        seq u64 | kind u8 (DATA | TOPIC_DEF) | reserved u8 | payload_len u16 | topic u32 | payload | pad to 8
SegmentFooter (sealed only): magic | last_seq u64 | record_count u64 | footer_crc32c u32
```

- TOPIC_DEF records (id → path) precede a topic's first DATA record, so the WAL describes itself.
- CRC32C follows LevelDB's choice (S26); SSE4.2 is present [V], and a table fallback is required for portability.
- **Versioning:** readers reject unknown major versions and ignore unknown flags only where the format permits.

### 7.2 Durable publication
- **Group commit:** records go to an in-memory buffer; `write(2)` at ≥1 MiB or every T ms; `fsync` per policy (every N ms or bytes). `durable_seq` = the last seq covered by a **completed** fsync.
- **Segment roll:** write footer → fsync segment → create the next segment with `O_EXCL` → write header → fsync it → **fsync the directory** (S31).
- **Fsync error policy [D].** Stop new durable acknowledgments on any fsync failure and preserve the failure context. Do not treat retry after a writeback error as restoring durability. EINTR and EIO are distinct; conservatively stopping on both is a project choice. A clean process restart alone does not prove recovery from storage/writeback faults (S29, S55). INV-D1 covers only the declared/tested crash model with successful syncs, not arbitrary media or writeback failure. The ring never evicts a record not yet *written* to the WAL (INV-D5).

### 7.3 Crash recovery
- Read the WAL directory and check that segment sequence ranges are contiguous.
- **Sealed segments:** check header and footer CRCs, with an optional deep CRC pass.
- **Last segment:** scan it. At the first record with invalid length bounds, CRC mismatch, or a sequence discontinuity, **truncate** (`ftruncate` + fsync) (S13).
- Corruption inside a sealed segment is **fail-stop**. History is never silently skipped.
- Then rebuild the ring and index from the WAL tail, load the manifest, and garbage-collect orphans.
- The recovered log is a prefix of the published log that covers every fsync-acknowledged record (INV-D1).

### 7.4 Compaction into store packs
- **Input:** whole sealed segments covering window Ω.
- **Volumes:** per topic, from pass 1 or from incremental statistics.
- **Layout:** solved per partition (§6).
- **Pass 2:** route records to per-store writers, producing a pack file:

```
stores/pack-<seq_lo>-<seq_hi>.tps
PackHeader | chunks: {store_id u32, n u32, first_seq u64, last_seq u64, bytes u32, crc32c u32, records...}
Directory: per store {store_id, partition, root_topic, topic ids, seq range, bytes, sparse chunk index}
PackFooter: directory offset/len/crc32c, magic
```

Many logical stores share one physical file, so store count affects metadata and merge cursors but not file count.

### 7.5 Manifest and atomic publication
- `MANIFEST-<n>` is a full snapshot with a CRC: packs, uncompacted WAL ranges, topic dictionary snapshot, layout parameters.
- Publication order:
  1. Write the pack to `tmp/`, fsync it, rename it, fsync the directory.
  2. Write `MANIFEST-<n>` the same way.
  3. Atomically update `CURRENT`: temp file → fsync → rename → fsync directory.
- Old WAL segments are deleted only after the new manifest is durable **and** no reader lease references them (Kafka's copy-on-write segment list is the model, S13). RocksDB's version-edit log is the considered alternative (S27).
- On startup: files not referenced by CURRENT's manifest are orphans and are removed.

### 7.6 Disk reader and handoff
- For each pack in range, select the stores whose topic lists intersect the subscription.
- Read them with `pread` in 1–4 MiB sequential buffers (`POSIX_FADV_SEQUENTIAL`), starting at the chunk containing s + 1 (sparse index). **Verify chunk CRC before use.**
- Merge by `seq` using the §5.7 kernels, filter, deliver. Then scan the remaining WAL. Then hand off to the tip (§3.8).
- No mmap is used, so physical I/O can be measured (S30).

### 7.7 Disk failure handling

| Condition | Response |
|---|---|
| Chunk CRC mismatch | `DataCorrupted` error for that request (never deliver unverified bytes). A fallback to WAL is allowed if the WAL still exists. |
| Manifest unreadable | Use the highest valid `MANIFEST-<n>` |
| Crash during compaction | Packs not referenced by the manifest are garbage-collected |

---

## 8. Concurrency extension (R4) — design notes

- **Threads:** one writer, N readers. This remains an unproved roadmap design, not an established race-free protocol. Before R4, select and justify the publication, overwrite, and reclamation mechanisms under the C++20 memory model; all conflicting accesses, including writer payload stores, must be compatible atomics or otherwise synchronized.
- **Candidate record protocol:** generation-validated copying or pinned/epoch-protected storage. The v1.0 informal tail/fence recipe is withdrawn as an implementation specification until a complete happens-before argument is supplied. Atomic word access additionally requires valid object lifetime, alignment, representation, and bounds; `atomic_ref` alone is not proof.
- **Blocks:** compare a fully justified generation protocol with EBR/pinning (S14–S16). EBR for index blocks alone does not protect ring bytes from overwrite. TSan and stress testing are evidence, not a proof of all C++ executions. C++26/C++29 proposals are optional background, not dependencies (S58).
- **Layout:** head, tail, and other hot counters sit on separate 64-byte lines (`perf c2c` checks for false sharing).
- **Verification:** TSan stress tests, plus the deterministic oracle run against recorded interleavings.

---

## 9. Illustrative C++ interfaces (not code to compile)

```cpp
namespace tiplog {
using Seq = std::uint64_t;  using LogPos = std::uint64_t;
using TopicId = std::uint32_t;  using PartitionId = std::uint32_t;

struct Term { enum Kind : std::uint8_t { Exact, Subtree } kind; std::string path; };
struct SubscriptionSpec { std::vector<Term> terms; };
struct ResumeCheckpoint { Seq after_seq; LogPos next_pos; }; // logical progress, not last output

enum class ReplayMode : std::uint8_t { Scan, Indexed, Auto };
enum class MergeKernel : std::uint8_t { StdPQ, BinHeap, Quad, Loser };
enum class PoolPolicy : std::uint8_t { ForceEvict, RejectPublish };

struct EngineConfig {
  std::size_t ring_bytes;          // power of two
  std::uint32_t block_entries;     // B, power of two
  std::uint32_t pool_blocks;       // validated against the sizing rule
  PoolPolicy pool_policy;
  std::uint32_t ckpt_log2;         // L
  std::size_t max_record_bytes;
};

struct Delivered { Seq seq; LogPos pos; TopicId topic; std::span<const std::byte> payload; };
struct ReplayError { enum Kind { HistoryExpired, FellBehind } kind; Seq last_delivered; Seq oldest_retained; };
enum class Status { More, Done, Error };

class Replay {
 public:
  Status next_batch(std::size_t max, std::vector<Delivered>& out);   // payload valid until next mutation
  std::optional<ReplayError> error() const;
  Seq upper_seq() const;
  std::optional<ResumeCheckpoint> checkpoint() const; // §3.6; absent for a future-start empty query
};

class Engine {
 public:
  explicit Engine(const EngineConfig&);
  TopicId intern(std::string_view path);
  Seq publish(TopicId, std::span<const std::byte> payload);
  CompiledSubscription compile(const SubscriptionSpec&);
  Replay open_replay(const CompiledSubscription&, Seq after_seq, ReplayMode, MergeKernel);
  Tail open_tail(const CompiledSubscription&, Seq after_seq, MergeKernel);  // chained polls (§3.7)
  EngineStats stats() const;          // memory, slack, evictions, pool high-water...
  void check_invariants() const;      // debug/test builds
};
}  // namespace tiplog
```

---

## 10. Invariants catalog (each has a test in VALIDATION_PLAN §3)

**Ring**
- R1: `0 ≤ head_pos − tail_pos ≤ C`; both are multiples of 8.
- R2: the items in `[tail_pos, head_pos)` parse contiguously, and their sizes sum to the span.
- R3: no item straddles the physical end.
- R4: PAD items appear only immediately before a physical boundary.
- R5: DATA sequence numbers are consecutive and increase with position; `tail_seq` is the first DATA at or after `tail_pos` (or `head_seq`).
- R6: DATA sizes are in [16, max_record], PAD sizes in [8, C); all are multiples of 8, and DATA payload lengths are consistent.
- R7: retention is maximal under capacity-only eviction. Explicit ForceEvict pressure may shorten it; every such action is counted, and the oracle uses the same declared pressure policy.

**Index**
- I1: per partition, entry positions are strictly increasing across its block chain.
- I2: every retained DATA record has exactly one entry in its partition; no entry is ≥ `head_pos`.
- I3: entries decode within `[base_pos, last_pos]`; `count ≤ B`.
- I4: only a partition's last block may be open; the expiry heap contains each sealed block exactly once and returns the minimum `last_pos`.
- I5: after `reclaim`, no sealed block with `last_pos < tail_pos` remains; an expired open block is its partition's only block.

**Pool**
- P1: free + allocated = N_blocks, with no block listed twice.
- P2: the owner field matches the containing list.
- P3: `gen` increments by exactly 1 per free.
- P4: the incremental slack and live counters equal a brute-force recount.
- P5: high-water ≤ N_blocks, and there is no pressure when the sizing rule holds.

**Replay**
- Q1: output sequence numbers are strictly increasing, and every delivered record matches.
- Q2: a completed replay equals Oracle(sub, after, upper).
- Q3: a replay that errors has delivered an exact prefix of the oracle output.
- Q4: errors are justified (see §3.6).
- Q5: nothing above `upper` is delivered.
- Q6: chained replays equal one replay over the union range.
- Q7: with identical interleaved API schedules and positive output budgets, Scan/Indexed/Auto produce identical output prefixes, statuses, progress checkpoints, and expiry outcomes under §3.6. `max=0` changes none of these.

**Merge**
- M1: keys are distinct.
- M2: pops are strictly increasing.
- M3: galloping emits only keys below β.

**Layout**
- L1: every layout is a connected partition of the pruned tree.
- L2: the two independent evaluators agree.
- L3: MASK-DP = ENUM for every k ≤ K on test instances.
- L4: materialized stores ≤ budget.

**Disk (R1–R2)**
- D1: the recovered WAL is a prefix of the published log that covers `durable_seq`.
- D2: no record with a bad CRC or length is ever delivered.
- D3: the manifest references only fully written, synced packs, and their sequence ranges are disjoint and contiguous with WAL coverage.
- D4: every seq in [1, recovered] is retrievable from packs ∪ WAL ∪ ring.
- D5: the ring never evicts a seq that has not been written to the WAL.
- D6: compaction preserves content and per-store order (pack union = source range).

---

## 11. Design decisions and alternatives

| ID | Decision [D] | Main alternatives (why not chosen) | Evidence |
|---|---|---|---|
| DD-01 | Deterministic single-threaded core | Concurrent from the start (schedule risk, correctness cost) | S15, S16 |
| DD-02 | Dense global sequence + logical positions, never recycled | Physical offsets (ABA, stale references) | S11, S13 |
| DD-03 | Spec-derived 4-level hierarchy; 2-segment partitions | `itch/SYM/type` (baseline already exact); event-first (useless tip selectivity per symbol) | S05, A6, A15 |
| DD-04 | Variable-length ring, 8-byte alignment, 16-byte header, in-band PAD | Mirrored virtual-memory ring; chunk lists | S11 |
| DD-05 | Byte-capacity, overwrite-oldest retention; explicit errors | Time or count retention; backpressure on publisher | A3, S12, S04 |
| DD-06 | Dense per-partition index, 32-bit deltas, shared block pool (B = 1024) | Per-partition worst-case rings (A11); vectors/deques; 64-bit entries; per-topic index | A11, A12, S02 |
| DD-07 | Sealed-block expiry min-heap + lazy open-block expiry + generations | FIFO is invalid for late partial seals; eager per-record eviction | v1.1 review §13 |
| DD-08 | Pool pressure → force-evict (configurable) | Reject publish | — |
| DD-09 | Union semantics; one cursor per partition prevents duplicates | Per-term cursors with deduplication | — |
| DD-10 | Captured upper bound; HistoryExpired/FellBehind; never silent | Best-effort skipping | S04, S13 |
| DD-11 | Four kernels with packed keys + galloping wrapper; no presumed winner | Heap only (A9) | S18, S20–S24 |
| DD-12 | Scan vs indexed planner calibrated by measurement | Always indexed | A5 |
| DD-13 | Connected-component stores within partitions; no replication | Complete-subtree cuts (narrower); cross-partition bundles (R10); replication | I-4, I-6 |
| DD-14 | ENUM + MASK-DP exact; KM-greedy (two bisections) heuristics | ILP solvers (dependency); learned layouts (out of scope) | S33–S36 |
| DD-15 | Python conversion/analysis; C++ engine/optimizer; freeze verified compatible pins in P0 (Benchmark v1.9.5 retained; optional HdrHistogram_c 0.12.1 reviewed) | Updating tools for age alone; assuming historical environment is current | S48, S57; refresh §13 |
| DD-16 | Global WAL + store packs + snapshot manifests + `pread` | Per-partition segments (A14); mmap reads | S13, S26–S31 |
| DD-17 | Independent C++ oracle + Python digests; libFuzzer; ASan/UBSan | Testing only against own implementation | S45 |
| DD-18 | Pin benchmarks to one P-core, sibling idle; repetitions with CIs | Unpinned runs on a hybrid CPU | S41, S47 |

---

## 12. Failure handling summary (core)

| Condition | Detection | Response |
|---|---|---|
| Malformed ITCH (bad length or type, truncated) | Converter checks against the spec length table | Strict mode: abort with byte offset (default); lenient: count and skip (never default) |
| Missing BinaryFILE terminator | End-of-file check | Mark the trace `incomplete` in metadata |
| Unknown locate | Directory lookup | Route to `_unmapped`, count |
| Malformed trace | Reader bounds checks | Error; fuzzed |
| Record too large | `publish` precondition | `std::errc::invalid_argument`, no state change |
| Sequence/packed-position/generation limit | Checked preflight arithmetic | `RepresentationLimit`, no partial publish or silent wrap |
| Pool exhausted | Allocation | ForceEvict (count retention loss) or RejectPublish |
| Start already evicted | Open | HistoryExpired |
| Evicted during replay | Common unread-checkpoint/tail check before either mode touches memory | FellBehind |
| Invariant violation | `check_invariants` (debug) | Abort with state dump |

## 13. Research and design review — 2026-10-17

This is a planning amendment, not executed code or validation. The original structure and research are preserved; corrected contracts above take precedence over v1.0. Review details and sources are in RESEARCH §6 and REVIEW_2026-10-17.md.

- **Core corrections:** common replay progress/expiry, zero-output tail bookmarks, safe PAD reservation and checked representations, ordered expiry for late-sealed blocks, and complete memory accounting. The generic registry must also reject local u16 topic-id exhaustion before mutation or choose a documented wider representation.
- **Merge hypotheses:** a 64-byte-aligned h[0] does not make every 4-ary sibling group cache-line-contained: children 4i+1…4i+4 can straddle lines. Specify any front padding explicitly and measure layout variants. `min`/`max` pseudocode does not guarantee branch-free emitted code. The 2026 PostgreSQL follow-up reinforces testing regressions; offset-value coding is not added for already scalar unique keys (S49).
- **Optimizer:** retain the connected residual model and class-mask recurrence. Add rational input scaling, overflow checks, finite threshold domains, proper Lagrange bounds, and per-workload exact coverage. Core claims remain full-window modeled cost, not physical disk speed.
- **2026 layout research:** LayoutPilot (S53) motivates reporting estimated versus measured candidate ranking; DriftBench (S50) motivates separating data-volume drift from subscription drift; WAIR (S51) is optional disk-roadmap context. These are different problem settings, not proofs of this optimizer. No new library or learned-layout feature is required.
- **Persistence:** XLL (S52) motivates explicitly counting WAL, compacted-pack, and rewrite bytes in R3. Its consensus/TiKV architecture and published speedups are not transferred to tiplog, and the current WAL is retained.
- **Concurrency:** current WG21 documents distinguish C++26 draft baseline interfaces from C++29 extensions (S58). Local standard-library availability needs an authorized feature probe; C++20 remains the core target.

All amended cases have planned validation rows in VALIDATION_PLAN §13. No claim here means those checks have passed.

**Recent engineering accounts:** Aeron's current Persistent Subscriptions design (S59) motivates repeated archive→live→archive handoff tests and explicit overlap-resource accounting in R2; it is not a dependency. Jane Street's October13 Flex Model article (S61) reinforces the distinction between preserving event history and coalescing current values. Its October2 outage account (S60) informs bounded retries/cancellation/resource-release checks only if R5 networking is later chosen.
