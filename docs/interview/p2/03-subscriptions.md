# 03 — Subscriptions (`src/tiplog/subs/compiled.hpp`, `compiled.cpp`)

## What it is for

A reader says *what* it wants as a list of terms. This module turns that list into a structure the engine can query **fast** and keeps it correct as new topics appear. It is used by both replay modes:

- **Scan** asks "does record *r*'s topic match?" once for every record in the ring.
- **Indexed** asks "which partitions do I open cursors on?" once, then "does this topic's local ID match?" for each candidate record.

## Semantics, from first principles [Doc] ARCHITECTURE §3.2–3.3

- `Exact(t)` matches topic `t` only.
- `Subtree(p)` matches `p` and every topic whose path extends `p` **at a segment boundary**. So `Subtree(itch/AAPL)` matches `itch/AAPL/add/anon` but **not** `itch/AAPLX/...`. A naive `starts_with` would get this wrong.
- A subscription is a **union** of terms, and each matching message is delivered **at most once per subscription**, however many terms match it.
- Subtree terms automatically include topics **created after** the subscription.
- **Wide terms** are Subtree terms rooted shallower than two segments, e.g. `Subtree(itch)`. They span partitions that don't exist yet, and they are served by Scan.

## Public API [Code] `compiled.hpp`

```cpp
struct PartitionFilter {
  PartitionId partition{};
  bool all{};                          // every topic in this partition matches
  std::vector<std::uint64_t> bits;     // else: bit i set ⇔ local_id i matches
  bool matches(std::uint16_t local_id) const noexcept;
};
class CompiledSubscription {
  bool wide() const noexcept;
  bool matches(TopicId) const;
  bool belongs_to(const topics::Registry&) const noexcept;
  std::span<const Term> normalized_terms() const noexcept;
  std::span<const PartitionFilter> filters() const noexcept;  // sorted by partition
  const PartitionFilter* partition_filter(PartitionId) const noexcept;
 private:
  std::shared_ptr<detail::CompiledState> state_;
};
SubscriptionSpec normalize(const SubscriptionSpec&);
CompiledSubscription compile(topics::Registry&, const SubscriptionSpec&);
```

- The class is just a `shared_ptr` to hidden state. This is the **pimpl** idea: the header exposes no internals, and copies are cheap and **share** state.
- `filters()` comments that "Views may invalidate on registry.intern()". The engine respects this by re-acquiring filter pointers each batch (`engine.cpp:299-314`).

## Worked example (traced by hand through the code)

Registry already contains `itch/AAPL/add/anon`, so IDs 1–4 exist (see `02`). Now compile:

```
{ Subtree(itch/AAPL/add), Exact(itch/AAPL/trade/cross),
  Subtree(itch/AAPL/add/anon), Exact(itch/AAPL/add/anon) }
```

**1. `normalize`**

- Sorted by (path, kind), with Exact before Subtree on the same path:
  ```
  Subtree itch/AAPL/add
  Exact   itch/AAPL/add/anon
  Subtree itch/AAPL/add/anon
  Exact   itch/AAPL/trade/cross
  ```
- The set of subtree roots is `{itch/AAPL/add, itch/AAPL/add/anon}`.
- Coverage check for each term:
  - `Subtree itch/AAPL/add`: the proper prefixes `itch` and `itch/AAPL` are not in the set → **keep**.
  - `Exact itch/AAPL/add/anon`: the path itself is in the set → covered → **drop**.
  - `Subtree itch/AAPL/add/anon`: the proper prefix `itch/AAPL/add` is in the set → **drop**.
  - `Exact itch/AAPL/trade/cross`: none of `itch`, `itch/AAPL`, `itch/AAPL/trade`, or the path itself is in the set → **keep**.
- Result: `[Subtree(itch/AAPL/add), Exact(itch/AAPL/trade/cross)]`.

**2. Intern the roots**

- `itch/AAPL/add` already exists as ID 3.
- `itch/AAPL/trade/cross` creates ID 5 `itch/AAPL/trade` (partition 1, local 3) and ID 6 `itch/AAPL/trade/cross` (partition 1, local 4).

**3. Build the filters.** Scan all topics against the matching sets:
- ID 3 (local 1) matches through subtree self.
- ID 4 (local 2) matches through prefix `itch/AAPL/add`.
- ID 6 (local 4) matches exactly.

