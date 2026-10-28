# 08 — Question bank (P2)

Format: **difficulty** ★ (warm-up) to ★★★★ (senior or curveball) · **A** = model answer · **Ref** = where to look · **F** = likely follow-ups · **Trap** = common wrong answer.

There are 151 questions in 13 groups. Practise saying each answer aloud in under 45 seconds. Labels in answers: [Inferred] means the docs don't state it, so present it as your reasoning.

**F** and **Trap** lines appear where an interviewer is likely to push or where candidates commonly slip. For the other questions, the natural follow-up is "why?" or "what would you change?", which the referenced guide file (`02`–`07`) answers in depth.

---

## A. Fundamentals

**A1 ★ What does Phase 2 do?**
A: It's the naming and filtering layer. A registry turns topic paths into compact IDs grouped into per-stock partitions, and subscriptions are compiled into per-partition bitsets kept current as topics appear. It also includes an independent test oracle for the whole replay contract and a deterministic driver that replays traces with simulated slow readers.
Ref: `00-overview.md`.
F: *Why is filtering the important part?* → The article's bottleneck was CPU spent filtering the whole stream for catch-up readers.
Trap: saying P2 "stores messages". It doesn't; the ring is P3.

**A2 ★ Define topic, partition and local ID.**
A: A topic is a slash-separated path with non-empty segments. Its partition is its ancestor at depth min(2, depth), i.e. one per symbol. Its local ID is a dense 16-bit number unique within the partition, used as a bit position in filters.
Ref: `registry.hpp:20-34`.
F: *Partition of `itch`?* → Its own partition, containing only itself.

**A3 ★ Exact vs Subtree?**
A: `Exact(t)` matches only `t`. `Subtree(p)` matches `p` and every descendant at a segment boundary, so `Subtree(itch/AAPL)` matches `itch/AAPL/add/anon` but not `itch/AAPLX/add`. Subtree terms also match topics created later.
Ref: ARCHITECTURE §3.2.
Trap: using `starts_with` without the boundary check.

**A4 ★★ What is union semantics and how is it guaranteed?**
A: A message matching several terms of one subscription is delivered once. Each record belongs to one partition, each subscription has one filter per partition, and one bit (or `all`) decides, so there's nothing to de-duplicate. The rejected alternative was one cursor per term plus de-duplication.
Ref: DD-09, `compiled.cpp:82-86`.
F: *Two subscriptions both matching?* → Each gets it once; they're independent streams.

**A5 ★ What is a wide subscription?**
A: One with a depth-1 Subtree term like `Subtree(itch)`. It covers every partition, including future ones. The engine serves it by Scan, because indexed replay would merge a cursor for every partition.
Ref: `compiled.cpp:212-215`, `engine.cpp:156`.

**A6 ★★ Why IDs instead of strings on the hot path?**
A: Scan checks every record. With strings, that's a comparison per term per record; with IDs, it's an array index, a binary search and a bit test, independent of term count. IDs also make filters compact bitsets.
F: *Where are strings still used?* → Only at intern/compile time and in the oracle.

**A7 ★ What does `intern` mean?**
A: Find the path's ID, or create the topic and any missing ancestors and return the new ID. Calling it again with the same path returns the same ID.
Ref: `registry.cpp:125-241`.

**A8 ★★ Checkpoint vs `last_delivered`?**
A: `last_delivered` is the last message the reader got. The checkpoint `{after_seq, next_pos}` is how far it has *examined*, including filtered records. A reader that filters out a million records after its last delivery resumes from the checkpoint, so it doesn't rescan them or falsely expire.
Ref: `types.hpp:26-30`, ARCHITECTURE §3.7.
Trap: "they're the same thing".

**A9 ★ What is the oracle and why is it independent?**
A: A slow, obviously correct model of publish, retention, matching and replay, used as the expected answer in differential tests. It shares only value types with production, so a bug in a production helper can't appear on both sides and cancel out.
Ref: `scan_oracle.hpp:3-4`, `cmake/p2_ref.cmake:9-13`.

**A10 ★ What does the driver do?**
A: It reads a trace in order, publishes each record through a callback, and after each publish emits a tick with the consumer's budget or a pause. The schedule is seeded and deterministic.
Ref: `trace_driver.hpp:57-61`.

**A11 ★★ What do P3–P5 need from P2?**
A: Topic IDs and local IDs for every record; `filters()` for the list of partitions to open index cursors on; `partition_filter()->matches(local_id)` to drop unwanted event types inside a partition; `wide()` and the filter count for mode choice; `belongs_to` for safety; and the oracle for differential tests.
Ref: `engine.cpp:150-169, 314, 332, 361`.

**A12 ★★ What came from the Jane Street article and what's yours?**
A: From the article: the hierarchical namespace, subtree subscriptions, two-segment partitions, and a per-partition index merged with a heap. Mine (independent design): normalization, u16 local IDs with bitset filters, the transactional observer hooks, wide-term scan selection, and the oracle and driver. The article publishes no code, so none was reconstructed.
Ref: `results/p2/topics-sources.md` ("Published Jane Street claims are limited to…").
Trap: implying you reproduced Aria.

---

## B. Registry, code level

**B1 ★ Intern `itch/MSFT/trade/cross` into a registry that has `itch/AAPL/add/anon` (IDs 1–4).**
A: `itch` exists (ID 1). `itch/MSFT` is new at depth 2: ID 5, new partition 2, local 0. `itch/MSFT/trade` is ID 6, partition 2, local 1. `itch/MSFT/trade/cross` is ID 7, local 2. It returns 7.
Ref: `registry.cpp:144-187`.
F: *Again?* → 7, through the fast path.

**B2 ★ Why do topic IDs start at 1?**
A: 0 is the "no parent" sentinel, which ends the ancestor walk (`while (ancestor != 0)`) and avoids `optional` in every Topic. IDs map to `topics_[id-1]`.
Ref: `registry.hpp:23`, `registry.cpp:85, 206`.

**B3 ★★ Which partition does `itch` get?**
A: Its own: a depth ≤ 2 topic creates a partition. In the test it's partition 0 with `topic_count` 1. A `Subtree(itch)` filter therefore includes partition 0 with `all`.
Ref: `topics_subs_test.cpp:86-100`.

