# 01 — Shared value types (`src/tiplog/types.hpp`)

This 52-line header is the vocabulary that **both** production code and the test oracle share. It contains only plain data: no logic and no helpers.

## Why a value-only header? [Doc]

The oracle must be independent of the engine ([Doc] VALIDATION_PLAN §2; `results/p2/review.md`: "The oracle's only project include is the value-only `types.hpp`"). If the oracle reused production matching or ring helpers, a bug in a helper would appear on both sides of the comparison and never be caught. Sharing *types* is safe, because a type cannot contain a matching or arithmetic bug. Sharing *functions* is not.

Interview line: *"The only coupling between my oracle and production is the shape of the data. They agree on what a checkpoint looks like, not on how it's computed."*

## Walkthrough

```cpp
using Seq = std::uint64_t;
using LogPos = std::uint64_t;
using TopicId = std::uint32_t;
using PartitionId = std::uint32_t;
```

These are type **aliases**, not distinct types. They document intent, but the compiler won't stop you passing a `TopicId` where a `PartitionId` is expected.

| Alias | Width | Why this width | Label |
|---|---|---|---|
| `Seq` | 64-bit | Dense global sequence starting at 1. The full ITCH day has 268,744,780 messages (P1). A 32-bit counter (≈4.29 billion) would last about 16 days at that rate, and a long-lived bus must never wrap. 64-bit is effectively infinite. | Count [Doc] P1 PROGRESS; arithmetic [Inferred] |
| `LogPos` | 64-bit | Logical byte offset that is **never recycled** (ARCHITECTURE §3.1, DD-02). The full day is 8.25 GB uncompressed, so 32-bit positions (4 GiB) would wrap within a single day. Never-recycled positions are what make stale references detectable. | Design [Doc] DD-02; arithmetic [Inferred] |
| `TopicId` | 32-bit | The full day produced 111,997 topics (P1), which is already too many for 16 bits. 32 bits is ample and halves the size of a 64-bit ID. | Count [Doc] PROGRESS P1; choice [Inferred] |
| `PartitionId` | 32-bit | ITCH has 8,907 partitions, which would fit in 16 bits. But the approved T3 experiment uses **100,000 partitions** (PROBLEM_STATEMENT §4). `UINT32_MAX` is also reserved as P4's free-block owner marker (`index::none`). | [Doc] + [Code] `registry.hpp:37`, `index.hpp:14` |

The **local ID** is `uint16_t`, but it lives in `topics::Topic`, not here. It is covered in `02-registry.md`.

```cpp
struct Term {
  enum Kind : std::uint8_t { Exact, Subtree };
  Kind kind{};
  std::string path;
  bool operator==(const Term&) const = default;
};
```

- **The enum is unscoped and nested** (`enum Kind`, not `enum class`). You write `Term::Exact`, which reads naturally. The `: std::uint8_t` fixes its size at one byte. [Code]
- **Declaration order matters.** `Exact = 0` and `Subtree = 1`, and normalization sorts by `(path, kind)`, so for the same path the Exact term sorts first. The sort does two jobs: it puts duplicates next to each other so `std::unique` can remove them, and it makes the output order deterministic. Which kind comes first for the same path doesn't affect correctness, because coverage is checked with a hash set (see `03`). [Code] `compiled.cpp:97-101`
- **`kind{}`** value-initializes to `Exact`. The code still validates `kind` explicitly, because a caller can `static_cast` an invalid value such as 7 or 99. The tests do exactly that (`topics_subs_test.cpp:280`, `oracle_test.cpp:113`).
- **`operator== = default`** is C++20: the compiler generates member-wise comparison. Tests rely on it heavily: `EXPECT_EQ(normalized.terms[0], (Term{...}))`.

```cpp
struct SubscriptionSpec {
  std::vector<Term> terms;
  bool operator==(const SubscriptionSpec&) const = default;
};
```

A spec is simply an **unordered union of terms**. Order and duplicates carry no meaning until normalization makes them canonical. An empty list is rejected by both `normalize` and the oracle ([Code] `compiled.cpp:89`, `scan_oracle.cpp:16`). The product defines a subscription as a *non-empty* union ([Doc] ARCHITECTURE §3.3).

```cpp
struct ResumeCheckpoint {
  Seq after_seq{};
  LogPos next_pos{};
  bool operator==(const ResumeCheckpoint&) const = default;
};
```

