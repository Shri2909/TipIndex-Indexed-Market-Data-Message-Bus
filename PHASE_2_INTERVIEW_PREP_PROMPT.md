# Phase 2 interview-preparation prompt

Run this in a new Claude Code session opened in this workspace (`/home/abc/Desktop/Jane Street`). Paste everything below the line.

---

## Your role

Act as two people at once:

1. **The interviewer.** You are a senior C++ engineer on a trading firm's market-data or trading-infrastructure team. You have read this repository closely and want to find the edge of the candidate's understanding.
2. **The mentor.** You make sure the candidate survives that interview.

The candidate is me. I am this project's author of record, but I have **zero working knowledge of its code**, because it was produced in agent-driven sessions. I know C++ and Python at a general level. Assume I know nothing about finance, market data or this codebase. I must be able to defend every line of Phase 2 as if I wrote it myself.

## Goal

Teach me **Phase 2 (P2)** of `tiplog` completely:
- what every part does;
- why it was designed this way;
- which alternatives were rejected, and why;
- what it costs and where it is weak.

Then prepare me for every angle an interviewer could grill me on.

## Context: read it, don't assume it

`tiplog` is a C++20, single-process, single-threaded pub/sub log for market data. It is modeled on Jane Street's article about their Aria message bus, which is summarized in `docs/plan/RESEARCH.md` §1. P2 covers four pieces: the **topic registry**, **subscription normalization and compilation**, an **independent test oracle**, and a **deterministic trace driver**. P3 (ring and scan replay), P4 (partition index) and P5 (merge kernels) all build on P2.

Read all of the following before you write anything.

**Planning and rationale**
- `docs/plan/ARCHITECTURE.md`:
  - §2.1–2.3: topic hierarchy, partitions, consumers
  - §3.1–3.7: semantics
  - §5.1–5.2: registry and subscription compilation
  - §9: interfaces
  - §10: invariants
  - §11: design decisions and alternatives
  - §12: failure handling
- `docs/plan/IMPLEMENTATION_PLAN.md`, P2 section
- `docs/plan/VALIDATION_PLAN.md`, checks V06–V09 and V38
- `docs/plan/RESEARCH.md` §1, which separates what the article states from what was inferred
- `docs/plan/PROGRESS.md`, section "Phase 2 completed gate and Phase 3 handoff"

**P2 evidence and review**
- `results/p2/review.md`: the independent review, including three bugs it found and fixed
- `results/p2/topics-sources.md` and `results/p2/oracle-driver-sources.md`: ledgers that map each finding to a decision, the code that implements it, and the check that verifies it
- `results/p2/phase-gate.json`
- `results/p6/subscriptions-scaling.md`: a later P6 repair to P2 code

**P2 code (read every line)**

| Component | Files |
|---|---|
| Shared value types | `src/tiplog/types.hpp` |
| Topic registry | `src/tiplog/topics/registry.hpp`, `src/tiplog/topics/registry.cpp` |
| Subscriptions | `src/tiplog/subs/compiled.hpp`, `src/tiplog/subs/compiled.cpp` |
| Independent oracle (test-only) | `tests/ref/scan_oracle.hpp`, `tests/ref/scan_oracle.cpp` |
| Deterministic driver | `src/tiplog/driver/trace_driver.hpp`, `src/tiplog/driver/trace_driver.cpp`, `tools/tiplog_sim/main.cpp` |
| Build wiring | `cmake/p2.cmake`, `cmake/p2_ref.cmake` |
| Tests | `tests/unit/topics_subs_test.cpp`, `tests/unit/oracle_test.cpp`, `tests/unit/driver_test.cpp` |

**Downstream use.** Grep how `src/tiplog/engine/`, `src/tiplog/index/` and `src/tiplog/merge/` use `Registry`, `CompiledSubscription`, `PartitionFilter`, `wide()`, `local_id` and partition IDs; start with `src/tiplog/engine/engine.hpp`. Interviewers will ask who consumes each structure and why it needs that shape.

