# P2 overview: topics, subscriptions, oracle, driver

> Study guide for interview preparation. Evidence labels:
> **[Doc]** stated in a planning or review document · **[Code]** visible in the code · **[Inferred]** my reasoning, where the docs are silent.

## P2 in five sentences

1. P2 gives every market-data message a **name**, called a *topic*, such as `itch/AAPL/modify/executed`. It keeps those names in a **registry** that assigns compact integer IDs and groups topics into per-stock *partitions*.
2. It lets a reader describe what it wants as a **subscription**: a set of "exactly this topic" and "this topic and everything under it" terms.
3. It **compiles** that subscription into a per-partition bitmap, so the engine can answer "does this message match?" with a lookup and a bit test instead of string comparisons.
4. It builds a deliberately simple, **independent reference implementation**, the *oracle*. Every later engine phase is checked against it.
5. It builds a **deterministic driver** that replays a trace file into any publisher and simulates slow readers with seeded budgets and pauses.

## The same thing in one page

**The problem.** The engine stores a stream of messages. Each message belongs to one topic, and topics form a tree:

```
itch
├── AAPL                      ← partition (one per stock)
│   ├── add
│   │   ├── anon              ← "A" messages: new anonymous order
│   │   └── attributed        ← "F" messages: new order with firm ID
│   ├── modify
│   │   ├── executed          ← "E": order filled
│   │   ├── executed_px       ← "C": filled at a different price
│   │   ├── cancel            ← "X"
│   │   ├── delete            ← "D"
│   │   └── replace           ← "U"
│   ├── trade
│   │   ├── noncross          ← "P"
│   │   └── cross             ← "Q": auction print
│   └── stock/...             ← directory, halts, Reg SHO, LULD …
├── MSFT …
└── _market                   ← market-wide events (open/close, circuit breakers)
    └── system_event
```

[Doc] ARCHITECTURE §2.1 derives this tree from the ITCH 5.0 specification's own sections, so an ordinary user would choose it without knowing anything about storage internals.

**Readers want slices of this tree.** [Doc] ARCHITECTURE §2.3 lists the consumers:

| Consumer | What it subscribes to for stock S |
|---|---|
| BOOK: rebuild the order book | `Subtree(itch/S/add)`, `Subtree(itch/S/modify)`, `Subtree(itch/S/stock)`, `Subtree(itch/_market)` |
| TAPE: trades and executions | `Exact(itch/S/modify/executed)`, `Exact(itch/S/modify/executed_px)`, `Subtree(itch/S/trade)` |
| AUCT: auctions | `Exact(itch/S/noii)`, `Exact(itch/S/trade/cross)` |
| STAT: halt/LULD monitor | `Subtree(itch/S/stock)` |
| REPLAY: everything for a basket | `Subtree(itch/S)` for each S |

**What P2 contributes:**

- **Registry** (`src/tiplog/topics/`). It turns strings into IDs:
  - a global `TopicId`;
  - a `PartitionId`, meaning which stock the topic belongs to;
  - a `local_id`, a small number that is unique only within its partition.

  Interning one path also creates its missing ancestors. Interning is **all-or-nothing**: if anything fails, nothing changes.
- **Subscriptions** (`src/tiplog/subs/`). These do three jobs:
  - Normalize the term list by removing duplicates and terms already covered by another term.
  - Compile it into one *filter* per partition. A filter is either "all topics in this partition" or a bitset of local IDs.
  - Keep the filter current when new topics appear later, using an observer hook.
- **Oracle** (`tests/ref/`). This is a slow, test-only model of the whole replay contract. It shares **only** the plain value types with production code, so a bug in production cannot hide by being copied into the checker.
- **Driver** (`src/tiplog/driver/`, `tools/tiplog_sim/`). It reads a trace, publishes each record through a callback, and after each publish tells the "consumer" how much it may read (its *budget*). Pauses and seeded jitter simulate slow readers reproducibly.

## Where P2 sits