**This is the most interview-worthy type.** A checkpoint records *how far the reader has examined the log*, which is not the same as *the last message it received*. ([Doc] ARCHITECTURE §9 comment: "logical progress, not last output".)

- `after_seq`: resume after this sequence number.
- `next_pos`: the byte position of the first unread item.

Why not simply store `last_delivered`? Suppose a TAPE reader wants only executions. It may scan a million filtered-out records after its last delivery. If it resumed from `last_delivered`, it would rescan them all, or worse, be told its history expired just because records it had already examined were evicted. The checkpoint lets a completed snapshot that delivered **zero** messages still advance progress ([Doc] ARCHITECTURE §3.7; test `OracleReplay.CompletedZeroOutputSnapshotAdvancesProgressAndChainsFromUpper`).

```cpp
enum class ReplayMode : std::uint8_t { Scan, Indexed, Auto };
enum class MergeKernel : std::uint8_t { StdPQ, BinHeap, Quad, Loser };
enum class PoolPolicy : std::uint8_t { ForceEvict, RejectPublish };
enum class Status : std::uint8_t { More, Done, Error };
```

These are scoped enums (`enum class`): no implicit conversion to `int`, and the names don't leak into the namespace. They are declared in P2 because the oracle and the later engine must agree on `Status`. `ReplayMode`, `MergeKernel` and `PoolPolicy` are used from P3–P5 onward [Code].

`Status` has three values:
- `More`: call again; there may be more.
- `Done`: this replay's captured range is finished.
- `Error`: check `error()`.

```cpp
struct Delivered {
  Seq seq{};
  LogPos pos{};
  TopicId topic{};
  std::span<const std::byte> payload;
};
```

- `payload` is a **non-owning view** into the engine's ring memory. Delivery copies nothing, but the view is valid only until the ring overwrites that region. [Doc] README: "Delivered byte spans are non-owning views subject to the documented Engine lifetime/publication rules."
- There is no `operator==` here. A span compares by identity, not content, so a defaulted comparison would be misleading. [Inferred]
- The oracle's own `OracleRecord` *copies* the payload instead (`scan_oracle.hpp:22`), because the oracle must be obviously correct, not fast.

```cpp
struct ReplayError {
  enum Kind : std::uint8_t { HistoryExpired, FellBehind };
  Kind kind{};
  Seq requested_after{};
  Seq last_delivered{};
  Seq oldest_retained{};
  bool operator==(const ReplayError&) const = default;
};
```

There are two failure kinds ([Doc] ARCHITECTURE §3.6):
- **HistoryExpired**: detected when the replay opens. The requested start was already overwritten, so nothing is delivered.
- **FellBehind**: detected during the replay. The reader was too slow and unread data was overwritten. Everything delivered before the error is a correct prefix (invariant Q3).

The three `Seq` fields let the client decide what to do next (for example, fall back to disk recovery in roadmap R2) without guessing. Tests compare all four fields exactly, e.g. `ReplayError{FellBehind, 0, 1, 3}` (`oracle_test.cpp:175`).

## Likely questions on this file

1. **"Why aliases instead of strong types?"** Aliases are zero-cost and simple, but they allow mix-ups. A strong-typedef wrapper (`struct TopicId { uint32_t v; }`) would catch them at compile time, at the cost of boilerplate for hashing, comparison and formatting. [Inferred] For a four-week project this was a reasonable trade; in a production codebase I'd consider strong types for IDs.
2. **"Why is `Seq` dense and global?"** It defines the single canonical order across all topics, as Aria does ([Doc] ARCHITECTURE §3.1 citing S03). Dense means a filtered stream has gaps that are expected, while an unexpected gap in the global sequence means loss.
3. **"Why separate `Seq` and `LogPos`?"** `Seq` counts messages; `LogPos` locates bytes. The ring needs byte positions for eviction and wraparound, and readers need sequence numbers for ordering and resuming. They are strictly co-monotone ([Doc] ARCHITECTURE §3.1), so either one orders records, but only `LogPos` lets you find bytes and detect eviction (`next_pos < tail_pos`).
4. **"Why is `payload` a span and not a `vector`?"** It avoids copying on the hot path. The trade-off is lifetime risk, which the engine's documented rules manage.
