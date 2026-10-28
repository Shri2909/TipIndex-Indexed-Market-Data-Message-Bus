# 04 — The independent oracle (`tests/ref/scan_oracle.hpp`, `scan_oracle.cpp`)

## What a test oracle is, and why this one exists

A **test oracle** is anything that tells you the *right answer* for a test input. For a few hand-written cases, you can compute the answer yourself and write it into the test (a "golden" test). For **millions of random operations** you need a program to produce the answer, and that program must be trustworthy *independently* of the code it checks.

**`ref::ScanOracle` is that program.** It models the whole engine contract: publish, retention, matching and replay. It is written to be **obviously correct rather than fast**:
- it keeps the full history;
- it matches by comparing strings;
- it recomputes ring positions with plain arithmetic.

**Why independence matters** [Doc] VALIDATION §2, DD-17 ("Testing only against own implementation" is the rejected alternative): if the oracle called the engine's `prefix_at_boundary` or the ring's alignment helper, a bug in that helper would produce the *same wrong answer on both sides*, and the comparison would pass. This is called a **common-mode failure**.

The oracle shares **only** `types.hpp` (value types) with production code [Doc] review.md: "The oracle's only project include is the value-only `types.hpp`; no production topic, subscription, ring or retention helper is reused."

**How the build enforces it** [Code] `cmake/p2_ref.cmake:9-13`:
```cmake
if(BUILD_TESTING)
  add_library(tiplog_ref tests/ref/scan_oracle.cpp)
  target_link_libraries(tiplog_ref PUBLIC tiplog::build_options)   # no tiplog::topics_subs, no ring
  ...
endif()
```
In the same file, `tiplog_sim` links only `tiplog::driver` (lines 6–7). The only post-P2 change to this file is three lines for P5's `oracle_tail` test (`scripts/git.sh diff d4e5b83 -- cmake/p2_ref.cmake`).
- `tiplog_ref` links **nothing** from production except build flags, so it couldn't call production matching even by accident.
- It only exists when tests are built. `tiplog_sim` (production CLI) links `tiplog::driver` only.

[Doc] phase-gate.json: "tiplog_sim links production driver/trace only; test reference stays test-only".

**What it's used for later.** It is the expected answer in every CC-2 differential campaign. In P6's final run that was 90M release + 18M sanitizer operations, across all 9 mode/kernel configurations ([Doc] PROGRESS P6).

## The data it keeps

```cpp
struct OracleRecord { Seq seq; LogPos pos; std::string path; std::vector<std::byte> payload; std::uint64_t size; };
struct OracleItem   { LogPos pos; std::uint64_t size; std::optional<Seq> seq; };  // nullopt = PAD
class ScanOracle {
  Config config_;
  std::vector<OracleRecord> records_;    // EVERY record ever published (never trimmed)
  std::vector<OracleItem> items_;        // DATA and PAD items, in log order
  std::size_t first_retained_item_{};    // index of the oldest retained item
  LogPos head_pos_{};  Seq next_seq_{1};
};
```
[Code] `scan_oracle.hpp:18-68`

- **Full history.** `records_[seq - 1]` is the record with sequence `seq`, because sequences are dense from 1. It never forgets, which makes "what *should* have been retained?" a pure calculation.
- **Payloads are copied.** The engine hands out views into ring memory. The oracle copies, so later overwrites can't change what it remembers. Test: `CapturedUpperExcludesLaterPublicationAndCopiesPayload` mutates the caller's buffer after publishing and checks the oracle still has the old bytes.
- Memory grows forever, which is fine for tests with thousands of operations [Inferred].

## The retention model

### Configuration rules [Code] `scan_oracle.cpp:26-33`

| Rule | Why |
|---|---|
| `ring_bytes` is a power of two, from 32 to 2³¹ | Matches the production ring's precondition. The engine computes offsets with masks (`pos & (C−1)`), which only works for powers of two ([Doc] ARCHITECTURE §5.3) |
| `16 ≤ max_record_bytes`, a multiple of 8 | Minimum DATA record = 16-byte header + empty payload; everything is 8-byte aligned |
| `max_record_bytes ≤ ring_bytes / 2` | Guarantees `pad + need ≤ C`. A pad is always smaller than the record that forced it, so pad + record < 2 × record ≤ C ([Doc] ARCHITECTURE §5.3 "Core precondition") |
| `position_limit ≥ 16`, `sequence_limit ≥ 2` | Small synthetic limits let tests reach "lifetime exhausted" quickly. The default `position_limit` is 2⁵¹, the same as production (`ring.hpp:18`, `merge/kernels.hpp:21`), because merge keys pack a position into 51 bits |