So partition 1's filter has `all = false` and `bits[0] = 0b10110 = 0x16`.

**4. Hooks.** One hook, on root ID 3. The Exact term needs none.

**5. Later: `intern("itch/AAPL/add/attributed")`** creates ID 7, local 5.
- The registry walks up from 7 to 3, finds the hook, and calls `prepare`.
- 7 matches through prefix `itch/AAPL/add`. Partition 1's filter exists and isn't `all`, so a modified copy with bit 5 set is staged: `0x36`.
- The commit swaps the bits in.
- Now `sub.matches(7)` is true.

## Annotated code

### Path-set helpers (added in P6)

```cpp
struct PathHash { using is_transparent = void;
  std::size_t operator()(std::string_view path) const noexcept { return std::hash<std::string_view>{}(path); } };
using Paths = std::unordered_set<std::string, PathHash, std::equal_to<>>;
```
[Code] `compiled.cpp:13-19`. A set of owned strings that can be searched with a `string_view` without allocating (transparent lookup, as in the registry).

```cpp
bool has_subtree_prefix(const Paths& roots, std::string_view path, bool include_self = true) {
  if (include_self && roots.contains(path)) return true;
  for (auto end = path.find('/'); end != npos; end = path.find('/', end + 1))
    if (roots.contains(path.substr(0, end))) return true;
  return false;
}
```
[Code] `compiled.cpp:21-29`

- Asks: "is this path, or any ancestor ending at a `/`, in the set?"
- It only checks prefixes that end **right before a slash**. So for `itch/AAPLX/add` it checks `itch` and `itch/AAPLX`, never `itch/AAPL`. That is how segment boundaries are enforced, with no character-by-character special case.
- `include_self = false` is for Subtree terms in `normalize`: a subtree must not count as covered **by itself**.
- `path.substr` on a `string_view` returns another view, so there is **no allocation** per prefix. The comment at lines 31–34 says this.

### `Matching`: the compiled membership test

```cpp
struct Matching {
  Paths exact, subtree, whole_partition;
  explicit Matching(std::span<const Term> terms) { ... }
  bool matches(std::string_view path) const {
    return exact.contains(path) || has_subtree_prefix(subtree, path);
  }
  bool covers_partition(std::string_view path) const {
    return has_subtree_prefix(whole_partition, path);
  }
};
```
[Code] `compiled.cpp:35-62`

- `exact` holds every Exact term's path. `subtree` holds every Subtree root.
- `whole_partition` holds Subtree roots with **fewer than 2 slashes**, i.e. at depth 1 or 2. Such a root is the partition root itself (`itch/AAPL`) or above it (`itch`), so it covers **every** topic in any partition beneath it. That lets the filter set `all = true`.
- **Cost of `matches(path)`.** One lookup for the exact set, plus one per `/` in the path. Path depth is at most 4 for ITCH, so this is constant work **regardless of how many terms the subscription has**. That is the point of the P6 repair.
- The comment at lines 31–32 explains why it **owns** strings instead of holding views into `terms`: the lookup sets then don't depend on the `terms` vector never being moved. The cost is that each path is stored two or three times [Inferred].

### Filter helpers

```cpp
auto find_filter(auto& filters, PartitionId partition) {
  return std::lower_bound(filters.begin(), filters.end(), partition,
      [](const PartitionFilter& f, PartitionId id) { return f.partition < id; });
}
```
[Code] `compiled.cpp:63-68`

- A binary search over the sorted vector, O(log F).
- The `auto&` parameter is C++20 abbreviated-template syntax, so one helper serves both `const` and non-const vectors.

```cpp
void include(PartitionFilter& filter, const topics::Topic& topic, bool all) {
  if (filter.all) return;                       // already everything
  if (all) { filter.all = true; filter.bits.clear(); return; }
  const auto word = topic.local_id / 64;
  if (filter.bits.size() <= word) filter.bits.resize(word + 1, 0);
  filter.bits[word] |= std::uint64_t{1} << (topic.local_id % 64);
}
```
[Code] `compiled.cpp:69-79`

- **Lazy growth.** The bitset is only as long as the highest selected local ID needs. For ITCH (≤ 21 topics per partition) that is a single word.
- `std::uint64_t{1} << n` and not `1 << n`: a plain `1` is an `int`, and shifting it by 32 or more is undefined behaviour.