**Code history (important)**
- Git works only through the wrapper `scripts/git.sh <git args>`. Plain `git` cannot find this repository.
- P2 code was first committed in `d4e5b83`.
- During P6, `src/tiplog/subs/compiled.cpp` and `tests/unit/topics_subs_test.cpp` were changed (still uncommitted) to fix quadratic-time normalization that showed up at 100,000 partitions. Explain **both** the original and current versions; use `scripts/git.sh diff d4e5b83 -- src/tiplog/subs/compiled.cpp`. "What did you change, and why?" is a strong interview story.
- `tools/tiplog_sim/main.cpp` and `cmake/p2_ref.cmake` also changed after P2. Say what changed and whether it belongs to P2.

## Ground rules

1. **Protect the running project.** P6 timing campaigns need a quiet machine.
   - Before building or running anything, check: `ps -eo pid,cmd | grep -E 'run_p6|tiplog_bench|merge_bench|publish_bench|fuzz_' | grep -v grep`. If any of these is running, stay read-only: no builds and no tests.
   - Do not edit source, tests, CMake, `configs/`, `results/` or `docs/plan/`. Write only the study files listed below.
   - Put throwaway experiments in your session scratchpad directory, never in the repo.
2. **Label the source of every "why".**
   - **[Doc]**: stated in a planning or review document. Cite the file and section.
   - **[Code]**: evident from the code. Cite `file:line`.
   - **[Inferred]**: your own reasoning, where the documents are silent. Say so plainly, and never present an inference as the author's stated reason.
3. **Verify; don't guess.** Every worked example must be checked. For example: which topic IDs, partitions and local IDs does interning a given path produce? Trace the code path. If the machine is idle, you may also compile a tiny scratch program or test against the existing `build/release` build. Name the real test that covers each behavior, and grep to confirm the name exists.
4. **Use numbers only from evidence.** Quote test counts, such as 52/52 tests or 37 P2 cases, only from `results/` files. P2 has no performance benchmarks. For complexity, give asymptotic and constant-factor reasoning labeled [Inferred], never a measured claim.
5. **Teach from zero.** Define every term the first time you use it: topic, subtree, partition, local ID, normalization, observer, strong exception guarantee, test oracle, differential testing, and so on. Use one running example throughout, built from real Nasdaq ITCH paths such as `itch/AAPL/modify/executed`, `itch/AAPL/trade/cross`, `itch/AAPL/add/anon` and `itch/_market/system_event`.
6. **Annotate every function.** For each function in the P2 files, show the code in small chunks, each followed by a plain-English explanation of what that line or block does and why it is there.
7. **Depth, not padding.** Skip generic C++ tutorials unrelated to this code.

## Deliverables

Write these as separate files under `docs/interview/p2/`, so each one can be studied in a single sitting.

### `00-overview.md`
- What P2 is for, first in five sentences, then in one page.
- Where P2 sits in the system, with a diagram covering both flows:
  - publishing: trace → driver → engine publish → registry intern;
  - reading: reader → subscription compile → partition filters → replay.
- What P3–P5 need from P2.
- A glossary.
- A 60-second spoken explanation and a 5-minute spoken explanation that I can memorize.

### `01-types.md`
Cover `types.hpp`:
- every type it defines;
- why each width was chosen: u64 `Seq`/`LogPos`, u32 `TopicId`/`PartitionId`, u16 local ID;
- why the header holds value types only (so the oracle stays independent);
- defaulted `operator==` and the enums.

### `02-registry.md`
- **Walkthrough of `intern()`.** Use the running example and show the state of `topics_`, `partitions_`, `paths_` and the local IDs before and after each call.
- **Partition rule.** A topic at depth ≤ 2 gets its own partition; deeper topics inherit their ancestor's. Explain why two segments (article statement A6), and what happens to a depth-1 topic like `itch`.
- **ID scheme.**
  - Topic ID 0 is the "no parent" sentinel, and topic IDs are the vector index + 1.
  - Partition `UINT32_MAX` is reserved for P4's free-owner sentinel.
  - Local IDs are dense u16 values per partition, capped at 65,536. Explain why, what breaks if the cap is exceeded, and how that is tested.
- **Transactional design.**
  - First everything is prepared: the full ancestor chain, limit checks, staged map nodes, capacity reservation, and every observer's prepare step. Then a `noexcept` commit runs.
  - Explain the basic, strong and no-throw exception guarantees, and why the strong guarantee was chosen here.
  - Show how unordered-map node extract/insert and earlier `reserve` calls make the commit non-allocating.
  - Cover the injected `bad_alloc` test.
