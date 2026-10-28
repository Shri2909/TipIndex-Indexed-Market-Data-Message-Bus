# 09 — Whiteboard drills and bug hunts

Do these **without notes**, on paper or in a blank editor. Answers are at the end. Every answer key was traced by hand through the actual code paths.

---

## Part 1: Implement from scratch (10–20 minutes each)

**W1. `validate_path(std::string_view)`.** Throw `std::invalid_argument` for an empty path, a leading or trailing `/`, any empty segment, or an embedded NUL.

**W2. `bool under(std::string_view root, std::string_view path)`.** True if `path == root`, or `path` is a descendant of `root` at a segment boundary. Must give `under("itch/AA", "itch/AAPL") == false`.

**W3. `normalize(std::vector<Term>)`.** Reject an empty list. De-duplicate. Drop an Exact covered by a Subtree on itself or an ancestor, and a Subtree covered by a strict-ancestor Subtree. Output sorted by (path, kind). Target O(n log n + n·depth) expected.

**W4. A partition filter.** Write `set(uint16_t id)`, `test(uint16_t id)` and `set_all()` over a lazily grown `std::vector<uint64_t>`. No undefined behaviour for id 63 or 65,535.

**W5. Simplified `intern`.** No observers. Use `vector<Topic> topics` (IDs from 1), `vector<Partition> partitions` and `unordered_map<string, TopicId>`. Create missing ancestors. A topic at depth ≤ 2 creates a partition; deeper topics inherit. Local IDs are dense per partition. **All-or-nothing:** if the local-ID limit would be exceeded anywhere along the path, change nothing.

**W6. `drive` loop.** Given a list of `(path, payload)` records, publish each one, check that returned sequences are dense from the first, and compute the budget per tick using `consume_every`, `batch_budget` and pause windows `[first, first + ticks)`.

---

## Part 2: Predict the state

### P1. Registry and subscription trace

Start from an empty `Registry` and run, in order:

1. `intern("itch/_market/system_event")`
2. `intern("itch/AAPL/add/anon")`
3. `S = compile({Subtree(itch/AAPL/add), Exact(itch/AAPL/modify/executed), Subtree(itch/_market)})`
4. `intern("itch/AAPL/modify/cancel")`
5. `intern("itch/AAPL/add/attributed")`
6. `intern("itch/_market/mwcb/status")`

Questions:
- (a) The ID, partition and local ID of every topic created.
- (b) `S.normalized_terms()`, `S.wide()`, and S's filters after step 3.
- (c) Which of steps 4–6 call `S.prepare`, and what changes?
- (d) S's final filters, and the topic IDs for which `S.matches` is true.
- (e) `registry.observer_count()` after step 3.

### P2. Oracle ring trace

`ScanOracle oracle({128, 64})`, so C = 128 and max record = 64. Publish to path `a` these payload sizes in order: **40, 40, 30, 0, 20**.

- (a) For each record: `need`, PAD (if any), DATA position, head after, `tail_pos`, `tail_seq`.
- (b) `open_replay(Exact(a), 1)`: status and error.
- (c) `r = open_replay(Exact(a), 2)`: the checkpoint and upper bound. Why is the checkpoint's position not 112?
- (d) `r.next_batch(2, out)`: what is delivered, the status, and the checkpoint.
- (e) Now publish one more record with a **48-byte** payload. Then `r.next_batch(2, out)`: what happens?

### P3. Driver schedule

`consume_every = 3`, `batch_budget = 5`, `pauses = {{4, 2}}`, `max_records = 8`, no jitter. List the budget at ticks 1–8.

### P4. Normalize these

- (a) `{Subtree x/y, Exact x/y/z, Exact x/yz, Subtree x/y/z}`
- (b) `{Exact m, Subtree m-n, Exact m-n/o, Subtree m/n, Exact m/n}`
- (c) `{Subtree itch, Subtree itch/AAPL, Exact bnc/BTC/trade}`. Also: is it wide?

---

## Part 3: Find the bug (each snippet has exactly one important bug)

**B1.**
```cpp
bool subtree_matches(std::string_view root, std::string_view path) {
  return path.starts_with(root);
}
```