```cpp
bool PartitionFilter::matches(std::uint16_t local_id) const noexcept {
  const auto word = local_id / 64;
  return all || (word < bits.size() && (bits[word] & (std::uint64_t{1} << (local_id % 64))) != 0);
}
```
[Code] `compiled.cpp:82-86`

- The bounds check `word < bits.size()` is needed because bits are grown lazily. A higher local ID than any selected one is simply "not set".
- This is the function on the **Indexed hot path** (`engine.cpp:332`).

### `normalize()`

[Code] `compiled.cpp:88-116`

```cpp
if (spec.terms.empty()) throw std::invalid_argument(...);     // product rule: non-empty union
SubscriptionSpec result = spec;                                 // work on a copy
for (term : result.terms) { Registry::validate_path(term.path); check kind is Exact or Subtree; }
std::sort(by path, then kind);
result.terms.erase(std::unique(...), end);                      // drop identical duplicates
Paths subtrees = { every Subtree path };
retained = terms where !has_subtree_prefix(subtrees, path, /*include_self=*/ kind == Exact);
```

- **Rules** [Doc] ARCHITECTURE §3.3:
  - drop `Exact(t)` if some `Subtree(p)` has *p* ⊑ *t* (p is t or an ancestor of t);
  - drop `Subtree(q)` if some `Subtree(p)` has *p* ⊏ *q* (a strict ancestor).
- **Validate everything first.** `compile` calls `normalize` before interning anything, so a bad 5th term can't leave the first four interned. Test: `V07Subscriptions.InvalidSpecsDoNotRegisterEarlierValidTerms` checks `topic_count() == 0` after each rejected spec.
- **Why sort?** `std::unique` only removes *adjacent* duplicates, and a fixed order makes the output deterministic. Equal inputs in any order produce identical normalized terms, which matters for reproducible experiments and for `normalize(normalize(x)) == normalize(x)` (idempotence, tested).
- **Same path, both kinds.** `{Exact(a0/b), Subtree(a0/b)}` normalizes to `{Subtree(a0/b)}`, because the subtree includes its root. Two identical `Subtree(a0/b)` terms are already merged by `unique`.

#### The lexical-interleaving trap (why "remember the last subtree" fails)

Sorted string order is **not** tree order. The `-` character (0x2D) sorts *before* `/` (0x2F), so:

```
a          ← Subtree
a-foo      ← Subtree   (not under a!)
a-foo/child
a/b        ← under a, but separated from it by a-foo
a/b/child
a0/b
```

A tempting O(n) sweep keeps only "the last uncovered subtree root" and checks whether each later term starts with it. Here it would make `a-foo` the current root and then fail to see that `a/b` is covered by `a`.

The current code sidesteps ordering entirely: each term checks **all of its own ancestors** against a hash set. Test: `V07Subscriptions.NormalizationHandlesLexicalInterleavingAndSamePathKinds` expects exactly `{Subtree a, Subtree a-foo, Subtree a0/b, Exact a0/bc}` ([Doc] `results/p6/subscriptions-scaling.md`).

#### Original (P2) vs current (P6) normalize and compile

The P2 version (commit `d4e5b83`, see `scripts/git.sh diff d4e5b83 -- src/tiplog/subs/compiled.cpp`):

```cpp
bool prefix_at_boundary(std::string_view root, std::string_view path) {
  return path == root || (path.size() > root.size() && path.starts_with(root) && path[root.size()] == '/');
}
bool matches_any(std::span<const Term> terms, std::string_view path) {
  return std::any_of(terms..., [path](const Term& t) { return term_matches(t, path); });
}
// normalize: for every term, any_of over every other term  → O(n²)
// compile:   for every topic in the registry, matches_any over every term → O(T·n)
```

| | P2 original | P6 current |
|---|---|---|
| Correct? | Yes (it was also tested against the reference) | Yes, and checked against an independent all-pairs reference on 512 random specs |
| normalize | O(n²·L) pairwise | O(n log n·L) sort + O(n·d) set lookups |
| compile scan | O(T·n·L): every topic × every term | O(T·d·L): every topic × its own depth |
| Hook prepare | O(k·n) per new-topic batch | O(k·d) |
| What broke | The required **100,000-partition** T3 functional case timed out in the P6 Python integration run ([Doc]). The regression test models it with 100k terms over 200k topics, which comes to roughly 10¹⁰ term-checks under the old code [Inferred] | The new test `HundredThousandTermsCompileAndObserveWithoutTimingAssumptions` passes; no timing threshold is asserted |

