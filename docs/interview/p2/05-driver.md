# 05 — Deterministic driver (`src/tiplog/driver/trace_driver.*`, `tools/tiplog_sim/main.cpp`)

## What it is for

Before an engine can be tested, something has to feed it realistic traffic and play the role of readers. The driver:

1. reads a P1 trace file record by record, in its original order;
2. **publishes** each record through a callback you supply;
3. after each publish, emits one **tick** that tells a consumer callback how many records it may read now (its *budget*), or that it is *paused*.

Everything is controlled by a seed and a configuration, so the same inputs always produce the same schedule. [Doc] ARCHITECTURE §3.7: "The driver models slow readers as consumption budgets per publish tick, or as pauses followed by catch-up."

## API [Code] `trace_driver.hpp`

```cpp
struct Pause  { std::uint64_t first_tick{1}; std::uint64_t ticks{}; };   // ticks [first, first+ticks) paused
struct Config {
  std::uint64_t seed{1};
  std::uint64_t max_records{UINT64_MAX};
  std::uint64_t consume_every{1};      // consumer polls every N publishes
  std::size_t   batch_budget{64};      // records per poll
  bool          jitter_budget{};       // random budget in [1, batch_budget]
  std::vector<Pause> pauses;
};
struct Tick   { std::uint64_t tick; Seq published_seq; std::size_t budget; bool paused; };
struct Result { seed, published, first_seq, last_seq, payload_bytes, publication_digest, schedule_digest; };

using Publish = std::function<Seq(std::string_view, std::span<const std::byte>)>;
using Consume = std::function<void(const Tick&)>;
Result drive_trace(const trace::Reader&, const Config&, const Publish&, const Consume& = {});
```

**Engine-neutral by design** [Doc] header comment: "owns no engine and links no test reference implementation". The same function drives three different publishers:

| Publisher | Where | Purpose |
|---|---|---|
| `ScanOracle::publish` | `driver_test.cpp:60` | Tests: trace to oracle |
| A counter returning `++seq` | `tiplog_sim --backend recording` | P2 smoke test before an engine existed |
| `engine.publish(engine.intern(topic), payload)` | `tiplog_sim --backend engine` (added P3+) | Functional runs of the real engine |

## Annotated code [Code] `trace_driver.cpp`

```cpp
void digest_byte(std::uint64_t& digest, std::uint8_t value) { digest ^= value; digest *= 1099511628211ULL; }
void digest_number(std::uint64_t& digest, std::uint64_t value) {
  for (unsigned i = 0; i < 8; ++i) { digest_byte(digest, value & 255U); value >>= 8; }
}
```
(lines 9–18)

- This is **FNV-1a 64-bit**: start from offset basis `14695981039346656037` (in `Result`), and for each byte, XOR it in and then multiply by the FNV prime `1099511628211`.
- `digest_number` feeds integers **least-significant byte first, explicitly**. The digest is therefore the same on any CPU byte order; it is a *canonical little-endian* encoding ([Doc] header: "over canonical little-endian fields").

```cpp
if (!publish || config.consume_every == 0) throw std::invalid_argument(...);
for (const auto& pause : config.pauses)
  if (pause.first_tick == 0 || pause.ticks > UINT64_MAX - pause.first_tick) throw std::invalid_argument(...);
```
(lines 23–28)

- Configuration is validated **before** anything is published. A pause at tick 0 is invalid because ticks start at 1.
- The second check is the overflow-safe form of `first_tick + ticks > UINT64_MAX`.
- `consume_every == 0` would divide by zero at `tick % consume_every`.

```cpp
std::mt19937_64 random(config.seed);
...
while (result.published < config.max_records && reader.next(cursor, record)) {
  const auto& path = reader.topic_path(record.topic_id);     // resolve via the trace DICTIONARY
  const Seq seq = publish(path, record.payload);
  if (seq == 0 || (result.published != 0 &&
      (result.last_seq == UINT64_MAX || seq != result.last_seq + 1)))
    throw std::logic_error("driver publisher returned non-dense sequence numbers");
```
(lines 29–40)