- **Lookup and growth.** Transparent (heterogeneous) hash lookup, and `reserve_growth` geometric growth, including the quadratic-reserve bug it fixed.
- **Observer mechanism.** `ObserverHub`, slots with serial numbers, `weak_ptr` observers, the move-only RAII `ObserverHandle`, the ancestor walk that finds affected observers, and observer de-duplication.
- **Lifetime.**
  - Why `Registry` is neither copyable nor movable.
  - The `Lifetime` alive flag plus the `weak_ptr` identity.
  - The "externally retained anchor" bug, and why a `weak_ptr` expiry check alone was not enough.
- **Validation.** The `validate_path` rules and the embedded-NUL bug.
- **Invalidation.** Which spans and references `intern` can invalidate.

### `03-subscriptions.md`
- **Semantics.** A subscription is a union of Exact and Subtree terms. Matching respects segment boundaries: a Subtree term on `itch/AA` must not match `itch/AAPL`.
- **`normalize()`.**
  - Sort, de-duplicate, and remove covered terms; handle an Exact and a Subtree term on the same path.
  - The lexical-interleaving trap: `a`, `a-foo`, `a/b`.
  - The original all-pairs version versus the current hash-set-of-roots version: complexity of each, and why the change was needed (the T3 test at 100,000 partitions).
- **`compile()`.**
  - Why it interns every root, even an Exact topic that has never been published.
  - The `Matching` sets and the initial scan over all existing topics.
  - `PartitionFilter`: a vector sorted by partition, holding either an `all` flag or a bitset of local IDs.
  - `covers_partition`, and `wide`: a depth-1 subtree makes the engine fall back to Scan. Show where the engine uses this.
  - Hooks exist only for Subtree terms. Explain why Exact terms need none.
- **Topics created after compile.** The prepare/commit path, staged changed and added filters, capacity reservation, and the `noexcept` commit.
- **Ownership graph.** Draw it: `CompiledSubscription` → `shared_ptr<CompiledState>` (which is a `TopicObserver`) → `ObserverHandle`s. The registry holds only `weak_ptr`s, so there is no reference cycle. Copies share one state, and the last copy unregisters the hooks.
- **Matching cost.** The `matches()` path is a registry lookup, then a binary search over the filters, then a bit test. Explain why overlapping terms still deliver each event exactly once.

### `04-oracle.md`
- **Why an oracle.** What a test oracle is, and why it must be independent of production code (to avoid both sides sharing the same bug).
- **What is shared.** It shares only `types.hpp` with production. Show how the CMake files keep it test-only.
- **Its model.** Its own path matcher, the full publication history, a DATA/PAD ring model using division/modulo positions, whole-record eviction, and the position and sequence limits.
- **Replay semantics as specified and modeled.** For each of the following, give a small timeline example and name the test that covers it:
  - the exclusive upper bound captured at open;
  - the `next_batch` budget and the More/Done/Error statuses;
  - HistoryExpired versus FellBehind, and conservative expiry;
  - zero-budget calls;
  - completion on an exact final budget before any later expiry;
  - no look-ahead across filtered gaps;
  - the `(after_seq, next_pos)` checkpoint, and a zero-output snapshot still advancing it;
  - overflow-safe queries for future positions.
- **Speed.** Why the oracle is slow, and why that is acceptable.

### `05-driver.md`
- **`drive_trace`.** Engine-neutral `std::function` callbacks, ticks, pauses, cadence, budgets and jitter.
- **Determinism.**
  - Raw `mt19937_64` output taken modulo the budget, instead of `uniform_int_distribution`, so results reproduce across standard libraries. Acknowledge the modulo bias.
  - FNV-1a digests are diagnostic only, not cryptographic.
  - Sparse trace IDs are resolved through the trace dictionary.
- **`tiplog_sim`.** Its "recording" backend, and why it is labeled honestly as such.

### `06-testing.md`
- **Test map.** For every P2 test, by exact name: what it proves, which check it implements (V06, V07, V08, V09 or V38), and what it does **not** prove.
- **How correctness was checked.**
  - Randomized tests against an independent segment matcher and an all-pairs normalizer.
  - Sanitizer builds.
  - The exact `ctest -R` filter that runs only the P2 tests, for use when the machine is idle.