### `publish()`, annotated [Code] `scan_oracle.cpp:35-72`

```cpp
validate_path(path);                                             // its OWN copy of the path rules
if (payload.size() > max_size - 16) throw std::length_error(...);
const std::uint64_t bytes = 16 + payload.size();                  // 16-byte header + payload
const std::uint64_t need  = ((bytes + 7) / 8) * 8;                // round up to 8 by DIVISION
const auto remainder = head_pos_ % config_.ring_bytes;            // physical offset by MODULO
const auto space = config_.ring_bytes - remainder;                // room to the physical end
const auto pad = space < need ? space : 0;                        // doesn't fit ⇒ PAD to the end
const auto advance = pad + need;
if (head_pos_ >= position_limit || advance >= position_limit - head_pos_ || next_seq_ >= sequence_limit)
  throw std::overflow_error("oracle logical lifetime exhausted");   // checked BEFORE adding
```

- **Different arithmetic from production, on purpose.** The comment at lines 37–38 says: "Division-based alignment and modulo-based placement intentionally avoid the production ring's packed header, alignment and masking helpers." Production uses `(x + 7) & ~7` and `pos & (C − 1)`. Two different formulas that agree on every input is good evidence both are right.
- **Overflow-safe check.** `advance >= limit - head` instead of `head + advance >= limit`, because the addition itself could wrap.

```cpp
OracleRecord record{next_seq_, head_pos_ + pad, std::string(path), copy of payload, need};
// All allocations precede visible state mutation, including retention.
if (records_.size() == records_.capacity()) records_.reserve(max(size + 1, capacity * 2));
if (new_items > items_.capacity())          items_.reserve(max(new_items, capacity * 2));
if (pad != 0) items_.push_back({head_pos_, pad, std::nullopt});    // PAD item
items_.push_back({record.pos, need, next_seq_});                   // DATA item
records_.push_back(std::move(record));
head_pos_ += advance;  ++next_seq_;
```

- The oracle itself gives the **strong guarantee**: every allocation (the record's string and payload, and both vectors' capacity) happens before any visible change. Test: `RejectsInvalidConfigsAndOversizedPublicationWithoutMutation` compares records, items, head and tail before and after a rejected publish.
- **Doubling growth.** The review found that an exact `reserve` made this quadratic, the same bug as in the registry ([Doc] review.md finding 3).

```cpp
const auto lower_bound = head_pos_ > ring_bytes ? head_pos_ - ring_bytes : 0;
while (first_retained_item_ < items_.size() && items_[first_retained_item_].pos < lower_bound)
  ++first_retained_item_;
```

- **The retention rule:** an item is retained if and only if its **start** position ≥ `head − C`. Eviction is of **whole items**, FIFO.
- This restates production's `ensure_space` loop ("evict from the tail while head + n − tail > C") as a predicate ([Doc] VALIDATION §2: "the tail is the smallest start ≥ end − C").
- A PAD is an item like any other, so it is retained or evicted whole.

`tail_pos()` is the first retained item's start, or `head_pos` if nothing is retained. `tail_seq()` is the first retained DATA's seq, skipping a retained PAD, or `next_seq_` if the ring is empty [Code] `scan_oracle.cpp:74-83`.

### Hand-computed example (test `OracleRetention.V09HandComputedPadAndWrap`, ring C = 64, max record 32)