**B2.**
```cpp
TopicId Registry::intern(std::string_view path) {
  ...plan pending...
  for (auto& t : pending) {
    paths_.emplace(t.path, t.id);        // commit
    topics_.push_back(std::move(t));
  }
  for (auto& u : updates) u->commit();
}
```

**B3.**
```cpp
struct ObserverHub {
  struct Slot { std::uint64_t serial; std::shared_ptr<TopicObserver> observer; };
  std::unordered_map<TopicId, std::vector<Slot>> roots;
};
```

**B4.**
```cpp
struct CompiledState final : TopicObserver {
  const Matching matching;
  std::vector<Term> terms;
  CompiledState(std::vector<Term> t) : terms(std::move(t)), matching(terms) {}
};
```

**B5.**
```cpp
filter.bits[id / 64] |= (1 << (id % 64));
```

**B6.**
```cpp
// normalize after sorting by raw path
std::optional<std::string> root;
for (const auto& t : sorted) {
  if (root && under(*root, t.path)) continue;       // covered
  out.push_back(t);
  if (t.kind == Term::Subtree) root = t.path;
}
```

**B7.**
```cpp
Status OracleReplay::next_batch(std::size_t max, std::vector<OracleRecord>& out) {
  out.clear();
  if (max == 0 || status_ != Status::More) return status_;
  if (checkpoint_->next_pos < oracle_->tail_pos()) { status_ = Error; /* FellBehind */ return status_; }
  if (checkpoint_->next_pos == upper_pos_) { status_ = Done; return status_; }
  ...
}
```

**B8.**
```cpp
ObserverHandle(ObserverHandle&& other) noexcept
    : hub_(other.hub_), root_(other.root_), serial_(other.serial_) {}
```

**B9.**
```cpp
void prepare_storage(std::size_t pending) {
  topics_.reserve(topics_.size() + pending);
}
```

**B10.**
```cpp
if (config.jitter_budget) budget = random() % (config.batch_budget + 1);
```

**B11.**
```cpp
OracleReplay::OracleReplay(const ScanOracle& o, const SubscriptionSpec& s, Seq after)
    : upper_seq_(o.head_seq() - 1) {
  if (after + 1 < o.tail_seq()) { /* HistoryExpired */ return; }
  if (after >= upper_seq_) { status_ = Done; return; }
  ...
}
```

**B12.**
```cpp
CompiledSubscription compile(Registry& r, const SubscriptionSpec& spec) {
  std::vector<TopicId> roots;
  for (const auto& term : spec.terms) roots.push_back(r.intern(term.path));
  auto normalized = normalize(spec);
  ...
}
```

---
---

# Answers

### W1
```cpp
void validate_path(std::string_view p) {
  if (p.empty() || p.front() == '/' || p.back() == '/' ||
      p.find("//") != std::string_view::npos || p.find('\0') != std::string_view::npos)
    throw std::invalid_argument("bad path");
}
```
(Leading `/`, trailing `/` and `//` together cover every possible empty segment.)

### W2
```cpp
bool under(std::string_view root, std::string_view path) {
  return path == root ||
         (path.size() > root.size() && path.starts_with(root) && path[root.size()] == '/');
}
```

### W3
Sort by (path, kind), `unique`, put the Subtree paths in an `unordered_set<string>` with a transparent hash, then keep a term unless one of its prefixes ending right before a `/` is in the set, or, for an Exact term, the path itself is. This is the current production code (`compiled.cpp:88-116`).

### W4
```cpp
void set(uint16_t id) { if (all) return; auto w = id / 64u;
  if (bits.size() <= w) bits.resize(w + 1, 0);
  bits[w] |= std::uint64_t{1} << (id % 64u); }
bool test(uint16_t id) const { auto w = id / 64u;
  return all || (w < bits.size() && (bits[w] >> (id % 64u) & 1u)); }
void set_all() { all = true; bits.clear(); }
```

### W5
The key point is **two passes**: plan every prefix into a local `pending` list, checking each limit (counting local IDs already planned for the same partition), and only then commit everything. Compare with `registry.cpp:129-187` (plan) and `231-240` (commit).

### W6
See `trace_driver.cpp:34-73`. Throw if `seq == 0`, or if `seq != last + 1` after the first record. `tick` is the 1-based publish count. Budget = 0 if paused or `tick % consume_every != 0`.