```
         PUBLISH SIDE                                  READ SIDE
 trace file (P1)                              reader: "AAPL book since seq 1000"
     │                                                   │
     ▼                                                   ▼
 driver::drive_trace ──publish(path,payload)──►  subs::compile(registry, spec)
     │                         │                   │  normalize terms
     │                         ▼                   │  intern roots
     │              Engine::intern(path)           │  build PartitionFilters
     │              → topics::Registry ◄──observe──┘  register hooks on Subtree roots
     │                 (IDs, partitions,
     │                  local IDs, hooks fire
     │                  on new topics)
     ▼                         │
 Tick{budget,paused} ──────────┼──────────►  Engine replay (P3–P5)
                               ▼               • Scan: sub.matches(topic) per record
                        ring + index (P3/P4)   • Indexed: one cursor per filter
                                                 partition, then filter->matches(local_id)

 Test-only, beside everything:  ref::ScanOracle  (own matcher, own retention model)
```

## What later phases need from P2 [Code]

| Consumer | What it uses | Where |
|---|---|---|
| Engine replay setup | `sub.belongs_to(registry)` rejects a subscription compiled for another engine | `src/tiplog/engine/engine.cpp:150` |
| Mode choice | `sub.wide()` forces Scan; Auto falls back to Scan when `filters().size()` exceeds `auto_max_partitions` (default 64) | `engine.cpp:156-163`, `engine.hpp:38` |
| Indexed replay | `filters()` gives the list of partitions, one index cursor each; `filter->matches(topic.local_id)` drops unwanted event types inside a partition | `engine.cpp:167-169`, `engine.cpp:314`, `engine.cpp:332` |
| Scan replay | `sub_.matches(item.topic)` for every retained DATA record | `engine.cpp:361` |
| Index ownership | `index::none = UINT32_MAX` marks a free block. P2 never assigns partition ID `UINT32_MAX`, so the sentinel cannot collide | `src/tiplog/index/index.hpp:14`, `registry.hpp:37-38` |
| Lifetime of filter views | Spans from `filters()` may be invalidated by `intern()`, so the engine re-acquires filter pointers at every batch | comment at `engine.cpp:299` |
| Differential tests (P3–P5) | `ref::ScanOracle` is the expected answer for 108M randomized operations in P6's final run | `results/p6/CC2-all-configurations.json` |

## Glossary

| Term | Meaning here |
|---|---|
| **Topic** | A `/`-separated name with non-empty segments, e.g. `itch/AAPL/add/anon` |
| **Segment** | One piece between slashes: `itch`, `AAPL`, `add`, `anon` |
| **Depth** | Number of segments; `itch` is 1 and `itch/AAPL/add/anon` is 4 |
| **Ancestor** | A prefix ending at a segment boundary; `itch/AAPL` is an ancestor of `itch/AAPL/add`, and `itch/AA` is not |
| **Intern** | Look a path up and create it (plus missing ancestors) if absent, returning its ID |
| **Partition** | The topic's ancestor at depth `min(2, depth)`; in practice one per stock, plus `itch/_market` |
| **Local ID** | A dense number (0, 1, 2 …) for a topic within its partition, stored as `uint16_t` |
| **Exact term** | `Exact(t)` matches topic `t` only |
| **Subtree term** | `Subtree(p)` matches `p` itself and everything below it at segment boundaries |
| **Union semantics** | A message matching several terms is still delivered once |
| **Normalization** | Rewriting a term list into a canonical, minimal form with the same meaning |
| **Wide term** | A Subtree term rooted at depth 1, such as `Subtree(itch)`; it spans partitions that don't exist yet, so the engine uses Scan |
| **Partition filter** | Per partition: `all = true`, or a bitset of selected local IDs |
| **Observer / hook** | A callback the registry runs when topics are created under a watched root |
| **Strong exception guarantee** | If an operation throws, program state is exactly as before |
| **Oracle** | An independent "obviously correct" implementation used to check the real one |
| **Differential testing** | Running the same random operations on two implementations and comparing results |
| **Seq** | Global message sequence number: dense, starts at 1 |
| **LogPos** | Logical byte position in the never-ending log, never reused |
| **DATA / PAD** | Ring items: a real record, or filler that skips to the physical end of the ring |
| **Budget** | Maximum records a reader may receive in one `next_batch` call |
| **Captured upper bound** | The last sequence a replay will return, fixed when the replay opens |