- **Sparse topic IDs.** Trace v1 stores a dictionary of `{topic_id, path}` pairs ([Doc] ARCHITECTURE §5.0). The driver resolves each record's ID through the dictionary instead of assuming ID = index. The test trace deliberately uses IDs **7 and 900001** (`driver_test.cpp:36`, `:45`) so an "index by position" bug would fail.
- **Dense sequence check.** The engine contract says sequences are dense, global and start at 1 ([Doc] §3.1). If a publisher returns 0, skips a number or repeats one, the driver throws instead of producing a misleading schedule. Test: `InvalidConfigurationsAndPublisherFailuresRemainExplicit` uses a publisher that always returns 1, so the second record throws `logic_error`.
- **Publisher exceptions propagate unchanged**, for example a rejected publish under the `RejectPublish` pool policy (same test, `runtime_error`).

```cpp
if (record.payload.size() > UINT64_MAX - result.payload_bytes) throw std::overflow_error(...);
result.payload_bytes += record.payload.size();
digest_number(publication_digest, seq);
digest_number(publication_digest, path.size());   for (char c : path) digest_byte(..., c);
digest_number(publication_digest, payload.size()); for (byte b : payload) digest_byte(..., b);
```
(lines 44–54)

- **Length-prefixed fields.** Without lengths, the pairs (`"ab"`, `"c"`) and (`"a"`, `"bc"`) would hash identically. Writing each length first makes the encoding unambiguous [Inferred; standard hashing practice].
- The **publication digest** depends only on *what was published*: seq, path and payload. The **schedule digest** depends on the reader schedule. Keeping them separate lets a test show "same data, different schedule" when only the seed changes. Test `SeededBudgetsRepeatAndZeroBudgetDoesNotAdvanceReplay` checks: same seed → identical results; seed + 1 → **equal** publication digest and **different** schedule digest.

```cpp
const auto tick = result.published;                       // 1-based tick = records published so far
bool paused = false;
for (const auto& pause : config.pauses)
  if (tick >= pause.first_tick && tick - pause.first_tick < pause.ticks) paused = true;
std::size_t budget = 0;
if (!paused && tick % config.consume_every == 0) {
  budget = config.batch_budget;
  if (config.jitter_budget && budget != 0)
    budget = 1 + static_cast<std::size_t>(random() % budget);   // in [1, batch_budget]
}
digest_number(schedule_digest, tick); ... seq ... budget ... paused;
if (consume) consume(Tick{tick, seq, budget, paused});
```
(lines 55–72)

- **One tick per published record**, so tick *n* happens right after the *n*-th publish ([Doc] header comment).
- `tick - pause.first_tick < pause.ticks` is again overflow-safe, instead of `tick < first + ticks`.
- **Three ways to make a reader slow:**
  - `consume_every`: it polls only every N messages;
  - `batch_budget`: it takes at most B messages per poll;
  - `pauses`: it stops completely for a stretch (think GC pause or network stall), then must catch up.
- **Jitter gives `1 + r % B`, never 0.** A zero budget means "make no progress" in the replay contract (`04-oracle.md`), so jitter avoids it. The test checks every jittered budget is ≥ 1.
- The PRNG is only advanced on non-paused polling ticks with jitter enabled. The random stream consumed is itself a deterministic function of the configuration.

**Worked schedule** (test `ScriptedPausesCadenceAndMaxRecordsAreDeterministic`: `max_records = 6`, `consume_every = 2`, `batch_budget = 3`, `pauses = {{2, 3}}`):

| tick | paused? (2,3,4) | tick % 2 == 0? | budget |
|---|---|---|---|
| 1 | no | no | 0 |
| 2 | **yes** | — | 0 |
| 3 | **yes** | — | 0 |
| 4 | **yes** | — | 0 |
| 5 | no | no | 0 |
| 6 | no | yes | **3** |

## Design decisions

### Why `std::function` callbacks? [Inferred]