(n = terms, T = topics, d = path depth, L = path length, k = new topics.)

[Doc] subscriptions-scaling.md: "Lookup count now depends on path depth rather than the number of subscription terms… hash-table lookup is not claimed worst-case constant."

**Interview story angle.** The original was simple and correct and passed every P2 test. The bottleneck only appeared when a later, already-approved experiment scaled one parameter by 1000×. Semantics were kept identical: the old all-pairs algorithm was **preserved inside the test** as the independent reference (`topics_subs_test.cpp:45-69`).

### `CompiledState`: the hidden state, which is also the observer

```cpp
struct CompiledState final : topics::TopicObserver {
  topics::Registry* registry;
  std::weak_ptr<const topics::Registry::Lifetime> identity;
  std::vector<Term> terms;
  const Matching matching;
  std::vector<PartitionFilter> filters;      // sorted by partition
  std::vector<topics::ObserverHandle> hooks;
  bool wide{};
  CompiledState(Registry& source, std::vector<Term> normalized)
      : registry(&source), identity(source.identity()), terms(std::move(normalized)), matching(terms) {}
```
[Code] `compiled.cpp:119-130`

- **Member order matters.** `matching(terms)` reads the `terms` member. C++ initializes members in **declaration order**, not initializer-list order, and `terms` is declared before `matching`, so it's already filled. Swapping the two declarations would build `matching` from an empty vector, a silent bug that compilers only warn about with `-Wreorder` [Inferred; classic interview question].
- **`final`** stops further derivation, which also lets the compiler devirtualize calls when it knows the exact type [Inferred].
- **Raw `Registry*` plus the `identity` check.** See `02` for the lifetime design. The raw pointer is never dereferenced unless `identity.lock()` succeeds and `alive()` is true.
- `hooks` are destroyed with the state, so each handle unregisters itself (RAII).

### Two-phase update for topics created later

```cpp
struct Prepared final : Update {
  CompiledState& state;
  std::vector<PartitionFilter> changed;   // modified copies of existing filters
  std::vector<PartitionFilter> added;     // filters for partitions not yet in `filters`
  void commit() noexcept override {
    for (auto& f : changed) { auto d = find_filter(state.filters, f.partition); d->all = f.all; d->bits.swap(f.bits); }
    for (auto& f : added)   { auto d = find_filter(state.filters, f.partition); state.filters.insert(d, std::move(f)); }
  }
};
```
[Code] `compiled.cpp:132-150`

```cpp
std::unique_ptr<Update> prepare(std::span<const Topic> pending) override {
  auto update = std::make_unique<Prepared>(*this);
  for (topic : pending) {
    if (!matching.matches(topic.path)) continue;
    current = find_filter(filters, topic.partition);
    exists = current is that partition;
    if (exists && current->all) continue;                    // nothing to do; `all` already covers it
    staged = exists ? update->changed : update->added;
    find-or-insert a staged filter (copy of current, or a fresh empty one);
    include(*staged_filter, topic, matching.covers_partition(topic.path));
  }
  reserve capacity in `filters` for the added ones (geometric growth);
  return update;
}
```
[Code] `compiled.cpp:152-173`

- **prepare** does everything that can allocate: copying bit vectors, growing them, inserting into the staged vectors, and reserving `filters` capacity.
- **commit** only swaps vectors (`noexcept`), assigns a `bool`, and inserts into a vector whose capacity is already reserved, moving `PartitionFilter`s with nothrow moves. The `static_assert`s at lines 11–12 guarantee those moves are nothrow.
- **Why copy and then swap** instead of editing in place? If a *later* observer's prepare throws, this subscription's filters must still be untouched (test `ObserverAllocationFailurePrecedesAllRegistrationCommit`).
- **The `all` short-circuit.** For `Subtree(itch/AAPL)`, every new AAPL topic finds `exists && all` and is skipped. A fully covered partition never needs updating again.
- Reserving `filters` during prepare **changes capacity, not content**. If the intern later fails, the subscription simply has spare capacity, which is harmless. It *does* invalidate existing spans from `filters()`, which is why the documented "views may invalidate on intern" rule exists.

