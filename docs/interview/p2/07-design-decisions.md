# 07 — Design decisions: chosen, alternatives, when each wins

Each decision lists:
- **Chosen**: what the code does.
- **Alternatives**: other options, and why each wasn't chosen.
- **When an alternative wins**: so you can show judgment rather than defend everything.
- **Label**: [Doc] stated in docs, [Code] visible in code, [Inferred] my reasoning.

The golden rule for the interview: **never claim a choice is universally best.** Say what it optimizes for, what it costs, and when you'd switch.

---

### D1. Topic names: `/`-separated strings at the edges, integer IDs inside
- **Chosen:** strings appear only at intern time; everything downstream uses `TopicId`, `PartitionId` and `local_id`.
- **Alternatives:**
  - *Strings everywhere:* matching costs O(terms × length) per record.
  - *Fixed structured keys*, e.g. `(symbol_id, msg_type)`: fastest, but only fits ITCH, and you lose subtree semantics and future hierarchies.
  - *64-bit hashes of paths with no registry:* no table needed, but collisions are possible, and you can't walk ancestors or have local IDs.
- **When an alternative wins:** a single-protocol system with a fixed schema, where structured keys are simpler and faster.
- **Label:** hierarchical namespace [Doc] (article A4, ARCHITECTURE §3.2); the IDs-inside split [Code]; the alternatives [Inferred].

### D2. Hierarchy: `itch/<SYM>/<family>/<type>` (4 levels, from the ITCH spec's sections)
- **Chosen:** families mirror ITCH 5.0 §1.2–1.8 (`stock`, `add`, `modify`, `trade`, plus `noii`, `rpii`, `dlcr`), with `itch/_market` for market-wide events.
- **Alternatives:**
  - *`itch/<SYM>/<type>` (3 levels):* under the article's three-segment store rule, every exact topic already gets its own store, so there is nothing for adaptive splitting to improve (§2.2). It is kept only as the "H-flat" sensitivity case.
  - *Event-first `itch/<type>/<SYM>`:* the partition becomes "all adds for all stocks", so the per-symbol tip index would be useless (DD-03).
- **When an alternative wins:** event-first suits consumers that want "all trades, all symbols", like a market-wide tape. But that is a wide subscription anyway.
- **Label:** [Doc] ARCHITECTURE §2.1–2.2, DD-03.

### D3. Partition = ancestor at depth min(2, depth), i.e. one per symbol
- **Chosen:** two-segment partitions, as in Aria.
- **Alternatives:**
  - *Per-topic index:* the article says this is untenable at around a million topics. A BOOK reader would also merge more cursors (one per event type instead of one per symbol).
  - *Depth 1:* one giant partition, so the index is useless.
  - *Depth 3 (symbol × family):* BOOK would need three cursors per symbol, and there would be many more partitions to manage.
- **When an alternative wins:** depth 3 wins when most readers want one family of a hot symbol (e.g. only trades of SPY) and the other families are huge. Per-topic indexing wins with few topics and very selective readers.
- **Label:** [Doc] article A6, ARCHITECTURE §2.1, DD-03; the trade-offs [Inferred].

### D4. ID widths: u64 Seq/LogPos, u32 TopicId/PartitionId, u16 local ID
- **Chosen:** see `01-types.md`. They are sized from measured counts (268.7M msgs/day, 111,997 topics, 8,907 partitions) and the approved 100,000-partition experiment.
- **Alternatives:** use 64-bit everywhere (simpler, but larger structures and bitsets); use u16 partitions (fits ITCH, fails T3).
- **When an alternative wins:** memory is no object, or IDs cross process boundaries and need room for namespacing.
- **Label:** counts [Doc] PROGRESS P1; widths [Code]; reasoning [Inferred].

### D5. Dense IDs, assigned in creation order
- **Chosen:** topic IDs 1, 2, 3 …; partition IDs 0, 1, 2 …; local IDs 0 … per partition.
- **Alternatives:**
  - *Stable hashed IDs:* the same across runs and processes, but sparse, and they would need hash tables instead of arrays.
  - *Pre-assigned schema IDs*, e.g. ITCH message-type letter → fixed bit: O(1) and stable, but not generic.
