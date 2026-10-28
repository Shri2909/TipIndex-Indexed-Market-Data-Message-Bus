# 02 — Topic registry (`src/tiplog/topics/registry.hpp`, `registry.cpp`)

## What it is for

The registry is the system's **phone book for topic names**. Given a path string, it returns a stable integer ID and records:

- the topic's **parent** (so the tree can be walked upward);
- its **depth**;
- its **partition**, i.e. which stock it belongs to;
- its **local ID** inside that partition.

Every later component works with these integers, not strings. [Doc] ARCHITECTURE §5.1: "Interning creates missing ancestors. The partition of a topic is its ancestor at depth min(2, depth). `local_id` is dense per partition (u16) and drives per-partition filter bitsets."

## Data model

```cpp
struct Topic {
  TopicId id{};
  std::string path;
  TopicId parent{};  // Zero is the absence of a parent, never a topic ID.
  std::uint32_t depth{};
  PartitionId partition{};
  std::uint16_t local_id{};
};
struct Partition {
  PartitionId id{};
  TopicId root{};            // the depth-1 or depth-2 topic that defines it
  std::uint32_t topic_count{};
};
struct Limits {
  std::uint64_t max_topics{UINT32_MAX};
  std::uint64_t max_partitions{UINT32_MAX};   // UINT32_MAX itself reserved for P4
  std::uint32_t max_local_topics{65536};
};
```
[Code] `registry.hpp:20-40`

**Storage** [Code] `registry.hpp:116-122`:

| Member | Type | Holds |
|---|---|---|
| `topics_` | `vector<Topic>` | All topics. `TopicId` *k* lives at index *k − 1* |
| `partitions_` | `vector<Partition>` | All partitions. `PartitionId` *p* lives at index *p* |
| `paths_` | `unordered_map<string, TopicId>` with transparent hash | Path → ID lookup |
| `observers_` | `shared_ptr<ObserverHub>` | Watched roots → observer slots (subscriptions) |
| `lifetime_` | `shared_ptr<Lifetime>` | "Is this registry still alive?" flag, for subscriptions |

### The ID scheme

- **Topic IDs start at 1. Zero means "no parent".** [Code] `registry.hpp:23`, `registry.cpp:85`. A sentinel of 0 is cheaper and clearer than `std::optional<TopicId>` in every `Topic`, and it lets the ancestor walk end with `while (ancestor != 0)` (`registry.cpp:206`).
- **Topic IDs are dense**, so lookup by ID is an array index: `topics_[id - 1]`, which is O(1) and cache-friendly. The alternative, a hash map from ID to Topic, costs a hash on every lookup, and the engine's Scan path calls `registry.get(item.topic)` for every record (via `CompiledSubscription::matches`).
- **Partition IDs start at 0 and are dense.** The `Limits` default `max_partitions = UINT32_MAX` means the largest ID ever assigned is `UINT32_MAX − 1`, because `partition_id = count − 1` (`registry.cpp:165`). So `UINT32_MAX` can safely mean "no owner" in P4's block pool (`index::none`, `index.hpp:14`). [Doc] topics-sources.md: "partition UINT32_MAX reserved".
- **Local IDs are dense per partition, from 0 to 65,535** (`uint16_t`). The partition's root topic gets 0. [Doc] ARCHITECTURE §5.1.

### Why local IDs at all? [Doc + Inferred]

A subscription filter is a **bitset per partition**. With global topic IDs, a bitset for stock AAPL would need one bit per topic in the whole system, up to 112k bits, almost all zero. Local IDs number the topics *within* a partition, so AAPL's bitset needs only as many bits as AAPL has topics. P1 measured ITCH partition trees of **4–21 nodes** ([Doc] PROGRESS P1), so a whole stock's selection fits in **one 64-bit word**.

### Why `uint16_t` for local IDs? [Inferred, partly Doc]