| Step | Payload | need | head before | offset | space | PAD? | DATA at | head after | head − C | tail_pos | tail_seq |
|---|---|---|---|---|---|---|---|---|---|---|---|
| seq 1 | 10 B | 32 | 0 | 0 | 64 | — | 0 | 32 | — | 0 | 1 |
| seq 2 | 4 B | 24 | 32 | 32 | 32 | — | 32 | 56 | — | 0 | 1 |
| seq 3 | 8 B | 24 | 56 | 56 | **8 < 24** | **PAD [56,64)** | 64 | 88 | 24 | **32** (seq 1 evicted) | 2 |
| seq 4 | 0 B | **16** | 88 | 24 | 40 | — | 88 | 104 | 40 | **56** (the PAD is the oldest item) | 3 |
| seq 5 | 8 B | 24 | 104 | 40 | **24 = 24** | — (exact fit, no PAD) | 104 | 128 | 64 | 64 | 3 |

Points this pins down:
- The PAD is only 8 bytes, which is legal because the minimum PAD is 8 (`OracleItem{56, 8, nullopt}`).
- An **empty** DATA record still takes 16 bytes. It's not confused with a PAD (line 42 of the test).
- An **exact fit** to the physical end needs no PAD (also `V09ExactPhysicalFitHasNoPadAndWholeRecordEviction`).
- A retained PAD makes `tail_pos` (56) differ from the position of the first retained DATA (64).

## The matcher [Code] `scan_oracle.cpp:94-104`

```cpp
for (const auto& term : sub.terms) {
  if (path == term.path) return true;                                   // Exact, or Subtree root itself
  if (term.kind == Term::Subtree && path.size() > term.path.size() &&
      path.compare(0, term.path.size(), term.path) == 0 && path[term.path.size()] == '/')
    return true;                                                         // strict descendant at a boundary
}
return false;
```

- **No IDs, no partitions, no normalization, no bitsets.** It works on raw strings and loops over every term. It is O(terms × length) per record, which is fine for a reference.
- `path == term.path` matches for **both** kinds, because a Subtree includes its root.
- Test `OracleMatching.IndependentPathBoundaryAndUnion`: `Subtree(itch/A)` must not match `itch/AB/add`, and `Exact(other/path)` must not match `other/path/child`.
- It also has its **own** `validate_path` and `validate_subscription` (lines 9–23). It doesn't call `Registry::validate_path`.

## Replay semantics: what the oracle models

[Doc] ARCHITECTURE §3.6–3.7. The engine must behave **identically** in Scan, Indexed and Auto modes (invariant Q7). The oracle is the reference for all three.

### Opening a replay [Code] `scan_oracle.cpp:110-131`

```cpp
OracleReplay(oracle, sub, after_seq)
  : upper_seq_(oracle.head_seq() - 1),       // CAPTURED: last published seq at open
    upper_pos_(oracle.head_pos()),           // CAPTURED: exclusive end position
    end_record_(oracle.full_records().size()) {
  validate_subscription(sub_);
  if (after_seq >= upper_seq_) {             // nothing to deliver (also covers UINT64_MAX)
    status_ = Done;
    if (after_seq == upper_seq_) checkpoint_ = {upper_seq_, upper_pos_};   // exactly caught up
    return;                                  // future start ⇒ no checkpoint
  }
  if (after_seq + 1 < oracle.tail_seq()) {   // first wanted seq already evicted
    status_ = Error; error_ = {HistoryExpired, after_seq, after_seq, tail_seq}; return;
  }
  next_record_ = after_seq;                  // records_[after_seq] has seq after_seq + 1
  checkpoint_ = {after_seq, records_[after_seq].pos};   // position of that DATA, skipping any PAD
}
```

| Concept | Meaning | Test |
|---|---|---|
| **Captured upper bound** | The replay delivers only seqs in `(after_seq, upper_seq]`, fixed at open. Records published afterwards belong to the *next* snapshot (invariant Q5) | `CapturedUpperExcludesLaterPublicationAndCopiesPayload`: publish 2, open, publish a 3rd; only 2 are delivered and upper_seq is 2 |
| **Check before +1** | `after_seq >= upper_seq` is tested *before* computing `after_seq + 1`, so `after_seq = UINT64_MAX` can't wrap to 0 | `EmptyFutureAndExtremeQueriesAvoidOverflow` |
| **Future start** | `after_seq > upper_seq` is an empty query with **no checkpoint**, since there is no real progress to report | same test: `future.checkpoint()` is empty |
| **Exactly caught up** | `after_seq == upper_seq`: Done, with checkpoint `{upper_seq, upper_pos}` | same test: `{1, 16}` |
| **HistoryExpired** | Raised at open if `after_seq + 1 < tail_seq`. Nothing is delivered, and the terminal state is stable | `HistoryExpiredHasExactFieldsAndStableTerminalState`: C = 64, four 32-byte records leave tail_seq 3; opening after 1 gives `{HistoryExpired, 1, 1, 3}`, and later calls still return Error |
| **Open skips a PAD** | The checkpoint points at the next **DATA**, not at a PAD before it | `SeqOnlyOpenSkipsPadWhileFullBatchCanCheckpointBeforePad`: after seq 2, the checkpoint is `{2, 64}`, skipping the PAD at 56 |