- **Costs of dense IDs:** IDs differ between runs if topics appear in a different order, so they **must not go on the wire or to disk** without the dictionary. P1's trace format carries a dictionary for exactly this reason (and its IDs are sparse).
- **When an alternative wins:** distributed or persistent systems need stable names or IDs.
- **Label:** [Code]; consequences [Inferred].

### D6. Filter per partition: `all` flag, or a lazily grown `vector<uint64_t>` bitset over local IDs
- **Chosen:** for ITCH, at most 21 topics per partition, so the bitset is one word, and the check is a shift and an AND.
- **Alternatives:**
  - *`unordered_set<TopicId>`:* a hash per record and about 10× the memory.
  - *`std::bitset<65536>`:* a fixed 8 KB per filter even for one selected topic.
  - *`vector<bool>`:* a proxy-reference special case, awkward and often slower.
  - *Sorted `vector<uint16_t>`:* binary search per record.
  - *Roaring bitmaps:* excellent for huge sparse sets, but an external dependency and overkill here.
- **Why the `all` flag:** whole-partition subscriptions (BOOK-style `Subtree(itch/S)`) need no bits, and **future topics in that partition need no update** (`prepare` skips them).
- **When an alternative wins:** roaring wins if partitions had millions of topics with sparse selections; a sorted vector wins for a handful of selections in a huge partition.
- **Label:** bitset/`all` [Doc] ARCHITECTURE §5.2; the alternatives [Inferred].

### D7. Filter container: `vector<PartitionFilter>` sorted by partition, binary search
- **Chosen:** compact and cache-friendly, deterministic order (which gives a deterministic cursor order for the merge), O(log F) lookup.
- **Alternatives:**
  - *`unordered_map<PartitionId, Filter>`:* O(1) average, but no ordered iteration, and iteration order varies.
  - *Dense array indexed by `PartitionId`:* O(1), but O(all partitions) memory **per subscription**: 100k × 32 B = 3.2 MB each.
  - *`std::map`:* pointer chasing.
  - *C++23 `std::flat_map`:* essentially what was hand-built here.
- **Known weak spot:** inserting into the middle costs O(F), and compile can degrade to O(F²) if partitions first match out of order (see `03`).
- **When an alternative wins:** a dense array wins for a few subscriptions over a modest partition count when Scan matching speed dominates. A hash map wins when filters change constantly.
- **Label:** [Code]; costs [Inferred].

### D8. Normalization: hash set of subtree roots, then check each term's own ancestors (P6)
- **Chosen:** O(n log n) sort (for de-duplication and deterministic output) plus O(n·d) lookups.
- **Alternatives:**
  - *All-pairs (P2 original):* simple, but O(n²) and too slow at 100k terms.
  - *Sweep over raw-string-sorted terms with a "current root":* wrong. `a`, `a-foo`, `a/b` interleave because `-` sorts before `/`.
  - *Sweep over **segment-wise** sorted terms with a stack of roots:* correct and O(n log n), because sorting by segment sequence makes descendants contiguous. This was not chosen; the hash-set method needs no custom comparator.
  - *Trie of terms:* O(total length) and naturally answers "is any ancestor a subtree root?", but more code and pointer-heavy.
- **When an alternative wins:** a trie wins when the same structure also serves matching for millions of subscriptions (shared prefix structure).
- **Label:** [Doc] subscriptions-scaling.md (the hash-set method and the interleaving finding); the segment-sort and trie alternatives [Inferred].

### D9. Eager compilation (precomputed filters) vs lazy matching
- **Chosen:** eager. Compile computes every partition's filter, and hooks maintain them.
- **Alternatives:**
  - *Match strings at replay time:* the oracle's approach. Far too slow for the engine.
  - *Lazy memo per TopicId:* on first sight of a topic, string-match it and cache the bit. No hooks needed, but the cache must be stored per subscription, and Indexed mode needs the partition list **up front**. For depth ≥ 2 terms that list comes from the terms themselves; for wide terms it can't.