**B4 ★★ How are local IDs assigned, and what happens at 65,536?**
A: Each new topic gets `existing topic_count + topics already planned in this call` for its partition; the root gets 0. If that would reach `max_local_topics` (default 65,536), intern throws `RepresentationLimit` **before** creating anything, including missing ancestors.
Ref: `registry.cpp:173-179`; test `FullUint16BoundaryAndLateBitsetGrowth`.

**B5 ★★ Why u16 local IDs?**
A: They're bit positions, so small is good. ITCH partitions have 4–21 topics, so one 64-bit word covers a stock. u16 is a generous ceiling that is enforced, not assumed; u8 would be fragile for other hierarchies and u32 wasteful.
F: *Need more?* → Make the limit configurable to a wider type; the docs allow "explicitly select a wider configured representation" (ARCHITECTURE §5.1).

**B6 ★★★ Describe intern's structure.**
A: Validate; fast-path lookup; plan every missing prefix into local `pending` and `new_partitions` while checking all limits; stage hash nodes in a temporary map; reserve all destination capacity; collect affected observers by walking up from each new topic; call each observer's `prepare`; then commit using only non-throwing operations: push into reserved vectors, add counts, splice nodes, and call `noexcept` observer commits. Anything that throws happens before the first visible change.
Ref: `02-registry.md`.

**B7 ★★★ Why stage path nodes in a separate map?**
A: Hash-map insertion allocates a node and that can throw. Allocating the nodes into `staged_paths` first, then `extract`-ing and `insert`-ing the node handles into `paths_` after buckets were reserved, makes the commit allocation-free and rehash-free.
Ref: `registry.cpp:191-201, 233-236`.
F: *Why reserve buckets too?* → Without enough buckets, insert would rehash, which allocates.

**B8 ★★ Why `reserve_growth` instead of `reserve(size + k)`?**
A: `reserve(n)` sets capacity to exactly n, so calling it on every intern reallocates every time, which is quadratic. `reserve_growth` grows by at least 1.5×, restoring amortized O(1) while still reserving before the commit. The review found and fixed this.
Ref: `registry.cpp:9-16`; review finding 3.

**B9 ★★★ How does intern find which subscriptions to notify? What does it cost?**
A: For each new topic it walks up the parent chain and looks up each ancestor ID in the hub's `roots` map, locking each `weak_ptr` and de-duplicating by pointer. That's O(depth) lookups per new topic, independent of the total number of subscriptions, but the de-duplication is a linear search, so A affected observers cost O(A²).
Ref: `registry.cpp:203-222`.
F: *Fix the A²?* → An epoch stamp per observer, or an `unordered_set`.

**B10 ★★ Why are observers stored as `weak_ptr`?**
A: So the registry doesn't keep subscriptions alive. The subscription state also holds handles pointing back to the hub, so strong pointers both ways would form a cycle and leak.
Ref: `registry.cpp:21-28`.

**B11 ★★ What is `Slot::serial` for?**
A: A unique ticket per registration, so a handle removes exactly its own slot, even if the same observer registered on several roots or several times. Serial 0 marks an empty or moved-from handle, so numbering starts at 1. Exhaustion at `UINT64_MAX` is checked.
Ref: `registry.cpp:46-59, 105-123`.

**B12 ★★ Why is `ObserverHandle` move-only? What about self-move?**
A: It represents unique ownership of a registration, and two copies would unregister twice. A move transfers the serial with `std::exchange(other.serial_, 0)`. Move-assignment first resets its own registration, and the `this != &other` check stops self-move from unregistering itself.
Ref: `registry.cpp:35-45`.

**B13 ★★★ Why can a handle safely outlive the registry?**
A: It holds a `weak_ptr` to the hub, not a raw pointer. `reset()` does `hub_.lock()`, and if the registry is gone the hub is too, so it does nothing.
Ref: test `RegistryLifetimeSafeEvenWithExternallyRetainedAnchor` (`sub = {}` after destruction).

**B14 ★★★ Explain the retained-anchor bug.**
A: Subscriptions guarded their raw `Registry*` with `weak_ptr<Lifetime>`. But `identity()` is public, so a caller can lock it and hold the `shared_ptr`, keeping `Lifetime` alive after the registry dies, and the weak check would pass on a dangling pointer. The fix is an `alive_` flag cleared first in the destructor and checked together with `lock()`.
Ref: `registry.cpp:70`, `compiled.cpp:186-187`.
Trap: "weak_ptr tells you the owner is alive". It tells you *the pointee* is alive.

**B15 ★★ Why is `Registry` non-copyable and non-movable?**
A: [Inferred] Subscriptions store the registry's address, and a move would leave those pointers dangling; a copy would duplicate the hub and identity. Deleting both makes the address stable. To move one, hold it in a `unique_ptr`.
Ref: `registry.hpp:89-92`.

**B16 ★★ What does `validate_path` reject, and why reject rather than normalize?**
A: Empty paths, a leading or trailing `/`, `//`, and embedded NUL. Rejecting avoids aliases, where two spellings mean one topic. NUL was added after the review found the registry accepted it while the trace format and oracle rejected it.
Ref: `registry.cpp:74-79`.

**B17 ★★ What invalidates `get()` references and `all_topics()` spans?**
A: Any `intern` that grows `topics_` or `partitions_`, because vector reallocation moves elements. The header documents it, and callers must not hold them across interns.
Ref: `registry.hpp:94-95`.

**B18 ★★ Why are `Limits` fields `uint64_t` when IDs are 32-bit?**
A: So the constructor can detect a request that can't be represented, such as 2³² partitions, and reject it, instead of silently truncating. Tested with `1 << 32` and 65,537.
Ref: `registry.cpp:62-69`.

---

## C. Subscriptions, code level

**C1 ★ Normalize `{Exact a, Subtree a, Subtree a/b, Exact a-foo/x, Subtree a-foo}`.**
A: `{Subtree a, Subtree a-foo}`. `Exact a` is covered by `Subtree a` on the same path; `Subtree a/b` by its strict ancestor `a`; `Exact a-foo/x` by `Subtree a-foo`. `a-foo` isn't under `a`, because `-` isn't a segment boundary.