## Evidence summary

- **P2 gate** ([Doc] `results/p2/phase-gate.json`): 52/52 tests passed in both the release and ASan/UBSan presets. Those 52 include **37 P2 cases**: 16 topics/subscriptions, 16 oracle and 5 driver.
- The independent review found and fixed three bugs: the embedded-NUL path, the externally retained lifetime anchor, and quadratic reserve growth ([Doc] `results/p2/review.md`).
- **After P2**, P6 replaced quadratic subscription normalization. It added three tests, so topics/subscriptions now has 19; that suite passed 19/19 in release and in ASan/UBSan ([Doc] `results/p6/subscriptions-scaling.md`).
- The driver's real-trace smoke test published 10,000 events ([Doc] `results/p2/oracle-driver-sources.md`).
- P2 has **no performance benchmarks**. Any statement about speed in these guides is labeled [Inferred].

## 60-second explanation (memorize)

> "Phase 2 built the naming and filtering layer of my market-data log. Every Nasdaq ITCH message gets a hierarchical topic like `itch/AAPL/modify/executed`. A registry interns these into integer IDs and groups them into one partition per stock, mirroring the two-segment partitioning Jane Street describes for Aria. Readers subscribe with Exact and Subtree terms. I normalize those terms, then compile them into a per-partition bitset over small local IDs. On the hot path, matching is a lookup and a bit test, and the partition list tells the indexed replay which per-stock indexes to merge. New topics that appear later are pushed into existing subscriptions through a two-phase, all-or-nothing observer hook. Alongside that, I wrote an independent oracle that shares no logic with production. It does string matching and its own ring-retention arithmetic, and it became the reference for over a hundred million randomized differential operations in later phases."

## 5-minute explanation (outline to practice aloud)

1. **Context (30 s).** Bounded in-memory log, slow readers catch up, filtering cost is the bottleneck (Jane Street article). P2 is the naming and filtering foundation.
2. **Topic design (60 s).** Four levels taken from the ITCH spec. Partition = first two segments = one per stock. That gives a natural unit for the later per-partition index. Mention why `itch/SYM/type` would have been the wrong hierarchy for the storage-split experiment (ARCHITECTURE §2.2).
3. **Registry (60 s).** Dense IDs, with 0 meaning "no parent". u16 local IDs per partition drive bitsets. Interning is transactional: everything is prepared first, then committed with `noexcept`. Tested with injected `bad_alloc` and limit exhaustion.
4. **Subscriptions (75 s).** Union semantics, segment boundaries. Normalization removes covered terms. The P6 fix replaced the O(n²) normalizer with hash lookups of each path's ancestors, after 100,000 partitions timed out. Filters are `all` or a bitset. Wide terms force Scan. Hooks exist only for Subtree roots.
5. **Oracle (45 s).** Why independence matters. What it models: captured upper bound, conservative expiry, budget rules. Used by every later differential campaign.
6. **Driver (20 s).** Engine-neutral callbacks, seeded schedules, length-prefixed FNV digests for reproducibility.
7. **What I'd change (10 s).** Pick one honestly from `07-design-decisions.md`, for example sorted-vector filter insertion order or the `weak_ptr` lock in `matches()`.

## Files in this guide

| File | Content |
|---|---|
| `01-types.md` | Shared value types and why each width |
| `02-registry.md` | Registry walkthrough, IDs, transactions, observers, lifetime |
| `03-subscriptions.md` | Normalization, compilation, filters, hooks, ownership |
| `04-oracle.md` | Independent oracle: retention model and replay semantics |
| `05-driver.md` | Deterministic driver and CLI |
| `06-testing.md` | Every test, what it proves, bug stories |
| `07-design-decisions.md` | Decision table with alternatives |
| `08-question-bank.md` | 120+ grilling questions with answers |
| `09-exercises.md` | Whiteboard drills and bug hunts |
| `10-mock-interview.md` | 45-minute mock script and rubric |