- **When an alternative wins:** a lazy memo wins with very many short-lived subscriptions that each touch few topics.
- **Label:** eager [Doc] ARCHITECTURE §5.2; the lazy alternative [Inferred].

### D10. Push-based observer hooks on Subtree roots for new topics
- **Chosen:** the registry walks up from each new topic (O(depth)) and runs `prepare`/`commit` on the subscriptions found.
- **Alternatives:**
  - *Recompile every subscription on each new topic:* O(topics × subscriptions), and at start of day 112k topics appear.
  - *Pull-based epoch log:* the registry appends new topic IDs to a log with an epoch counter. Each subscription catches up from its last epoch at the start of each batch (the engine already re-acquires filters per batch). That removes callbacks, observer lifetimes and the A² de-duplication, and gives natural batching.
  - *Inverted index from topic to subscriptions:* useful for routing (fan-out) more than replay.
- **When an alternative wins:** the pull-based epoch log is likely better for a concurrent design, since readers update themselves on their own thread with no callbacks into other threads' state.
- **Label:** push hooks [Doc] ARCHITECTURE §5.1; alternatives [Inferred].

### D11. Ownership: shared state, weak observers, raw registry pointer plus lifetime token
- **Chosen:** `CompiledSubscription` owns `shared_ptr<CompiledState>`; the registry holds `weak_ptr` observers; the state holds a `Registry*` checked through `Lifetime{alive}`.
- **Alternatives:**
  - *Subscription holds `shared_ptr<Registry>`:* subscriptions extend the registry's life, and the registry must be heap-allocated.
  - *Handle/ID design:* the registry (or engine) owns all subscription tables, and users hold `{sub_id, generation}`. No `weak_ptr`, no atomics in `matches()`, data-oriented, and copy semantics are explicit.
  - *Raw pointers plus a "don't do that" rule:* fastest and least safe.
- **When an alternative wins:** the handle/ID design wins for performance and concurrency. It is what I'd pick for production.
- **Label:** [Code]; alternatives [Inferred].

### D12. Exceptions plus the strong exception guarantee (prepare, then a no-throw commit)
- **Chosen:**
  - throw `std::invalid_argument` for bad input;
  - throw `RepresentationLimit` (derived from `std::length_error`) for exhausted ID space;
  - throw `std::out_of_range` for bad IDs.
  - Mutations are transactional.
- **Alternatives:**
  - *Error codes or `std::expected` (C++23):* explicit, no hidden control flow, and usable in `-fno-exceptions` builds. Many low-latency shops prefer this.
  - *Abort on failure:* simplest, and acceptable when failures mean programmer error.
  - *Basic guarantee only:* simpler code, but registry and subscriptions could drift apart, which means silent loss.
- **Why exceptions here:** registry mutation is **off the hot path** (topics are created rarely compared with 268M messages), table-based exceptions cost nothing when not thrown, they compose with constructors, and they're easy to test (`EXPECT_THROW`).
- **When an alternative wins:** inside the publish and replay hot loops, or in codebases compiled without exceptions.
- **Label:** "reject without mutation" [Doc] V38, ARCHITECTURE §12; the zero-cost claim [Inferred, standard Itanium-ABI behaviour].

### D13. Single-threaded, deterministic core
- **Chosen:** no locks and no atomics by design, and every run is reproducible.
- **Alternatives:** concurrent from the start, which costs schedule and makes correctness harder to establish (DD-01); one thread per partition (sharded).
- **Consequences in P2:** `intern` and `prepare`/`commit` assume nothing interleaves; filter spans may be invalidated by `intern`; hooks are registered *after* the initial scan.
- **When an alternative wins:** real production buses serve concurrent readers. That is roadmap R4.
- **Label:** [Doc] DD-01, ARCHITECTURE §3.9.