- `uint8_t` (256) would fit ITCH's 21 nodes per partition, but would be fragile for other hierarchies.
- `uint32_t` would allow absurd bitset sizes and wastes space in the `Topic` struct.
- 65,536 topics per partition is a generous ceiling. The registry enforces it explicitly instead of silently wrapping ([Doc] VALIDATION V38: "local-topic-id exhaustion; reject limits without mutation"). The test `V38Registry.FullUint16BoundaryAndLateBitsetGrowth` actually creates local ID 65,535 and checks that bit 63 of word 1023 is set.

### Why partition = depth min(2, depth)? [Doc]

- Jane Street's Aria uses one index per **topic partition**, meaning all topics sharing the same two-segment prefix (RESEARCH §1.1, A6). A per-topic index was untenable at nearly a million topics.
- In this hierarchy, two segments means `itch/<SYMBOL>`: one partition per stock, plus `itch/_market`.
- A **depth-1** topic such as `itch` becomes its own tiny partition containing only itself ([Doc] ARCHITECTURE §2.1: "Topics with fewer than two segments form their own partition"). In the test, `itch` is partition 0 with `topic_count` 1 (`topics_subs_test.cpp:99-100`).

## Worked example (verified against `V06Registry.AncestorsPartitionsAndDenseLocalIds`)

Start from an empty registry.

**Call 1: `intern("itch/AAPL/add/anon")` returns 4.** The loop visits each prefix:

| Prefix | Exists? | New ID | Depth | Partition | Local ID |
|---|---|---|---|---|---|
| `itch` | no | 1 | 1 | **new 0** (depth ≤ 2) | 0 |
| `itch/AAPL` | no | 2 | 2 | **new 1** (depth ≤ 2) | 0 |
| `itch/AAPL/add` | no | 3 | 3 | inherits 1 from parent 2 | 1 |
| `itch/AAPL/add/anon` | no | 4 | 4 | inherits 1 | 2 |

After the commit, partition 0 = {root 1, count 1} and partition 1 = {root 2, count 3}.

**Call 2: `intern("itch/MSFT")` returns 5.** `itch` exists. `itch/MSFT` is new at depth 2, so it gets **new partition 2** and local ID 0.

**Call 3: `intern("itch/AAPL/add/anon")` again returns 4.** This is the fast path: one hash lookup at `registry.cpp:127`, with no allocation.

**Call 4: `intern("itch/_market/system_event")`.** This creates `itch/_market` (ID 6, **partition 3**, local 0) and `itch/_market/system_event` (ID 7, partition 3, local 1).

Call 4 is my own extension. The real test skips it and instead runs `intern("bnc")`, which returns 6 with partition 3, then `intern("bnc/BTC/trade")`, which returns 8 with partition 4 and local ID 1 (`topics_subs_test.cpp:108-112`). Same rules, different sequence.

## Annotated code

### Helpers

```cpp
template <class T>
void reserve_growth(std::vector<T>& values, std::size_t needed) {
  if (needed > values.capacity()) {
    const auto available = values.max_size() - values.capacity();
    const auto increment = std::min(available, values.capacity() / 2 + 1);
    values.reserve(std::max(needed, values.capacity() + increment));
  }
}
```
[Code] `registry.cpp:9-16`