**C2 ★★★ Why does a sorted sweep with a "current root" fail?**
A: Raw string order isn't tree order: `-` (0x2D) sorts before `/` (0x2F), so `a`, `a-foo`, `a/b` interleave. A sweep that replaces its root with `a-foo` then misses that `a/b` is under `a`. The fix checks each term's own ancestors against a hash set, so order doesn't matter.
Ref: test `NormalizationHandlesLexicalInterleavingAndSamePathKinds`.
F: *Make a sweep work?* → Sort by segment sequence, not raw bytes, and keep a stack.

**C3 ★★ Why sort at all?**
A: `std::unique` removes only adjacent duplicates, and a canonical order makes output deterministic and idempotent: equal inputs in any order normalize identically.
Ref: `compiled.cpp:97-101`.

**C4 ★★ Exact and Subtree on the same path?**
A: Keep the Subtree and drop the Exact, because a subtree includes its root. `include_self` is true for Exact checks and false for Subtree checks, so a subtree isn't covered by itself.
Ref: `compiled.cpp:109-113`.

**C5 ★★ Why validate every term before interning any?**
A: So a malformed fifth term can't leave the first four interned. Validation is pure and happens in `normalize`; interning is the first side effect.
Ref: test `InvalidSpecsDoNotRegisterEarlierValidTerms`.

**C6 ★★★ Is `compile` strongly exception-safe?**
A: Not entirely. Malformed specs have no effect, and each intern is atomic. But if a later root's intern hits a representation limit, earlier roots stay interned. The registry remains consistent; it just has extra empty topics. So compile is basic-safe with respect to registry contents.
Ref: `compiled.cpp:204-211`.
Trap: claiming "fully transactional".

**C7 ★★ Why intern Exact topics at compile time?**
A: The topic then has a local ID immediately, so its bit can be set now. Since a topic is created only once, no future topic can match the Exact term, so it needs no hook. The side effect: subscriptions create permanent topics, even typos.
Ref: test `ExactPreinternedAndNoHookNeeded`.

**C8 ★★ Why do hooks exist only for Subtree terms?**
A: Only Subtree terms can match topics created in the future (descendants). Exact topics already exist after compile.
Ref: `compiled.cpp:225-230`.

**C9 ★★ When is `all` set, and what does it buy?**
A: When a matching Subtree root has depth ≤ 2 (the partition root or above), the whole partition matches. It needs no bits, and future topics in that partition need no update: `prepare` skips `exists && all`.
Ref: `compiled.cpp:50-52, 158`.

**C10 ★★ How does the bitset grow? Why `std::uint64_t{1} << n`?**
A: Lazily, `resize(word + 1)`, so the vector covers only up to the highest selected local ID; `matches` treats beyond-the-end as unset. A plain `1` is an `int`, and shifting it by 32 or more is undefined behaviour.
Ref: `compiled.cpp:69-86`.

**C11 ★★ Why a sorted vector of filters?**
A: Compact, cache-friendly, O(log F) lookup, and deterministic ordered iteration for the indexed merge. Insertion is O(F), but it's rare: only when a partition first matches.
F: *Dense array?* → O(1) lookup but O(all partitions) memory per subscription.

**C12 ★★★ What is compile's worst case for building filters?**
A: [Inferred] Topics are visited in ID order, and the first match in each partition inserts at its sorted position. If those first matches arrive in scrambled partition order, that's O(F) moves each, O(F²) total. Fix: collect, then sort once.
Ref: `compiled.cpp:217-224`.

**C13 ★★★ Walk through a late topic arriving in a partition with no filter yet.**
A: The registry's ancestor walk finds this subscription's hook on the Subtree root and calls `prepare(pending)`. `matching.matches` is true, `find_filter` finds no filter, so a fresh filter goes into `update->added` and gets the bit (or `all`). `prepare` reserves `filters` capacity. At commit, the staged filter is inserted at its sorted position: no allocation, nothrow moves.
Ref: `compiled.cpp:132-173`.

**C14 ★★ Why copy-then-swap instead of editing filters in place?**
A: If a *later* observer's `prepare` throws, this subscription must be untouched. Edits happen on staged copies; commit only swaps or moves.
Ref: test `ObserverAllocationFailurePrecedesAllRegistrationCommit`.

**C15 ★★ Copying vs moving a `CompiledSubscription`?**
A: A copy shares the same `CompiledState` (a refcount increment), so both see future updates. A move leaves the source null, so it matches nothing. The last owner's destruction unregisters the hooks.
Ref: test `CopyMoveAndDestructionReleaseHooks`.

**C16 ★★★ What does `matches(TopicId)` cost?**
A: [Inferred] `weak_ptr::lock()` (an atomic increment and decrement), the alive check, a bounds-checked `topics_[id-1]`, a binary search over filters, and a bit test. On Scan it runs per record, so the atomics are the surprising cost. You could hoist the lifetime check to once per batch.
Ref: `compiled.cpp:184-191`.

**C17 ★★ What misuse does `belongs_to` prevent?**
A: Using a subscription compiled for one engine or registry with another. Its partition and local IDs would point at unrelated topics and produce wrong matches. The engine throws `invalid_argument`.
Ref: `engine.cpp:150`.

**C18 ★★ Is `Subtree(itch/NEW)` wide? `Exact(itch)`?**
A: Neither. `Subtree(itch/NEW)` is exactly one partition with `all = true`. `Exact(itch)` matches only the topic `itch`. Only a Subtree with no `/` is wide.
Ref: test `WideTermsIncludeFuturePartitionsAndShallowExactStaysNarrow`.

**C19 ★★★ Why does member order in `CompiledState` matter?**
A: Members are initialized in declaration order, not initializer-list order. `matching(terms)` reads `terms`, which is declared earlier, so it's already filled. If the order were swapped, `matching` would be built from an empty vector, a silent bug flagged only by `-Wreorder`.
Ref: `compiled.cpp:119-130`.