### D14. An independent oracle sharing only value types
- **Chosen:** test-only `ScanOracle`, with its own matcher, own path validation, own arithmetic and full history.
- **Alternatives:**
  - *Testing against the implementation's own helpers:* common-mode bugs pass (DD-17).
  - *Golden tests only:* don't scale to random schedules.
  - *Property tests only:* check invariants, but can't confirm exact outputs.
  - The Python digest oracle is *also* used, for end-to-end ITCH runs.
- **When an alternative wins:** for an extremely simple function, a property test may be enough. The oracle earns its cost because the contract (expiry, budgets, checkpoints) is subtle.
- **Label:** [Doc] VALIDATION §2, DD-17.

### D15. Driver callbacks via `std::function`
- **Alternatives:** templates (inlined, header-only), a virtual interface, or `std::function_ref` (C++26; non-owning, no allocation). See `05`.
- **Label:** [Code]; the reasoning [Inferred].

### D16. PRNG: raw `mt19937_64` output modulo the budget
- **Alternatives:**
  - *`uniform_int_distribution`:* not reproducible across standard libraries [Doc].
  - *A self-implemented splitmix64 or PCG:* portable, faster and tiny, but must be implemented and tested.
  - *Lemire's unbiased bounded method:* no modulo bias, but unnecessary here.
- **Label:** [Doc] header comment; the alternatives [Inferred].

### D17. Hashing: `std::hash<std::string_view>` with transparent lookup
- **Alternatives:** a custom stable hash such as FNV or xxHash, which is faster and identical across platforms; a seeded or keyed hash, which resists collision attacks.
- **Caveat:** libstdc++'s string hash uses a fixed, public seed, so adversarially chosen paths could force collisions, a hash-flooding DoS. That's irrelevant for trusted ITCH data, but relevant if clients can create topics (they can, through subscriptions; see `03`).
- **Label:** [Code]; the DoS caveat [Inferred].

### D18. Reject malformed paths rather than normalizing them
- **Chosen:** `a//b`, `/a` and `a/` are errors.
- **Alternative:** normalize by collapsing `//` and trimming slashes. That's friendlier, but it creates **aliases**: two spellings for one topic, which risks double-counting and lookup mismatches.
- **Label:** [Code]; reasoning [Inferred].

### D19. Wide subscriptions (depth-1 Subtree) are served by Scan
- **Chosen:** `wide()` forces Scan (`engine.cpp:156`). Auto also falls back to Scan above `auto_max_partitions`, which defaults to 64 and is explicitly **uncalibrated** in P5.
- **Alternatives:**
  - *Indexed over every partition:* merging thousands of cursors costs more than scanning, and future partitions would need cursors created mid-replay.
  - *A separate global "everything" index:* redundant, because the ring *is* that index.
- **Label:** [Doc] ARCHITECTURE §3.3, §5.2, README ("Auto … thresholds are configurable and uncalibrated").

### D20. Topics are never deleted
- **Alternatives:** reference-counted topics, or generation-tagged IDs (as P4 does for blocks) with registry compaction.
- **When an alternative wins:** a long-running service with symbol churn (IPOs, delistings, option chains) needs deletion.
- **Label:** [Code] (there is no remove API); reasoning [Inferred].

---

## The three trade-offs to volunteer if asked "what would you change?"

1. **Lifetime check in `matches()`.** Hoist it out of the per-record path, for example by checking once per batch, or move to the handle/ID design (D11). That removes two atomic operations per record from Scan.
2. **Out-of-order filter insertion in compile.** Build filters unsorted, then sort once: O(F log F) instead of a worst case of O(F²).
3. **Observer de-duplication and the push model.** Switch to a pull-based epoch log (D10). That makes topic creation cost independent of the number of subscribers, and prepares for concurrency.

Say clearly that these are **unmeasured hypotheses**. You'd confirm them with P6's measurement harness first, which counts replay work and uses wall/CPU time plus simulated Cachegrind (hardware counters are blocked on this machine), before changing anything.