### `next_batch(max, out)` [Code] `scan_oracle.cpp:133-159`

```cpp
out.clear();
if (max == 0 || status_ != More) return status_;                  // (a) zero budget / already terminal
if (checkpoint_->next_pos == upper_pos_) {                         // (b) complete BEFORE expiry check
  status_ = Done; checkpoint_ = {upper_seq_, upper_pos_}; return status_;
}
if (checkpoint_->next_pos < oracle_->tail_pos()) {                 // (c) conservative expiry
  status_ = Error; error_ = {FellBehind, requested_after_, last_delivered_, tail_seq}; return status_;
}
while (next_record_ < end_record_) {                               // (d) walk captured history
  const auto& record = records_[next_record_++];
  checkpoint_ = {record.seq, record.pos + record.size};            // progress past EVERY record
  if (matches(sub_, record.path)) {
    out.push_back(record); last_delivered_ = record.seq;
    if (out.size() == max) return More;                            // (e) stop right after last delivery
  }
}
checkpoint_ = {upper_seq_, upper_pos_}; status_ = Done; return status_;   // (f) exhausted
```

**(a) A zero budget does nothing.** `max = 0` neither advances progress nor checks expiry. It also doesn't turn a pending replay into an error: test `ConservativeExpiryIncludesIrrelevantRecordsAndZeroBudgetDefersCheck` gets `More` with an unchanged checkpoint from `next_batch(0)`, and only the next positive call reports the error. Once a replay is terminal (Done or Error), every later call returns the same status.

**(b) Completion is checked before expiry.** Test `ExactFinalBudgetIsDoneBeforeExpiryOnNextPositiveCall`:
```
C = 32. publish a(seq 1, pos 0..16). open Exact(a) after 0 → upper = {1, 16}.
next_batch(1) → delivers seq 1, budget exactly full → More, checkpoint {1,16}.
publish 4 × b  → everything old is evicted (tail_pos 48 > 16).
next_batch(1) → next_pos 16 == upper_pos 16 → Done   (NOT FellBehind)
```
- **Why:** the reader already received everything in its range. It would be wrong to call that a failure just because the budget happened to end exactly at the last record.
- **Why return More in the first place?** Returning More when the budget fills, without peeking ahead, keeps all modes uniform. Scan would need to scan forward to prove nothing more matches, while Indexed might know immediately. Peeking would make the modes' outputs and checkpoints differ ([Doc] ARCHITECTURE §3.6; README: "Positive full-budget batches return More immediately; a later positive poll establishes completion").

**(c) FellBehind is conservative.** The check compares the **unread position** with the tail. It triggers even if every evicted unread record was *irrelevant* to this subscription:
```
C = 64. publish a/irrelevant (pos 0), b/match (pos 32). open Subtree(b) after 0 → checkpoint {0, 0}.
publish a/irrelevant → tail_pos 32, so pos 0 is evicted.
next_batch(1) → 0 < 32 → FellBehind{requested 0, last_delivered 0, oldest_retained 2}
```
The matching record (seq 2) is **still in the ring**, yet the replay fails. Why accept that [Doc + Inferred]?
- **One rule for every mode.** Scan doesn't know whether an evicted record matched without having read it. Indexed could know. Making the rule depend on the mode would break Q7 (identical outcomes across modes), and with it the ability to compare modes exactly in differential tests [Doc] §3.6: "This intentionally conservative rule includes eviction of irrelevant records and is identical in Scan/Indexed/Auto."
- **Safe ordering.** The check runs **before** dereferencing ring or index memory, so a reader never reads overwritten bytes.
- **Cost:** a slow reader with a narrow subscription can be failed unnecessarily. The fix would be per-mode precise expiry, at the price of mode-dependent semantics.