### Query functions

```cpp
bool CompiledSubscription::wide() const noexcept { return state_ && state_->wide; }
bool CompiledSubscription::belongs_to(const Registry& r) const noexcept {
  // both identities lock, both alive, and same Lifetime object
}
bool CompiledSubscription::matches(TopicId id) const {
  if (!state_) return false;                                     // default-constructed or moved-from
  const auto lifetime = state_->identity.lock();
  if (!lifetime || !lifetime->alive()) return false;             // registry destroyed
  const auto& topic = state_->registry->get(id);                 // throws on invalid id
  const auto* filter = partition_filter(topic.partition);        // binary search
  return filter && filter->matches(topic.local_id);              // bit test
}
```
[Code] `compiled.cpp:177-202`

- **`belongs_to`** guards against a subtle misuse: a subscription compiled on engine A then used on engine B. Its local IDs and partition IDs would refer to the wrong registry and give nonsense matches. The engine refuses (`engine.cpp:150`). Test: `CopyMoveAndDestructionReleaseHooks` checks `copy.belongs_to(other) == false`.
- **`matches` is on the Scan hot path** (once per retained DATA record, `engine.cpp:361`). Its cost [Inferred, not measured]:
  - `weak_ptr::lock()` is an atomic increment plus an atomic decrement on the control block, because it creates and destroys a temporary `shared_ptr`;
  - a bounds-checked vector index;
  - an O(log F) binary search;
  - a bit test.

  The atomics are the surprising part. An optimization would be to check lifetime once per batch instead of once per record. This is a good "what would you optimize" answer, with the caveat that it hasn't been profiled.

### `compile()`

[Code] `compiled.cpp:204-232`

```cpp
auto normalized = normalize(spec);                                    // 1. validate + canonicalize
for (term : normalized.terms) roots.push_back(registry.intern(term.path));   // 2. intern every root
auto state = std::make_shared<CompiledState>(registry, std::move(normalized.terms));
for (term : state->terms) if (Subtree && no '/' in path) state->wide = true; // 3. depth-1 subtree ⇒ wide
for (topic : registry.all_topics()) {                                 // 4. initial filters
  if (!matching.matches(topic.path)) continue;
  find-or-insert the partition's filter (sorted position);
  include(*filter, topic, matching.covers_partition(topic.path));
}
for (i) if (terms[i] is Subtree) hooks.push_back(registry.observe(roots[i], state));  // 5. hooks
return CompiledSubscription{std::move(state)};
```

1. **Why intern every root, including Exact topics never published?**
   - A **Subtree** root needs a `TopicId` to hang the hook on, because the hub is keyed by ID.
   - An **Exact** topic, once interned, has a local ID **now**, so its bit can be set immediately. Because a topic is created only once, no *future* topic can ever equal an existing Exact path, so Exact terms need **no hook**. Test: `V08Subscriptions.ExactPreinternedAndNoHookNeeded` checks `observer_count() == 0`.
   - **Side effect** [Inferred]: subscribing creates permanent topics (and possibly partitions) in the registry. A typo'd subscription creates a junk topic forever, and a hostile client could use up a partition's local IDs. Production systems often keep "pending exact" paths outside the registry instead.
   - This interning also notifies *other* subscriptions. If someone holds `Subtree(itch)`, compiling `Exact(itch/NEW/x)` creates `itch/NEW`, which flows into the wide subscription through its hook, as it should.
2. **Is `compile` atomic?** [Inferred]
   - Malformed specs have no effect (step 1 validates first).
   - Each `intern` is individually all-or-nothing.
   - But if the *third* root's intern hits a `RepresentationLimit`, the first two roots **stay interned**. The registry stays consistent, and those topics simply have no messages. So `compile` gives the **basic** guarantee with respect to registry contents, not the strong one. Be ready to say this precisely.
3. **Wide detection.** Only `Subtree` with zero slashes, e.g. `Subtree(itch)`. `Exact(itch)` is not wide; it matches just the topic `itch` (test `WideTermsIncludeFuturePartitionsAndShallowExactStaysNarrow`). `Subtree(itch/NEW)` at depth 2 is **not** wide either: it is exactly one partition with `all = true` (same test, lines 310–313).
4. **Why sorted insertion?** Filters stay ordered by partition ID, which gives binary search and a deterministic cursor order for the indexed merge.
   - **Hidden cost** [Inferred]: topics are visited in **topic-ID order**, and the first matching topic of each partition triggers a `vector::insert` at its sorted position. Insert is O(F) element moves. If partitions are first matched in a scrambled order, building F filters costs O(F²) moves.
   - The 100k test creates partitions in order, so every insert is an append and this never shows.
   - **Fix:** collect filters unsorted, then sort once at the end, which is O(F log F).