- **Pros:** the driver compiles once into the `tiplog_driver` library, callers pass any lambda, and the driver needs no template or header dependency on any engine. That's what lets production code avoid linking the test oracle.
- **Cons:** an indirect call per publish and per tick (type erasure), and possibly a heap allocation when the `std::function` is *constructed* from a large capture.
- **Why it doesn't matter here:** the driver is a functional and replay tool. [Doc] oracle-driver-sources.md: "Driver schedules are deterministic work controls, not timing/latency evidence." P5/P6 timing uses separate harnesses (`merge_bench`, `publish_bench`, `tiplog_bench`).
- **Alternatives:**
  - a template `drive_trace<Pub, Con>`, which inlines but lives in a header and must be compiled into every caller;
  - a virtual interface `struct Sink { virtual Seq publish(...) = 0; }`, which has similar cost to `std::function` but more boilerplate for callers;
  - `std::function_ref` (C++26), which is non-owning, cheaper, and doesn't allocate.

### Why raw `mt19937_64 % budget` instead of `uniform_int_distribution`? [Doc]

- The C++ standard fully specifies the **engines**: `mt19937_64` produces the same numbers on every conforming library. The **distributions**, such as `uniform_int_distribution`, have implementation-defined algorithms, so libstdc++ and libc++ can produce different values from the same seed.
- The project builds with GCC and Clang (RC3 compares repeated GCC/Clang runs), so schedules must not depend on the standard library. [Doc] header comment: "Uses raw mt19937_64 output modulo batch_budget, avoiding implementation-dependent uniform_int_distribution mapping."
- **Modulo bias.** `r % B` is very slightly non-uniform when B doesn't divide 2⁶⁴. The bias is at most about B/2⁶⁴, which is negligible, and the header explicitly says "This is a schedule, not a claim of statistically uniform workload sampling."
- The authors inspected libstdc++'s `random.tcc` to confirm the engine's behaviour ([Doc] oracle-driver-sources.md).

### Why FNV-1a and not SHA-256? [Doc]

- FNV-1a is tiny, fast, dependency-free and deterministic, which is enough to detect "did this run reproduce the last one?"
- It is **not** collision-resistant, since collisions can be constructed deliberately. [Doc] header: "these are reproducibility checks, not cryptographic identity/checksum substitutes." P1 uses SHA-256 for real data identity (the dataset and trace hashes in `data/manifest.json`).

## `tiplog_sim` (the CLI) [Code] `tools/tiplog_sim/main.cpp`

- **In P2 it had only a "recording" backend.** The publisher just counts (`return ++sequence;`, now lines 185–191), because no engine existed until P3.
- [Doc] phase-gate.json: "P2 CLI recording backend is explicit; production engine integration starts P3." The name **recording** is deliberate. Its output must never be mistaken for engine results.
- **What the P2 smoke test did:** published the first 10,000 real trace events and printed aggregate counts and digests. It never prints payload bytes, because the raw Nasdaq data stays local ([Doc] oracle-driver-sources.md).
- **Later phases added the `engine` backend** (now the default):
  - it builds an `Engine`;
  - it compiles a subscription, defaulting to `Subtree(itch)`;
  - it opens a `Tail` with the selected mode and kernel;
  - it polls on each non-paused tick with that tick's budget;
  - it hashes deliveries and reports the final status, error and checkpoint as JSON.

  The diff against `d4e5b83` (56 insertions) is P5's mode, kernel and Auto options. The original P2 version isn't recoverable from git, because the first commit was made in P4 ([Doc] PROGRESS P4, "snapshot commit d4e5b83").
- **Number parsing** uses `std::from_chars` and requires the whole string to be consumed. So `--budget 12abc` is rejected instead of being read as 12 [Code] `main.cpp:15-23`.

## Ten questions to make sure you can answer

1. Why does the driver resolve topic IDs through the dictionary?
2. What happens if the publisher returns the same sequence twice?
3. Why are there two digests? What does changing only the seed change?
4. Why is jitter `1 + r % B` and not `r % (B + 1)`?
5. Why not `uniform_int_distribution`? Is modulo bias a problem here?
6. Why length-prefix fields before hashing?
7. Why is FNV acceptable here but not for the dataset checksum?
8. Why `std::function`? When would you change it?
9. What does "recording backend" mean, and why does the name matter?
10. How would you model a reader that falls behind by exactly 1 GiB?