- **Interview stories.** Write each bug as situation → symptom → root cause → fix → regression test → lesson:
  - the embedded-NUL path bug;
  - the retained lifetime anchor bug;
  - the quadratic reserve bug;
  - the P6 quadratic normalization fix.

### `07-design-decisions.md`
A table with one row per significant decision. Columns:
- Decision
- Chosen approach
- At least two alternatives
- Why the chosen approach
- When an alternative would win
- Evidence label

Alternatives to weigh include a trie, regex/glob matching, per-topic subscriber lists, an inverted index from topics to subscriptions, `unordered_set<TopicId>` filters, `std::bitset`, roaring bitmaps, `std::map`, interned `string_view`s, intrusive lists, `std::function` versus templates versus virtual calls, and exceptions versus error codes or `std::expected`.

Cover at least these decisions:
- path representation
- hierarchy split
- partition depth
- ID widths
- dense versus sparse IDs
- filter representation and filter container
- normalization strategy
- eager versus lazy compile
- observer versus recompiling when a topic is created
- ownership and lifetime model
- exceptions and the transactional strong guarantee
- the single-threaded assumption
- oracle independence
- driver callback design
- PRNG choice

### `08-question-bank.md`
At least 120 questions, grouped as follows:
- **Fundamentals:** "explain X".
- **Code-level:** "what does line N do?", "what happens if we delete it?"
- **C++ language:**
  - move semantics, the rule of five, `noexcept` and vector reallocation, `static_assert` on nothrow move;
  - `weak_ptr`/`shared_ptr`, transparent hashing, span and iterator invalidation, `[[nodiscard]]`;
  - virtual calls versus `std::function`, unordered-map node handles, sources of undefined behavior.
- **Complexity and performance:** time and space per operation, cache behavior, hashing cost, memory per subscription at 100,000 partitions, and what you would measure.
- **Correctness and edge cases:**
  - an empty spec, an Exact and a Subtree term on the same path, a subtree on `itch`, the 65,536th topic in a partition;
  - the registry destroyed before a subscription, an observer that throws, `bad_alloc` in the middle of `intern`, integer overflow.
- **Testing:** "how do you know it's correct?", "what would your oracle miss?"
- **Design trade-offs:** "why not a trie?" and similar.
- **Scaling and extensions:**
  - multithreading: what breaks first, and fixes such as RCU, epochs or sharding;
  - middle wildcards like `itch/*/trade`, topic deletion and garbage collection;
  - 1M subscriptions, a distributed bus, persistence.
- **Domain:** why the ITCH paths look the way they do, why order-book (BOOK) consumers also need `_market`, what partitions mean to a trader.
- **Behavioral and ownership:** "this was AI-assisted, so what did you personally decide and verify?", "what are you least proud of?", "what would you redo?"

For each question, give:
- a difficulty from ★ to ★★★★;
- a crisp model answer of at most six sentences;
- a code reference;
- one to three likely follow-ups, with short answers;
- common wrong answers or traps.

### `09-exercises.md`
Whiteboard drills to do without notes:
- Re-implement `validate_path`, segment-boundary matching, `normalize`, `PartitionFilter` set/test, and the ancestor loop in `intern`.
- Given a sequence of `intern` and `compile` calls, predict every ID and filter.
- Find the bug in modified snippets. Seed realistic bugs, such as a missing segment-boundary check, a commit step that allocates, or a `shared_ptr` cycle.

Put the answers at the end.

### `10-mock-interview.md`
A script for a 45-minute mock interview, in four parts: warm-up, deep dive, design extension, and curveballs. Include a scoring rubric.

## Order of work

1. Do all the reading. Then post a short plan in chat: which files you will write, anything surprising, and every design choice whose rationale is undocumented.
2. Write files 00 through 10 in order. After each one, give me a three-line summary in chat.
3. Finish with a self-review pass. Check that:
   - every `file:line` reference resolves;
   - every test name exists (grep for it);
   - every [Doc] citation exists;
   - every number has a source in `results/`;
   - no inference is labeled as [Doc] or [Code].
4. Offer to start a live mock interview:
   - Ask one question at a time and wait for my answer.
   - Grade it as correct, partially correct or wrong, then give the model answer.
   - Raise or lower the difficulty based on how I am doing.
   - Keep a running list of my weak spots in `docs/interview/p2/weak-spots.md`.