### P1
(a)

| Step | Topic | ID | Partition | Local |
|---|---|---|---|---|
| 1 | `itch` | 1 | 0 (new) | 0 |
| 1 | `itch/_market` | 2 | 1 (new) | 0 |
| 1 | `itch/_market/system_event` | 3 | 1 | 1 |
| 2 | `itch/AAPL` | 4 | 2 (new) | 0 |
| 2 | `itch/AAPL/add` | 5 | 2 | 1 |
| 2 | `itch/AAPL/add/anon` | 6 | 2 | 2 |
| 3 (compile interns roots) | `itch/AAPL/modify` | 7 | 2 | 3 |
| 3 | `itch/AAPL/modify/executed` | 8 | 2 | 4 |
| 4 | `itch/AAPL/modify/cancel` | 9 | 2 | 5 |
| 5 | `itch/AAPL/add/attributed` | 10 | 2 | 6 |
| 6 | `itch/_market/mwcb` | 11 | 1 | 2 |
| 6 | `itch/_market/mwcb/status` | 12 | 1 | 3 |

(b) The normalized terms, in sorted order, are `[Subtree itch/AAPL/add, Exact itch/AAPL/modify/executed, Subtree itch/_market]`. `A` (0x41) sorts before `_` (0x5F), and nothing is covered. `wide()` is false, since no Subtree term lacks a `/`.
- Matching sets: exact = {`…/modify/executed`}; subtree = {`itch/AAPL/add`, `itch/_market`}; whole_partition = {`itch/_market`} (one slash).
- Initial scan: ID 2 matches and covers its partition, so partition 1 is `all`; ID 3 is skipped because partition 1 is already `all`; IDs 5, 6 and 8 set local bits 1, 2 and 4.
- Filters: `[ {P1, all}, {P2, bits[0] = 0b10110 = 0x16} ]`.

(c)
- **Step 4:** ancestors 9 → 7 → 4 → 1 carry no hooks (hooks are on 5 and 2), so `prepare` is **not called**. `S.matches(9)` is false, which is correct, since a cancel isn't selected.
- **Step 5:** ancestors 10 → **5** (hook), so `prepare([10])` runs. 10 matches through prefix `itch/AAPL/add`; P2's filter exists and isn't `all`, so a changed copy gets bit 6, and the commit swaps in `0x56`.
- **Step 6:** ancestors 11 → **2** (hook), so `prepare([11, 12])` runs. Both match, but P1 is `all`, so nothing is staged.

(d) Final filters: `[ {P1, all}, {P2, 0x56} ]`. `matches` is true for **2, 3, 11, 12** (all of `_market`) and **5, 6, 8, 10**; false for 1, 4, 7, 9.

(e) 2: one hook per Subtree term, on IDs 5 and 2.

### P2
(a) `need = round8(16 + payload)`

| seq | payload | need | head before | offset (head % 128) | space | PAD | DATA pos | head after | head − C | tail_pos | tail_seq |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 40 | 56 | 0 | 0 | 128 | — | 0 | 56 | — | 0 | 1 |
| 2 | 40 | 56 | 56 | 56 | 72 | — | 56 | 112 | — | 0 | 1 |
| 3 | 30 | 48 | 112 | 112 | **16** | **[112, 128)** | 128 | 176 | 48 | **56** | 2 |
| 4 | 0 | 16 | 176 | 48 | 80 | — | 176 | 192 | 64 | **112** (PAD) | 3 |
| 5 | 20 | 40 | 192 | 64 | 64 | — | 192 | 232 | 104 | 112 | 3 |

(b) `after + 1 = 2 < tail_seq = 3`, so the status is **Error** with `HistoryExpired{requested 1, last_delivered 1, oldest_retained 3}`.

(c) The upper bound is `{5, 232}` and the checkpoint is `{2, 128}`. The open uses `records_[2].pos`, the position of seq 3's **DATA**, which skips the PAD at 112.

(d) It delivers seq 3, with checkpoint `{3, 176}`, then seq 4, with checkpoint `{4, 192}`. The budget is now full, so it returns **More** without looking ahead.