**C20 ★★ What changed in P6, and why?**
A: Normalize went from all-pairs O(n²) to a hash set of subtree roots plus per-term ancestor checks. Matching went from scanning every term to set lookups per segment boundary, now O(depth) and shared by compile and hooks. The approved 100,000-partition T3 case timed out. Semantics were preserved: the old algorithm became the test's independent reference, checked on 512 random specs.
Ref: `results/p6/subscriptions-scaling.md`.

---

## D. Oracle

**D1 ★ What does `ScanOracle` model?**
A: Publication with dense sequences, a byte-capacity ring with DATA/PAD items and whole-item FIFO eviction, string-based subscription matching, and replay with a captured upper bound, budgets, checkpoints and the two expiry errors.
Ref: `04-oracle.md`.

**D2 ★★ What does it share with production, and how is that enforced?**
A: Only `types.hpp`. The `tiplog_ref` CMake target links only build flags, and exists only when `BUILD_TESTING` is on. Production `tiplog_sim` links only the driver.
Ref: `cmake/p2_ref.cmake:6-13`.

**D3 ★★ C = 64: publish payloads of 10, 4 and 8 bytes. Where's the PAD?**
A: Records need 32, 24 and 24 bytes (16-byte header plus payload, rounded to 8). The first two fill [0, 56). The third doesn't fit in the 8 bytes left, so a PAD covers [56, 64) and the record goes at 64. Head becomes 88, and seq 1 is evicted (tail 32).
Ref: test `V09HandComputedPadAndWrap`.

**D4 ★★ Why `max_record ≤ C/2`?**
A: A PAD is always smaller than the record that caused it, so pad + record < 2 × record ≤ C. The append therefore always fits in the ring.
Ref: ARCHITECTURE §5.3.

**D5 ★★ State the retention rule.**
A: An item is retained if and only if its start position ≥ head − C. Eviction is whole-item and FIFO, and a PAD is an item too.
Ref: `scan_oracle.cpp:67-70`.

**D6 ★★ Why use division and modulo instead of masks?**
A: Deliberately different arithmetic from production's masking and bit tricks. If both agree on every random case, a shared arithmetic bug is unlikely.
Ref: `scan_oracle.cpp:37-38` comment.

**D7 ★★ What is the captured upper bound?**
A: `upper_seq = head_seq − 1` and `upper_pos = head_pos` at open. The replay never delivers anything published later (invariant Q5), which gives a well-defined snapshot. A live tail chains snapshots.
Ref: test `CapturedUpperExcludesLaterPublicationAndCopiesPayload`.

**D8 ★★★ Why does evicting irrelevant records cause FellBehind?**
A: The check compares the unread *position* with the tail before touching memory. Scan can't know whether unread evicted records matched, and a precise rule would differ between Scan and Indexed. Uniform semantics let differential tests compare modes exactly, at the cost of failing some narrow, slow readers unnecessarily.
Ref: ARCHITECTURE §3.6; test `ConservativeExpiryIncludesIrrelevantRecords…`.

**D9 ★★★ Why return Done, not FellBehind, after an exact final budget plus eviction?**
A: The reader already received everything up to `upper_pos`. Completion (`next_pos == upper_pos`) is checked before expiry, so a budget ending exactly at the last record can't turn into a false failure.
Ref: test `ExactFinalBudgetIsDoneBeforeExpiryOnNextPositiveCall`.

**D10 ★★ What does `max = 0` do?**
A: Nothing: no progress, no expiry check, same status. It lets a driver tick for a paused reader without side effects.
Ref: `scan_oracle.cpp:135`.

**D11 ★★★ Why no look-ahead when the budget fills?**
A: Returning right after the last delivery keeps the checkpoint identical across modes. Scanning ahead through filtered records would advance progress differently in Scan and Indexed. Completion is established by the next positive call.
Ref: test `FullBudgetDoesNotLookAheadAcrossFilteredGap`.

**D12 ★★ Why does a zero-output completed snapshot advance the checkpoint?**
A: The reader examined the whole range. The next snapshot should start at `upper_seq`, not rescan from `last_delivered`. That's how Tail chains for quiet subscribers.
Ref: test `CompletedZeroOutputSnapshotAdvancesProgressAndChainsFromUpper`.

**D13 ★★ How is overflow avoided at open?**
A: `after_seq >= upper_seq` is checked first, so `after_seq + 1` is computed only when after < upper. `UINT64_MAX` can't wrap. A future start gives Done with no checkpoint.
Ref: `scan_oracle.cpp:115-121`.

**D14 ★★★ What bugs can't the oracle catch?**
A: Specification bugs (it implements the same contract), performance bugs, concurrency bugs, and anything it doesn't model, such as pool-pressure policies (covered later by a separate pressure fixture). The hand-computed V09 cases anchor the oracle itself.

**D15 ★★ HistoryExpired vs FellBehind?**
A: HistoryExpired comes at open: the requested start is already gone, and nothing is delivered. FellBehind comes mid-replay: unread data was overwritten, and the delivered prefix is still correct. Both report `requested_after`, `last_delivered` and `oldest_retained`.
Ref: `types.hpp:43-50`.

---

## E. Driver

**E1 ★ What's a tick? A budget?**
A: One tick follows each published record. The budget is how many records the consumer may read at that tick: 0 if paused or off-cadence, otherwise `batch_budget` or a jittered value in [1, B].
Ref: `trace_driver.cpp:55-72`.

**E2 ★★ Why resolve topic IDs through the trace dictionary?**
A: Trace IDs are sparse and not ordered; the test uses 7 and 900001. Indexing by position would silently publish to the wrong topics.
Ref: `driver_test.cpp:36, 45`.

**E3 ★★ Why check that sequences are dense?**
A: The engine contract is dense, global and starting at 1. A publisher that skips or repeats numbers would make ticks and replay checks meaningless, so the driver throws `logic_error`.
Ref: `trace_driver.cpp:37-40`.

**E4 ★★ Why two digests?**
A: One covers *what* was published (seq, path, payload); the other covers *how* the reader was scheduled. Changing only the seed changes the schedule digest but not the publication digest, which the test checks.
Ref: test `SeededBudgetsRepeat…`.