5. **Hooks after the initial scan.** That order is safe because the core is single-threaded: no topic can be created between the scan and the hook registration. A concurrent design would need the hook registered *before* scanning, plus de-duplication.

## Ownership graph

```
CompiledSubscription ──shared_ptr──► CompiledState  (is-a TopicObserver)
CompiledSubscription (copy) ─────────┘     │
Engine Replay::sub_ (copy) ──────────┘     ├── terms, matching, filters
                                           └── hooks: vector<ObserverHandle>
                                                       │ weak_ptr
                                                       ▼
Registry ──shared_ptr──► ObserverHub { roots: TopicId → [Slot{serial, weak_ptr<TopicObserver>}] }
                                                       │ weak_ptr (back to CompiledState)
Registry ──shared_ptr──► Lifetime{alive}  ◄──weak_ptr── CompiledState::identity
CompiledState ──raw Registry*──► Registry   (dereferenced only if identity alive)
```

- **There are no `shared_ptr` cycles.** The only strong owners of `CompiledState` are user-side copies of the subscription, including the engine's `Replay`/`Tail` objects (`engine.hpp:104`, `engine.hpp:142`).
- **When the last copy dies**, `CompiledState` is destroyed, its `hooks` are destroyed, and each handle erases its slot. Tested: `observer_count()` returns to 0.
- **Copies share state**, so all copies see filter updates from new topics. A moved-from subscription has a null state, so `matches()` returns false (`topics_subs_test.cpp:333`).

## Union and duplicates [Doc] DD-09

A record belongs to exactly one partition. That partition has exactly one filter in a subscription, and one bit (or `all`) decides the match. **Overlapping terms can't cause a duplicate delivery**, because there is nothing to de-duplicate.

The rejected alternative was one cursor *per term*, followed by de-duplication of the merged output ([Doc] ARCHITECTURE §11). That costs a merge input per term, plus a "seen" check per record.

The oracle checks the other side of this: **equal-valued but distinct events** must all be delivered (`OracleReplay.EqualValuedDistinctSequenceEventsSurviveUnion`). De-duplication is by *record*, never by payload ([Doc] ARCHITECTURE §3.7, citing Jane Street's Flex-model article S61).

## Memory per subscription [Inferred, rough]

- **Per selected partition:** one `PartitionFilter` (4 B partition + 1 B flag + 24 B vector, about 32 B) plus one 8-byte bitset word unless `all` is set.
- **Per term:** the path is stored in `terms` and again in a `Matching` set (three times for depth ≤ 2 subtrees), plus hash-node overhead.
- **Example:** a REPLAY subscription on all 8,907 ITCH partitions holds about 9k filters, roughly 300 KB, and is wide, so it uses Scan anyway. A TAPE subscription on 1,000 symbols has about 3,000 terms and 1,000 filters, tens of KB.
- **Alternative:** a dense `vector<Filter>` indexed by `PartitionId` gives O(1) lookup but costs O(all partitions) per subscription: 100k partitions × 32 B = 3.2 MB **each**.

## Ten questions to make sure you can answer

1. Show that `Subtree(itch/AA)` doesn't match `itch/AAPL/add`. Which line enforces it?
2. Normalize `{Exact a, Subtree a, Subtree a/b, Exact a-foo/x, Subtree a-foo}` and justify every drop.
3. Why does a lexical sweep fail? Give the counterexample.
4. Why do Exact terms need no hook? What would break if Exact topics weren't interned at compile time?
5. What does `all = true` buy you, besides compactness?
6. Why is the filter container a sorted vector? What's its worst case?
7. Walk through `prepare`/`commit` when a new topic matches a partition that has no filter yet.
8. Is `compile` strongly exception-safe? Precisely what can remain changed after a throw?
9. Why does `matches()` check lifetime? What does it cost on the hot path?
10. Why does `wide` force Scan? What would Indexed replay do with a wide subscription?