(e) The new record needs 64. The offset is 232 % 128 = 104 and the space is 24 < 64, so a **PAD [232, 256)** goes in and the DATA lands at 256. Head is 320 and head − C = 192, so everything before 192 is evicted (the PAD at 112, seq 3 at 128, seq 4 at 176). Seq 5 at **192 is retained**, since 192 ≥ 192. `tail_pos` is 192 and `tail_seq` is 5.

Then `next_batch(2)`: `next_pos` 192 ≠ upper 232, and 192 is **not** < tail 192, so there's no error. It delivers seq 5, with checkpoint `{5, 232}`. The captured history is exhausted, so the result is **Done** with checkpoint `{5, 232}`. The new seq 6 isn't delivered, because it's above the captured upper bound. The reader survived by exactly zero bytes.

### P3
Ticks 1–8 have budgets **0, 0, 5, 0 (paused), 0 (paused), 5, 0, 0**.

### P4
- (a) `{Subtree x/y, Exact x/yz}`. `x/y/z` (both kinds) is under `x/y`; `x/yz` isn't (no boundary).
- (b) `{Exact m, Subtree m-n, Subtree m/n}`. `Exact m` stays, because nothing covers it (only Subtrees cover). `Exact m-n/o` is covered by `Subtree m-n`, and `Exact m/n` by `Subtree m/n` on the same path.
- (c) `{Exact bnc/BTC/trade, Subtree itch}`, in sorted order, since `b` < `i`. `Subtree itch/AAPL` is covered by `Subtree itch`. It **is** wide (`Subtree itch` has no `/`), so the engine will use Scan.

### Bugs
- **B1.** No segment boundary: `subtree_matches("itch/AA", "itch/AAPL")` returns true. Fix: require `path == root`, or the next character to be `'/'`.
- **B2.** The commit allocates. `emplace` creates a node, may rehash and may throw `bad_alloc`, and `push_back` may reallocate. A throw on the second topic leaves the first one registered: a partial intern. Fix: stage nodes, reserve capacity, then splice with `extract` / `insert`.
- **B3.** A strong `shared_ptr` to observers: subscriptions can't die while the registry lives, and with handles referencing the hub, there's a cycle. Fix: `weak_ptr`.
- **B4.** Member order. `matching` is declared before `terms`, so it's initialized first, from a not-yet-constructed `terms`. That's undefined behaviour. Fix: declare `terms` first (and compile with `-Wreorder`).
- **B5.** `1` is an `int`, so shifting by 32–63 is undefined behaviour. Fix: `std::uint64_t{1} << (id % 64)`.
- **B6.** The lexical-interleaving trap: with `a`, `a-foo`, `a/b`, the remembered root becomes `a-foo`, and `a/b` is kept wrongly. It also only remembers one root. Fix: a hash set of all subtree roots with per-term ancestor checks, or a segment-wise sort with a stack.
- **B7.** Expiry is checked **before** completion. A reader whose last batch ended exactly at `upper_pos` gets FellBehind after a later eviction, even though it received everything. Fix: check `next_pos == upper_pos` first.
- **B8.** The "move" copies `hub_` and doesn't clear the source's serial, so **both** handles believe they own the registration. When the moved-from handle is destroyed (typically right away, e.g. a temporary during `hooks.push_back`), its `reset()` erases the slot. The surviving handle still looks registered, but the hub has no slot, so the subscription **silently stops receiving new topics** under that root. That is a silent-loss bug. Fix: `hub_(std::move(other.hub_))` and `serial_(std::exchange(other.serial_, 0))`, as in `registry.cpp:35-36`.
- **B9.** An exact `reserve` on every call defeats geometric growth, which is quadratic. Fix: grow to `max(needed, cap + cap/2 + 1)`.
- **B10.** It can produce budget **0** (meaning "no progress"), and the range is `[0, B]`, not `[1, B]`. Fix: `1 + random() % budget` (guarding budget ≠ 0).
- **B11.** `after + 1` is computed before the `after >= upper_seq` check. With `after = UINT64_MAX`, it wraps to 0 and skips the empty-range case. Fix: check `after >= upper_seq` first.
- **B12.** It interns **before** validating and normalizing. A malformed later term throws after earlier roots are already interned, and it interns redundant roots too. Fix: `normalize` first, then intern the normalized roots.