- **Purpose.** Make sure capacity exists *before* the commit, so the commit's `push_back` cannot allocate and therefore cannot throw.
- **Why not just `reserve(size + pending.size())`?** That was the original code, and it was **a bug found in review**. `std::vector::reserve(n)` sets capacity to exactly *n* (the authors read libstdc++'s `vector.tcc` lines 64–101 to confirm: [Doc] topics-sources.md). Calling it with "size + 1" on every intern reallocates and copies the whole vector **every time**, which is O(n²) in total. `push_back`'s own geometric growth is what normally makes appends amortized O(1), and an exact `reserve` defeats it.
- **The fix** grows by at least 1.5× (`capacity/2 + 1`), keeping amortized O(1) while still reserving before the commit. The `+1` handles capacity 0. The `min(available, …)` avoids overflow near `max_size()`, which is theoretical but consistent with the project's "no silent wrap" rule.

```cpp
static_assert(std::is_nothrow_move_constructible_v<Topic>);
static_assert(std::is_nothrow_move_constructible_v<Partition>);
```
[Code] `registry.cpp:17-18`

- When a vector grows, it moves its elements to the new buffer only if their move constructor is `noexcept`; otherwise it **copies** them, to preserve the strong guarantee (`std::move_if_noexcept`).
- More importantly, the commit does `topics_.push_back(std::move(topic))`. That must not throw, and a nothrow move guarantees it once capacity is reserved.
- These asserts turn a silent assumption into a compile error if someone later adds a member whose move can throw.

### `ObserverHub`: who is watching which root

```cpp
struct ObserverHub {
  struct Slot { std::uint64_t serial; std::weak_ptr<TopicObserver> observer; };
  std::unordered_map<TopicId, std::vector<Slot>> roots;
  std::uint64_t next_serial{1};
};
```
[Code] `registry.cpp:21-28`

- **Keyed by root `TopicId`.** A subscription with `Subtree(itch/AAPL/add)` registers on ID 3. Whenever a new topic is created, the registry walks *up* from it and checks each ancestor ID in this map.
- **`weak_ptr` observer.** The registry does **not** keep subscriptions alive. If it held `shared_ptr`s, a subscription could never die while the registry lives. Subscriptions also hold handles back to the hub, so that would create a reference cycle and a leak.
- **`serial`.** This is a unique ticket number for the slot. A handle removes its own slot by serial, which works even if the same observer registered several times, for example once per Subtree term. Serial 0 means an empty handle, so serials start at 1.
- **The hub is held through a `shared_ptr` and handles hold a `weak_ptr`.** A handle can therefore outlive the registry safely: `hub_.lock()` simply fails.

### `ObserverHandle`: RAII unregistration

```cpp
ObserverHandle::~ObserverHandle() { reset(); }
ObserverHandle(ObserverHandle&& other) noexcept
    : hub_(std::move(other.hub_)), root_(other.root_), serial_(std::exchange(other.serial_, 0)) {}
```
[Code] `registry.cpp:34-36`

- **Move-only.** Copying is deleted in the header. Two copies of the same handle would both try to unregister one slot.
- `std::exchange(other.serial_, 0)` takes the serial and leaves the moved-from handle empty, so its destructor does nothing.

```cpp
ObserverHandle& operator=(ObserverHandle&& other) noexcept {
  if (this != &other) { reset(); hub_ = ...; root_ = ...; serial_ = std::exchange(other.serial_, 0); }
  return *this;
}
```
[Code] `registry.cpp:37-45`

- It first releases the slot this handle already owns, then takes over the other's.
- The self-move check prevents `h = std::move(h)` from unregistering itself.

```cpp
void ObserverHandle::reset() noexcept {
  if (serial_ != 0) {
    if (auto hub = hub_.lock()) {
      const auto root = hub->roots.find(root_);
      if (root != hub->roots.end()) {
        auto& slots = root->second;
        std::erase_if(slots, [this](const auto& slot) { return slot.serial == serial_; });
        if (slots.empty()) hub->roots.erase(root);
      }
    }
    serial_ = 0;
  }
  hub_.reset();
}
```
[Code] `registry.cpp:46-59`

- `hub_.lock()`: if the registry is gone, do nothing. This is what makes `sub = {}` safe after the registry is destroyed (test `V08Subscriptions.RegistryLifetimeSafeEvenWithExternallyRetainedAnchor`, line 368).
- `std::erase_if` (C++20) removes exactly this handle's slot.
- `if (slots.empty()) hub->roots.erase(root)` stops quiet roots piling up empty vectors. The test `CopyMoveAndDestructionReleaseHooks` creates and destroys 100 subscriptions on the same root, then checks `observer_count() == 0`.
- **Why is `reset` `noexcept`?** It runs from a destructor, and destructors must not throw. Every operation inside (hash of an integer, vector erase of nothrow-movable slots, map erase) cannot throw in practice.

### Constructors and destructor

```cpp
Registry::Registry(Limits limits)
    : limits_(limits), observers_(std::make_shared<detail::ObserverHub>()),
      lifetime_(std::make_shared<Lifetime>()) {
  if (limits.max_topics > UINT32_MAX || limits.max_partitions > UINT32_MAX ||
      limits.max_local_topics > 65536) throw std::invalid_argument(...);
}
Registry::~Registry() { lifetime_->alive_ = false; }
```
[Code] `registry.cpp:61-70`

- `Limits` uses `uint64_t` fields **on purpose**, so the constructor can detect a request that cannot be represented (e.g. `1 << 32` partitions) and reject it, instead of truncating silently. Test: `V38Registry.PartitionLimitAndReservedOwnerSentinel`.
- **Reduced limits are a testing tool.** `Limits{3, 10, 65536}` lets a test hit "topic IDs exhausted" after three topics instead of four billion. [Doc] VALIDATION V38: "No petabyte trace … is needed to exercise representation boundaries."
- **The destructor clears the alive flag first.** It's explained under Lifetime, below.

### Lookup functions

```cpp
void Registry::validate_path(std::string_view path) {
  if (path.empty() || path.front() == '/' || path.back() == '/' ||
      path.find("//") != npos || path.find('\0') != npos) throw std::invalid_argument(...);
}
```
[Code] `registry.cpp:74-79`

- It enforces "slash-separated, non-empty segments" ([Doc] ARCHITECTURE §3.2). It rejects `""`, `"/"`, `"/a"`, `"a/"`, `"a//b"` and any embedded NUL.
- It accepts any other bytes, including UTF-8 such as `Δ` and `%2F` (tested at `topics_subs_test.cpp:123`). P1's converter percent-encodes unusual symbol characters before they reach the registry ([Doc] ARCHITECTURE §2.1).
- **The NUL bug (found in review).** This function originally accepted `std::string("a\0b", 3)`, while the oracle and trace format v1 rejected it. The three components disagreed on what a valid topic is. A C string API would truncate at the NUL and see `"a"`, so two different topics could collide. Fixed and regression-tested ([Doc] review.md finding 1).
- It is `static` and public, because `subs::normalize` calls it to validate every term **before** interning anything.

```cpp
std::optional<TopicId> Registry::find(std::string_view path) const {
  const auto found = paths_.find(path);  ...
}
```
[Code] `registry.cpp:80-83`

- **Heterogeneous lookup.** `paths_` is `unordered_map<std::string, TopicId, StringHash, std::equal_to<>>`, and `StringHash` declares `using is_transparent = void` (`registry.hpp:112-116`). C++20 then lets you call `find(std::string_view)` **without building a temporary `std::string`**. The intern loop calls `find(prefix)` once per segment, so this avoids one heap allocation per prefix for paths longer than the 15-character small-string buffer.
- Both pieces are required: the transparent hash *and* the transparent equality `std::equal_to<>`.

```cpp
const Topic& Registry::get(TopicId id) const {
  if (id == 0 || id > topics_.size()) throw std::out_of_range("invalid topic ID");
  return topics_[id - 1];
}
```
[Code] `registry.cpp:84-89`

- This is a checked access. ID 0 is invalid by definition.
- **The reference is invalidated by the next `intern`**, because the vector may reallocate. The header says so ([Code] `registry.hpp:94-95`: "References/spans may invalidate on intern"). The same applies to `all_topics()` and `all_partitions()` spans.

### `observe()`

```cpp
ObserverHandle Registry::observe(TopicId root, const std::shared_ptr<TopicObserver>& observer) {
  (void)get(root);                                   // root must exist
  if (!observer) throw std::invalid_argument(...);
  if (observers_->next_serial == UINT64_MAX) throw RepresentationLimit(...);
  const auto serial = observers_->next_serial;
  auto [found, inserted] = observers_->roots.try_emplace(root);
  try { found->second.push_back({serial, observer}); }
  catch (...) { if (inserted) observers_->roots.erase(found); throw; }
  ++observers_->next_serial;
  return ObserverHandle{observers_, root, serial};
}
```
[Code] `registry.cpp:105-123`

- **Strong guarantee on a small scale.** If `push_back` throws, a root entry created by *this* call is removed, and the serial is consumed only after success.
- The observer is taken as `shared_ptr` but stored as `weak_ptr` (implicit conversion in the `Slot` initializer).
- `(void)get(root)` validates the root by letting `get` throw. The `(void)` silences `[[nodiscard]]`.

## `intern()`: the heart of the registry

[Code] `registry.cpp:125-241`. It runs in seven steps. **Nothing visible changes until step 7.**

**Step 1: validate and fast path** (125–127)
```cpp
validate_path(path);
if (const auto existing = find(path)) return *existing;
```
The common case once topics exist is one hash lookup.

**Step 2: plan the missing chain in local variables** (129–187)
```cpp
std::vector<Topic> pending;              // topics to create, in parent→child order
std::vector<Partition> new_partitions;   // partitions to create
std::vector<std::pair<PartitionId, std::uint32_t>> additions;  // tentative count increments
```
- It walks the path one segment at a time (`path.find('/', end)`), building each prefix `itch`, `itch/AAPL`, …
- **Existing prefix:** remember its ID as `parent`.
- **Missing prefix:**
  - Check `topics_.size() + pending.size() + 1 <= max_topics`, otherwise throw `RepresentationLimit` (lines 155–156).
  - At depth ≤ 2, create a partition, after checking the partition limit (159–166).
  - Deeper prefixes inherit the parent's partition. The parent may itself still be pending, so its index into `pending` is computed (167–172).
  - Compute the local ID as `existing topic_count + additions already planned for this partition`, and check the local limit (173–179).
  - Append to `pending` (180–183).
- `additions` is a tiny vector searched linearly. A single path can create at most two partitions (one at depth 1, one at depth 2), so a map would be overkill [Inferred].
- `depth` is `uint64_t` and checked against `UINT32_MAX`, because `Topic::depth` is 32-bit. Reaching it is practically impossible, but the check costs nothing [Code].

**Every limit is checked before anything is created.** If the 3rd of 4 new topics would exceed a limit, the first 2 are never registered. Test: `V38Registry.TopicLimitPreflightsEntireAncestorChain` uses `Limits{3,…}`, interns `r`, then tries `r/s/a/b` (3 new topics, total 4 > 3). It throws, and afterwards `r/s` does **not** exist.

**Step 3: stage path-map nodes** (191–193)
```cpp
PathMap staged_paths;
staged_paths.reserve(pending.size());
for (const auto& topic : pending) staged_paths.emplace(topic.path, topic.id);
```
This allocates the hash-map **nodes** now, in a throwaway map. At commit time they are *moved* into `paths_` with `extract`/`insert` (C++17 node handles), which relinks memory without allocating.

**Step 4: reserve all destination capacity** (194–201)
```cpp
reserve_growth(topics_, ...);  reserve_growth(partitions_, ...);
if (paths_.empty() || required_paths > paths_.bucket_count())
  paths_.reserve(std::max(required_paths, paths_.size() + paths_.size() / 2 + 1));
```
- With the default `max_load_factor` of 1.0, having `bucket_count() >= size` means inserting won't trigger a rehash. Rehashing allocates and could throw during the commit.
- The authors read libstdc++'s `hashtable.h` `_M_insert_unique_node` to confirm when a rehash happens ([Doc] topics-sources.md).
- Growth is geometric here too, for the same reason as `reserve_growth`.

**Step 5: find affected observers** (203–222)
```cpp
for (const auto& topic : pending) {
  TopicId ancestor = topic.id;
  while (ancestor != 0) {
    // look up hooks registered on this ancestor; lock each weak_ptr;
    // add to `affected` unless already present (pointer comparison)
    ancestor = parent of ancestor (from topics_ or pending);
  }
}
```
- A subscription on `Subtree(itch/AAPL)` must learn about the new `itch/AAPL/add/attributed`. Walking *up* from each new topic finds every subtree root above it in **O(depth)** lookups. It never iterates over all subscriptions ([Doc] ARCHITECTURE §5.1: "(≤ depth lookups)").
- **De-duplication.** One subscription may be found through several ancestors or several new topics, but it must be prepared only once per intern. Otherwise it would stage two conflicting updates.
- Expired `weak_ptr`s are skipped. That can't normally happen, because handles unregister when the subscription dies, but it's safe if it does.

**Step 6: prepare every observer** (223–229)
```cpp
auto update = observer->prepare(pending);   // may allocate, may throw
updates.push_back(std::move(update));
```
- This is the first phase of a two-phase protocol ([Code] `registry.hpp:42-53`): "A subscription may allocate in `prepare()`, but `commit()` must only perform nonthrowing mutations."
- Each subscription computes its new filter bits on the side (see `03`).
- If **any** prepare throws, for example with `bad_alloc`, the exception propagates. The prepared updates are destroyed unused, and the registry and all subscriptions are unchanged. Test: `V08Subscriptions.ObserverAllocationFailurePrecedesAllRegistrationCommit` registers an observer that throws `std::bad_alloc` and checks the topic count, partition count, path lookup *and the other subscription's bits* are all unchanged.

**Step 7: commit with no-throw operations only** (231–240)
```cpp
for (...) partitions_.push_back(std::move(partition_info));   // capacity reserved, nothrow move
for (...) partitions_[id].topic_count += count;              // integer add
while (!staged_paths.empty()) paths_.insert(staged_paths.extract(staged_paths.begin()));  // relink node
for (...) topics_.push_back(std::move(topic));                // capacity reserved
for (auto& update : updates) update->commit();               // declared noexcept
return result;
```

## The transaction pattern, explained for interviews

**The three exception-safety levels:**
- **Basic**: no leaks, and invariants still hold, but state may have changed.
- **Strong**: commit-or-rollback; on failure, state is exactly as before.
- **No-throw**: the operation never fails.

`intern` gives the **strong guarantee** [Doc] (review.md: "registry stages the complete missing ancestor chain, all topic/partition/local limits, path-map nodes/storage and every affected observer's update before commit").

**How:** *do everything that can fail first, on the side; then publish the result using only operations that cannot fail.* This is the same idea as copy-and-swap, generalized across several containers and several observers.

**Why it matters here** [Doc + Inferred]:
1. **V38 requires it** [Doc]: "reject limits without mutation".
2. **Registry and subscriptions must agree.** If the registry committed a topic but a subscription's filter update failed halfway, a Subtree subscriber would silently miss that topic's messages forever. Loss is never allowed to be silent ([Doc] ARCHITECTURE §3.4).
3. **The differential tests compare against an oracle.** Any partial state would make the engine and the oracle diverge in ways that are hard to debug.

**What *could* still go wrong** [Inferred]: the commit loop isn't marked `noexcept` as a function. It relies on each step being non-throwing because capacity was reserved and moves are nothrow. `Prepared::commit` *is* declared `noexcept`, so if it ever threw, `std::terminate` would run instead of leaving a half-update: loud failure rather than silent corruption.

## Lifetime design

**Problem.** A `CompiledSubscription` holds a raw `Registry*` (see `03`). If the registry is destroyed while a subscription still exists, calling `sub.matches(id)` would read freed memory.

**First design.** The registry owns `shared_ptr<Lifetime>` and hands out `weak_ptr<const Lifetime>` (`identity()`). The subscription checks `identity.lock()` before touching the registry, and a destroyed registry means an expired `weak_ptr`.

**The bug the review found** ([Doc] review.md finding 2): `identity()` is public. A caller can call `registry.identity().lock()` and **keep** that `shared_ptr`. The `Lifetime` object then outlives the registry, so the `weak_ptr` never expires, and the subscription would happily dereference a dangling `Registry*`.

**Fix.** `Lifetime` has an `alive_` flag that the registry's destructor clears **first thing** (`registry.cpp:70`). The subscription checks `lock()` **and** `alive()` (`compiled.cpp:186-187`). Test `RegistryLifetimeSafeEvenWithExternallyRetainedAnchor` holds the anchor across destruction and verifies `matches()` returns false. It runs under ASan, which would flag a use-after-free.

**Why is `Registry` neither copyable nor movable?** (`registry.hpp:89-92`) [Inferred; not stated in the docs]:
- Subscriptions store `Registry*`. Moving a registry changes its address, which would leave those pointers dangling.
- A copy would share the hub and lifetime pointers, making two registries claim one identity.

Deleting both operations makes the address stable for the object's whole life. If you need to move one, put it behind a `unique_ptr`; the engine simply owns it as a member (`engine.hpp:191`).

**Why not have subscriptions hold `shared_ptr<Registry>`?** [Inferred] That would keep a registry alive as long as any subscription exists, so lifetime would no longer follow the engine's ownership. It would also force the engine to heap-allocate its registry. The project chose "a subscription becomes inert when its registry dies" over "a subscription extends the registry's life".

## Complexity summary [Inferred, not measured]

For `intern` of a path with *d* segments, *k* of them new, and *A* affected observers:

| Part | Cost |
|---|---|
| Fast path (exists) | 1 hash of the path: O(L) for path length L |
| Prefix lookups | d hashes of growing prefixes: O(d·L) |
| Staging and commit | O(k) string copies and node moves, amortized O(1) vector growth |
| Observer discovery | O(k·d) hub lookups + slot scans + O(A²) de-duplication (linear `find_if`) |
| Observer prepare | per observer: O(k·(d + log F)) (see `03`) |

Point lookups: `find` is O(L) on average, and `get`/`partition` are O(1).

**Memory per topic** (libstdc++, x86-64; rough): a `Topic` is about 56 bytes, plus a heap copy of its path when it exceeds 15 characters. The `paths_` entry holds **a second copy** of the path in a node of about 56 bytes, plus a bucket pointer.

## Weaknesses and what I'd say I'd change [Inferred]

1. **Paths are stored twice** (in `Topic::path` and as the map key). A `string_view` key pointing into `Topic::path` would dangle when `topics_` reallocates: short strings live *inside* the `std::string` object (the small-string buffer), so moving the object moves the characters. The fix needs stable storage, such as an arena or `std::deque<Topic>`, or storing offsets into one big character buffer.
2. **Observer de-duplication is O(A²)** per intern. With thousands of subscriptions on the same root (say 1,000 wide `Subtree(itch)` readers), creating a topic gets slow. A fix: use an "epoch" stamp on each observer, or an `unordered_set` of pointers.
3. **There is no topic deletion.** IDs, partitions and local IDs are never reclaimed, so a long-running process with churning symbols grows forever. Deletion would need generation counters on IDs (as P4 does for blocks) and a way to update subscribers.
4. **Not thread-safe.** The core is deliberately single-threaded ([Doc] DD-01). Concurrent interning would need a lock, or a read-copy-update scheme in which readers see an immutable snapshot and writers publish a new one.
5. **`get()` throws on invalid IDs.** That's good for safety but adds a branch on the hot path. An unchecked internal accessor could be used where IDs are known valid.

## Ten questions to make sure you can answer

1. Walk me through interning `itch/MSFT/trade/cross` on a registry that already has `itch/AAPL/add/anon`. (`itch` exists. New: `itch/MSFT` gets a new partition and local 0; `trade` gets local 1; `cross` gets local 2.)
2. Why do topic IDs start at 1?
3. What breaks if `reserve_growth` is replaced with an exact `reserve`?
4. Why stage map nodes in a separate map instead of inserting directly?
5. What happens if a subscription's `prepare` throws during intern?
6. Why does the registry store observers as `weak_ptr`?
7. Why is `Registry` non-movable? How would you make it movable?
8. Why does `ObserverHandle` hold a `weak_ptr` to the hub instead of a raw pointer?
9. What does the alive flag protect against that `weak_ptr` alone doesn't?
10. Which partition does `itch` belong to, and why does that matter for wide subscriptions?