**E5 ★★★ Why not `uniform_int_distribution`? Isn't modulo biased?**
A: Engines like `mt19937_64` are fully specified by the standard; distributions aren't, so libstdc++ and libc++ can give different numbers from the same seed. Raw output modulo B is reproducible everywhere. The bias is at most about B/2⁶⁴, negligible, and the header disclaims uniform sampling.
Ref: `trace_driver.hpp:26-28`.

**E6 ★★ Why length-prefix fields before hashing?**
A: Without lengths, ("ab", "c") and ("a", "bc") would produce the same byte stream. Prefixing makes the encoding unambiguous.

**E7 ★★ FNV vs SHA-256?**
A: FNV-1a is a fast, dependency-free reproducibility check, but not collision-resistant. Data identity uses SHA-256 (P1's manifest and trace hashes).

**E8 ★★ Why `std::function`, and what does it cost?**
A: It keeps the driver engine-neutral and compiled once, and callers pass lambdas. The cost is an indirect call per publish and per tick, plus possible allocation when constructed. That's fine, because the driver isn't a timing harness. Alternatives: a template, a virtual interface, or `std::function_ref` (C++26).

---

## F. C++ language

**F1 ★★ What is heterogeneous lookup? What's required?**
A: Looking up a `std::string`-keyed container with a `string_view` without building a temporary string. For unordered containers in C++20, you need a hasher with `is_transparent` *and* a transparent equality such as `std::equal_to<>`.
Ref: `registry.hpp:112-116`.
Trap: only the hash being transparent isn't enough.

**F2 ★★ What does `bool operator==(const T&) const = default;` do? Why doesn't `Delivered` have one?**
A: It generates member-wise equality (C++20). `Delivered` holds a `span`, and comparing spans by identity would be misleading [Inferred].

**F3 ★★★ Why `static_assert(std::is_nothrow_move_constructible_v<Topic>)`?**
A: When a vector reallocates, it moves elements only if their move is `noexcept`, and copies them otherwise, to keep the strong guarantee. More importantly, the commit's `push_back(std::move(t))` must not throw. The assert makes that assumption a compile-time check.
Ref: `registry.cpp:17-18`.

**F4 ★★ Basic, strong and no-throw guarantees?**
A: Basic: no leaks, invariants hold, but state may change. Strong: commit or roll back. No-throw: never fails. `intern` gives strong, `ObserverHandle::reset` gives no-throw, and `compile` gives basic with respect to the registry.

**F5 ★★★ `Prepared::commit` calls `vector::insert`. Can that throw?**
A: In general, yes. But with capacity reserved and nothrow-movable elements, it doesn't allocate and the moves can't throw. `commit` is declared `noexcept`, so if an assumption were ever broken, `std::terminate` would run instead of leaving a half-applied update: fail loud, not corrupt.
Ref: `compiled.cpp:137-149`.

**F6 ★★ What does `weak_ptr::lock()` cost?**
A: A check of the control block plus an atomic compare-and-swap increment of the use count, then an atomic decrement when the temporary `shared_ptr` dies. That's tens of cycles uncontended, and more under contention [Inferred].

**F7 ★★ How are `shared_ptr` cycles avoided here?**
A: Only user-side subscription copies own `CompiledState` strongly. The registry's hub holds `weak_ptr` observers; handles hold `weak_ptr` to the hub; the lifetime token is weak in the subscription. No strong cycle exists.
Ref: the ownership graph in `03`.

**F8 ★★ What are node handles?**
A: C++17 `extract()` removes a node from an associative or unordered container without destroying it, and `insert(node)` relinks it into another container of the same type with no allocation. Here it lets nodes be allocated early and spliced in during the commit.
Ref: `registry.cpp:233-236`.

**F9 ★★ What lifetime pitfalls does `std::span` have here?**
A: Spans returned from `all_topics()`, `filters()` and `normalized_terms()` point into vectors that `intern` may reallocate. Holding one across an intern is a dangling view. The engine re-acquires per batch.

**F10 ★ What do `[[nodiscard]]` and `(void)` mean in the tests?**
A: `[[nodiscard]]` warns when a return value is ignored. In tests that intentionally ignore it, for example `(void)registry.intern(p)`, the cast documents the intent and silences the warning. The review fixed three such warnings in P2.

**F11 ★★ Why is `Term::Kind` unscoped but `Status` an `enum class`?**
A: `Kind` is nested in `Term`, so `Term::Exact` is already qualified and reads naturally. Top-level enums use `enum class` for scoping and no implicit int conversion. Both have explicit `uint8_t` storage.

**F12 ★★ Why `final` on `CompiledState`?**
A: Nothing should derive from it. It also lets the compiler devirtualize calls when the static type is known [Inferred].

**F13 ★★ Why do `TopicObserver` and `Update` have virtual destructors?**
A: They're deleted through base pointers (`unique_ptr<Update>`, `shared_ptr<TopicObserver>`); without a virtual destructor, that's undefined behaviour. (`shared_ptr` created by `make_shared` would actually get it right, but `unique_ptr<Base>` wouldn't.)

**F14 ★★ Rule of five for `ObserverHandle`?**
A: It defines the destructor, move constructor and move assignment, and deletes copy constructor and copy assignment, because it manages a unique resource (a registration).

**F15 ★★ What does `std::exchange` do here?**
A: It sets `other.serial_` to 0 and returns the old value in one expression, transferring ownership and marking the source empty.

**F16 ★★ What is `auto find_filter(auto& filters, …)`?**
A: A C++20 abbreviated function template: `auto` parameters make it a template, so it works for `vector<PartitionFilter>&` and `const vector<…>&` alike.

**F17 ★★ Why is `1 << 63` dangerous?**
A: `1` is an `int`, typically 32-bit. Shifting by at least its width is undefined behaviour. `std::uint64_t{1} << 63` is well-defined.

**F18 ★★ Does `string_view::substr` allocate? What is SSO?**
A: No; it returns a view. SSO (small-string optimization) stores short strings, up to 15 characters in libstdc++, inside the `std::string` object itself. That's why moving a short string moves its characters.

**F19 ★★★ Why not key `paths_` by `string_view` into `Topic::path` to avoid the duplicate string?**
A: `topics_` is a vector. On reallocation, each `std::string` moves, and for SSO strings the characters move with the object, so the views would dangle. You'd need stable storage, such as a `deque`, an arena, or offsets into one character buffer.

**F20 ★★ Are exceptions "zero-cost"?**
A: With table-based unwinding (Itanium ABI) there is no runtime cost on the non-throwing path, apart from some code-size and optimization effects. Throwing is expensive (microseconds). That's why they're used for rare registry failures and not in the replay loop.

---

## G. Complexity and performance (all [Inferred] unless noted; P2 has no benchmarks)

**G1 ★★ Complexity of `intern`?**
A: The fast path is one hash of the path, O(L). Creating k new topics from a d-segment path costs O(d·L) for prefix hashing, O(k) amortized appends, O(k·d) observer lookups, plus each affected observer's prepare.
F: *Hash worst case?* → O(n) per lookup with adversarial collisions.

**G2 ★★ Compile complexity before and after P6?**
A: Before: normalize O(n²·L), initial scan O(T·n·L). After: normalize O(n log n·L + n·d·L), initial scan O(T·d·L), plus filter inserts (O(F²) worst case for out-of-order first matches).
Ref: `03`.

**G3 ★★ Per-record matching cost: Scan vs Indexed?**
A: Scan calls `sub.matches(topic)` for every retained DATA record: a lifetime lock, a topic lookup, a binary search over F filters, and a bit test. Indexed calls `filter->matches(local_id)` only for candidates in selected partitions, with the filter pointer fetched once per batch per cursor, so it's just a bit test.
Ref: `engine.cpp:332, 361`.

**G4 ★★★ Memory per topic and per subscription?**
A: Per topic: about 56 bytes for `Topic`, a heap path if longer than 15 characters, and a second path copy in a hash node of about 56 bytes plus a bucket pointer. Per subscription: about 32 bytes per selected-partition filter, plus a word unless `all`, plus 2–3 copies of each term path in the sets. A 1,000-symbol TAPE subscription is tens of KB.

**G5 ★★★ How cache-friendly is the filter lookup?**
A: The filters are one contiguous vector, and binary search over thousands of 32-byte entries touches about log₂F cache lines. For ITCH, each filter's bits are one word, but on a separate heap allocation, so that's another line. A dense array, or inline small bitsets (e.g. a `uint64_t` stored in the filter for local IDs below 64), would cut a miss.

**G6 ★★ How would you measure the cost of `matches()`?**
A: A Google Benchmark microbenchmark on realistic topic-ID streams with filters of 1, 100 and 10k partitions, pinned to a P-core, with repetitions and confidence intervals as in the project's P5/P6 method. Compare against variants: lifetime hoisted, dense array. Hardware counters are denied on this machine, so use time plus simulated Cachegrind.
Ref: README/PROGRESS P0 (perf denied).

**G7 ★★★ When does observer de-duplication hurt?**
A: Many subscriptions hooked under the same ancestors, e.g. 1,000 `Subtree(itch)` readers. Each new topic finds all 1,000, and the linear de-duplication costs about 500k pointer comparisons per intern. At start of day, with 112k topics created, that adds up.

**G8 ★★ Is hash lookup O(1)?**
A: Average O(1) with a good hash. The worst case is O(n), with collisions or adversarial keys. The P6 doc explicitly says "hash-table lookup is not claimed worst-case constant."
Ref: subscriptions-scaling.md.

**G9 ★★ Why does the `all` short-circuit matter for performance?**
A: Whole-partition subscriptions (BOOK, REPLAY) never need bitset updates for new topics in that partition, and `matches` returns immediately. With 21 topics per ITCH partition that's minor for bits, but it removes all hook work for those partitions.

**G10 ★★ Dense array vs sorted vector for filters: numbers?**
A: With 100k partitions, a dense array is 3.2 MB per subscription versus about 32 B × selected partitions. For 1,000 subscriptions that's 3.2 GB versus a few MB. The dense array wins only for few subscriptions or few partitions.

---

## H. Correctness and edge cases

**H1 ★ Empty subscription?**
A: Rejected with `invalid_argument` by both `normalize` and the oracle. The product defines a non-empty union.
Ref: `compiled.cpp:89`.

**H2 ★★ What exactly does `Subtree(itch)` match?**
A: The topic `itch` itself, all current descendants, and all future descendants, including topics in partitions created later. It is wide (forces Scan), and every partition under `itch` gets `all = true`, including partition 0 (`itch` alone). It does not match `bnc/...`.

**H3 ★★ `Exact(itch)`?**
A: Only the topic `itch`. Not wide, no hook, and no descendants match.

**H4 ★★ The 65,536th topic in a partition, and the 65,537th?**
A: The 65,536th gets local ID 65,535 (the filter then has 1,024 words, last bit set). The 65,537th throws `RepresentationLimit`, and nothing is created, not even its missing ancestors.

**H5 ★★★ The registry is destroyed while a subscription exists?**
A: The destructor clears `alive_`. `matches` and `belongs_to` return false. Destroying the subscription later is safe because handles lock a dead `weak_ptr` hub and do nothing. ASan-tested.

**H6 ★★★ An observer's `prepare` throws during intern?**
A: The exception propagates from intern before any commit. Topics, partitions, the path map and every subscription's filters are unchanged, and the same intern succeeds once the bad observer is removed.

**H7 ★★ An invalid `TopicId` passed to `matches`?**
A: `registry->get(id)` throws `out_of_range` (0 or beyond the size), if the registry is alive. If it's dead, `matches` returns false first.

**H8 ★★ `open_replay(sub, UINT64_MAX)`?**
A: Done immediately, with no checkpoint and no error. `after_seq >= upper_seq` is tested before any `+1`.

**H9 ★★ A record matches both `Exact(a/b)` and `Subtree(a)`?**
A: Delivered once. Normalization drops the Exact anyway, and even unnormalized, the oracle's matcher returns on the first matching term.

**H10 ★★ Unicode or `%` in paths?**
A: Accepted as opaque bytes; only empty segments, slashes at the edges and NUL are rejected. P1's converter percent-encodes symbol characters outside `[A-Z0-9.]`, so ITCH paths are ASCII in practice.

---

## I. Testing

**I1 ★★ How do you know P2 is correct?**
A: Three layers:
1. Hand-computed golden tests for registry IDs and oracle retention.
2. Randomized comparisons against independent references inside the tests: a segment-splitting matcher on 128 seeds, and an all-pairs normalizer on 512 seeds.
3. Fault injection and limit tests for the all-or-nothing claims.

Everything passes in release and ASan/UBSan. Downstream, the oracle served as the reference for over 100M differential operations against the engine.

**I2 ★★ What reference do the topic tests use?**
A: `segments()` splits paths with `getline(…, '/')`, and `reference_match` compares segment vectors. `reference_normalize` is the old all-pairs algorithm on segments. Neither uses production helpers.
Ref: `topics_subs_test.cpp:23-79`.

**I3 ★★ How did you test the exception-safety claims?**
A: Reduced `Limits` force every exhaustion path. A `ThrowingObserver` injects `bad_alloc` during `prepare`. Each test compares counts, lookups and another subscription's bits before and after.

**I4 ★★ Why reduced `Limits`?**
A: To reach "IDs exhausted" with 3 topics instead of 4 billion. The code path is identical, only the threshold changes [Doc] V38.

**I5 ★★★ What's missing from P2's tests?**
A: Concurrency (out of scope), performance (no benchmarks), `bad_alloc` injected into the registry's own reserves (only the observer path is injected), O(F²) adversarial insertion, and observer storms. End-to-end engine correctness was P3+.

**I6 ★★ Why fixed seeds in random tests?**
A: Reproducibility: a failure prints its seed (`SCOPED_TRACE(seed)`) and reruns identically. Coverage comes from many seeds, not from randomness per run.

**I7 ★★ What does ASan add here?**
A: It turns silent use-after-free and out-of-bounds reads into immediate failures. That is essential for the lifetime tests, where release builds might "work" by luck. LeakSanitizer also checks that hooks and states are freed.

**I8 ★★ How do you run only the P2 tests?**
A: `ctest --preset release -R '^(topics\.subs|oracle|driver)\.'`, and the same with `--preset asan-ubsan`.

---

## J. Design trade-offs

**J1 ★★★ Why not a trie for matching?**
A: Matching is done on topic IDs and bitsets, not strings, so the hot path never walks a tree. A trie of terms could replace the hash-set normalizer, or serve a reverse "which subscriptions match this new topic?" index. That's worth it with millions of subscriptions sharing prefixes; it isn't needed for a handful of replays.

**J2 ★★ Why not regex or glob patterns?**
A: Arbitrary patterns can't be compiled into per-partition bitsets or a partition list for indexed replay, and their matching cost is unbounded. Exact and Subtree cover the consumers (ARCHITECTURE §2.3), and middle wildcards would be an explicit extension (K2).

**J3 ★★★ Why not an inverted index from topics to subscriptions?**
A: That suits *routing* live messages to many subscribers (fan-out). Here, replay asks the opposite question for one subscription: does this record match? A per-subscription filter answers that in O(1)–O(log F). An inverted index becomes valuable for live push delivery to thousands of subscribers.

**J4 ★★ Why not one cursor per term, plus de-duplication?**
A: More merge inputs (a BOOK has 3–4 terms per symbol) and a de-duplication step per record. One cursor per partition with a filter gives union semantics for free.
Ref: DD-09.

**J5 ★★★ Push hooks vs a pull epoch log?**
A: Push keeps filters always current, with O(depth) lookups per new topic, but needs callbacks, observer lifetimes and two-phase updates. Pull (each subscription catches up from a registry log of new topics at batch start) has no callbacks and batches naturally, so it is concurrency-friendly. For a single-threaded core, push is simple and immediate. For concurrency, I'd move to pull.

**J6 ★★ Exceptions vs `std::expected`?**
A: Exceptions are fine off the hot path, compose with constructors, and have zero cost when not thrown. `expected` makes failure explicit in signatures and works with `-fno-exceptions`, which many trading shops use. If the codebase banned exceptions, `intern` would return `expected<TopicId, RegistryError>` with the same transactional structure.

**J7 ★★ Why not `std::bitset`?**
A: Its size is a compile-time constant. Covering 65,536 local IDs means 8 KB per filter even when one bit is set, versus one word for ITCH with a lazy `vector<uint64_t>`.

**J8 ★★ Why u32 `PartitionId` when ITCH has 8,907 partitions?**
A: The approved T3 experiment uses 100,000 partitions, and other workloads (Binance, option chains) can exceed 65,535. `UINT32_MAX` is reserved as P4's free-owner sentinel.

---

## K. Scaling and extensions

**K1 ★★★★ Make the registry concurrent. What breaks first, and how would you fix it?**
A: Everything that assumes nothing interleaves:
- vector reallocation invalidating spans that other threads hold;
- `paths_` mutation during lookups;
- hooks registered after the initial scan, so topics created in between would be missed;
- filter updates racing with readers.

Options:
- **Sharded locks or a single writer thread for interning**, plus RCU or epoch-based reclamation: readers use an immutable snapshot (topics stored in stable chunked arrays, so IDs never move), and the writer publishes a new snapshot pointer atomically.
- **Subscriptions pull** new topics from an append-only log.
- **Register the hook before scanning**, then de-duplicate.

**K2 ★★★ Add middle wildcards like `itch/*/trade`.**
A: It's no longer a single subtree, so it spans all partitions, making it wide-like. Compile per partition: for each partition, match the pattern's remaining segments against its topics. The hook would need to fire on *every* new partition, so register on the wildcard's fixed prefix (`itch`). Indexed replay would merge every partition with matching topics, so Auto would usually pick Scan unless few partitions have a `trade` child.

**K3 ★★★ Add topic deletion.**
A: Generation-tag IDs (`{index, generation}`), as P4 does for blocks, so stale IDs are detectable. Return local IDs to a per-partition free list only once no retained record references them, which needs coordination with ring retention. Notify subscriptions to clear bits. Replays must not see a reused local ID for an old record, so deletion can only finalize after the ring evicts the topic's last record.

**K4 ★★★★ Support 1M subscriptions.**
A: The per-subscription cost becomes the problem: 1M sets of term copies, 1M filter vectors, and hooks storms on hot roots (the O(A²) de-duplication). Share structure: intern identical normalized specs to one shared `CompiledState`, since copies already share. Store filters in shared tables. Replace push hooks with pull. Move lifetime checks out of `matches`. For live delivery, an inverted index from topic to subscriptions matters more than per-subscription filters.

**K5 ★★★ Make it a distributed bus. What changes for IDs?**
A: Dense, creation-ordered IDs are process-local. On the wire, use paths or a stable global ID assigned by a central registry service and versioned, with a dictionary exchange, as trace v1 does. Partitions become the unit of sharding across servers.

**K6 ★★★ What must be persisted to restart?**
A: The path dictionary with IDs, or else the paths, re-interned in a deterministic order. Subscriptions are client state and are re-compiled. Ordering and sequence numbers come from the log itself (roadmap R1–R2: WAL segments and manifests). Never persist local IDs without the dictionary that defines them.

**K7 ★★ 10M topics?**
A: IDs fit in u32. Memory is the issue: about 150–200 bytes per topic plus paths, so 2 GB or more. Halve it by storing each path once (an arena with offsets) and using a more compact hash map, such as open addressing. Partitions and local IDs are unaffected.

**K8 ★★★ One hot symbol with a huge partition?**
A: Indexed replay on that partition visits all its records, and filtering by event type happens per candidate. If one event type dominates (e.g. `modify/delete`), a reader wanting only executions still visits all of them. Options: a finer partition depth for that symbol, per-family sub-indexes, or the P7 storage-layout split, which is exactly the article's "one large sibling" problem (A16).

**K9 ★★★ Add a "direct children only" term kind.**
A: Extend `Term::Kind`. In normalize, it's covered by a Subtree on itself or an ancestor, and it covers Exact children. In `Matching`, add a set checked against the parent prefix (path minus its last segment). It needs a hook on the root. It sets `all` only if the root is above the partition root. Then update the oracle matcher independently, add it to the random reference test, and add it to the value-type validators.

**K10 ★★★ Make Auto smarter using filter information.**
A: Auto currently uses partition count (`filters().size()`) and a density threshold, uncalibrated. Better: estimate the candidate fraction q from per-partition record counts in the index, and the selectivity within a partition from its bitset popcount relative to its topic mix. That's what P6's calibration is meant to inform. Don't claim a gain until it's measured.

---

## L. Domain

**L1 ★ What is ITCH?**
A: Nasdaq TotalView-ITCH 5.0, Nasdaq's full-depth feed. It's a binary stream of every order add, execution, cancel, delete and replace, plus trades, auction imbalances (NOII), halts and system events, each with a nanosecond timestamp and a stock "locate" code.
Ref: ARCHITECTURE §2.1.

**L2 ★★ Why does a BOOK consumer subscribe to `stock` and `_market` too?**
A: Rebuilding the order book needs adds and modifies, but also the stock directory and trading state (halts, from `stock`) and market-wide system events like start and end of messages (`_market`). It also needs data **from session start**, since orders added earlier are otherwise unknown.
Ref: ARCHITECTURE §2.3.

**L3 ★★ Why is a partition per symbol natural for traders?**
A: Most consumers reason per instrument: one stock's book, one stock's trades. Per-symbol partitions make an indexed catch-up for a basket of symbols touch only those symbols' messages.

**L4 ★★ What does TAPE subscribe to?**
A: `Exact(modify/executed)` (E), `Exact(modify/executed_px)` (C) and `Subtree(trade)` (P, Q, B). Executions live inside the `modify` family, so TAPE filters out X/D/U. That is why per-partition bitsets matter: the index selects the symbol, and the bitset drops cancels and deletes.

**L5 ★★ Why keep equal-valued events distinct?**
A: Two identical-looking executions are two real trades. Collapsing them would corrupt volume, VWAP and order-book state. De-duplication is by record identity (sequence number), never by payload.
Ref: S61 citation, ARCHITECTURE §3.7.

**L6 ★★ Why do slow readers matter in trading?**
A: A strategy or risk system that falls behind is acting on stale state. If it can't catch up fast, it "falls off the tip" and must recover from disk, which is much slower. The article's incident: a recovery that normally took under 2.5 s took over 13 minutes, because it read and filtered about 10× more data than it needed.
Ref: RESEARCH §1.1 A13.

---

## M. Behavioral and ownership

> Answer these **truthfully**. The guidance below is a structure, not a script; fill it with what you actually did.

**M1 ★★ "This was AI-assisted. What did you personally decide or verify?"**
Structure:
- Say plainly that implementation was agent-driven.
- Then name what you owned:
  - approving the plan version and scope (Tier B, defaults);
  - gating each phase on explicit evidence;
  - the independent-review requirement;
  - and now being able to explain and defend every design choice.
- Mention the process artifacts: phase gates, traceability ledgers, review findings.
- Offer to walk through any function on a whiteboard.

Trap: claiming you hand-wrote it, or being unable to explain a line.

**M2 ★★ What are you least proud of in P2?**
Pick something real and technical, e.g. the original O(n²) normalizer that only surfaced at 100k partitions, or that `compile` isn't fully transactional. Then say what you learned and how it was fixed or would be fixed.

**M3 ★★ What would you redo?**
The handle/ID ownership model instead of `weak_ptr` with a raw pointer (D11), and a pull-based topic log instead of push hooks (D10). Both simplify concurrency and the hot path.

**M4 ★★ Hardest bug?**
The retained lifetime anchor: subtle, because the `weak_ptr` check *looked* right. Explain the gap between "the token is alive" and "the owner is alive", and that it was caught by review and pinned by an ASan test.

**M5 ★★ How did you avoid overclaiming?**
Every claim is labeled measured or not. P2 makes no performance claims; uncalibrated Auto is labeled uncalibrated; Jane Street statements are kept separate from independent design; numbers come only from saved results.

**M6 ★★ Correctness vs speed: how did you prioritize?**
Correctness first: an independent oracle, exact semantics identical across modes, and explicit errors rather than silent loss. Then measure before optimizing. The P6 fix was driven by an actual failing case, not speculation.