**(d) Progress advances over filtered records.** The checkpoint moves past every record the batch *examined*, not just delivered ones. This is the difference between "progress" and "last delivered" from `01-types.md`.

**(e) No look-ahead across a filtered gap.** When the budget fills, the batch returns **immediately after the last delivered record**. It doesn't keep scanning through non-matching records to advance the checkpoint further. Test `FullBudgetDoesNotLookAheadAcrossFilteredGap`: after delivering seq 1, the checkpoint is `{1, 16}`, not past the following `b` records. When 7 more `b`s evict position 16, the next call reports FellBehind with `last_delivered = 1`. A look-ahead would again have made modes differ.

**(f) Exhaustion moves the checkpoint to the upper bound, even with zero output.** Test `CompletedZeroOutputSnapshotAdvancesProgressAndChainsFromUpper`:
```
publish b, b. open Exact(a) after 0 → Done, delivered nothing, checkpoint {2, 32}.
publish a (seq 3). open Exact(a) after checkpoint.after_seq = 2 → delivers seq 3.
```
This is how the live **Tail** chains snapshots ([Doc] §3.7): resume from `after_seq` of the last completed snapshot, never from `last_delivered`. Otherwise a quiet subscriber would rescan, or wrongly expire on, ranges it already examined.

**Error fields keep the delivered prefix exact** (invariant Q3). Test `ErrorPreservesExactDeliveredPrefixAndLastDelivered`: seq 1 is delivered, eviction happens, and the error reports `last_delivered = 1`. The checkpoint stays `{1, 32}`, so the client knows exactly which prefix it received.

**Equal payloads stay distinct events.** Test `EqualValuedDistinctSequenceEventsSurviveUnion` publishes three identical `a/b` messages with an overlapping `{Exact(a/b), Subtree(a)}` subscription. Exactly 3 are delivered, seqs 1, 2, 3, with no duplicates from the overlap and nothing dropped for having equal payloads ([Doc] ARCHITECTURE §3.7, citing S61: repeated prices are real events).

## Why it can be slow and simple

- Its complexity is fine for tests: O(history) per replay, O(terms × length) per match, and `tail_seq()` scans from the first retained item [Inferred].
- **Correctness of the oracle itself** is established by hand-computed golden cases (V09). Those are the only tests where a human, not a program, computed the expected values.
- Its non-owning `const ScanOracle*` inside `OracleReplay` follows the ordinary rule that the oracle must outlive its replays ([Doc] review.md).

## What the oracle does *not* model (limits to admit in an interview) [Inferred]

- **Index-pool pressure policies** (ForceEvict/RejectPublish). Those are P4 behaviours. The ring invariant R7 notes that the oracle must use "the same declared pressure policy" when pressure is exercised. P4's F3 fuzz added an independent pressure fixture for this (`tests/fuzz/pressure_fixture.hpp`).
- **The Tail chaining API itself.** That came in P5 with `oracle_tail.hpp`.
- **Concurrency, durability and timing.** It can say *what* must be delivered, never *how fast*.
- A **specification bug** (a wrong rule in ARCHITECTURE §3.6) would be faithfully reproduced by both sides. Independence protects against implementation bugs, not specification bugs. The hand-computed V09 cases and the review of the contract are the defence there.

## Ten questions to make sure you can answer

1. Why can't the oracle use the registry's `validate_path`?
2. Compute head, tail and the PAD for publishing 10, 4 and 8 payload bytes into a 64-byte ring.
3. Why must `max_record ≤ C/2`?
4. What is the captured upper bound, and what invariant does it protect?
5. Why is FellBehind triggered by evicted *irrelevant* records?
6. Why does a full budget return More instead of Done when nothing else matches?
7. Why does a zero-output completed snapshot still advance the checkpoint?
8. Why compare `after_seq >= upper_seq` before computing `after_seq + 1`?
9. What kinds of bugs can an independent oracle *not* catch?
10. How does CMake guarantee the oracle never links production matching code?
