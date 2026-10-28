# 10 — 45-minute mock interview (P2) and scoring rubric

Use this with a friend, or ask Claude to run it live: one question at a time, waiting for your answer, grading it and escalating. Time each section. The interviewer speaks in *italics*; "Listen for" is what a strong answer contains.

---

## 0. Setup (1 minute)

*"Tell me about a systems project you built. We'll go deep on one component."* Answer with the 60-second pitch from `00-overview.md`, and steer toward Phase 2.

---

## 1. Warm-up (5 minutes)

1. *"What problem does your topic and subscription layer solve?"*
   Listen for: filtering cost for catch-up readers; IDs instead of strings; per-partition filters; the article's context, without claiming to reproduce Aria.
2. *"What's a partition, and why two segments?"*
   Listen for: ancestor at depth min(2, depth); one per symbol; Aria's partitioning (A6); the unit of the per-partition index; per-topic indexing untenable.
3. *"Exact vs Subtree, and give me an edge case."*
   Listen for: segment boundary (`itch/AA` vs `itch/AAPL`); future topics; Subtree includes its root.

---

## 2. Deep dive: the registry (10 minutes)

4. *"Walk me through `intern` for a new four-segment path. What can fail, and what state is left if it does?"*
   Listen for: the plan, stage, reserve, prepare, commit order; all limits checked before any mutation; node handles; strong guarantee; the observer `bad_alloc` test.
   - Push: *"What if the commit itself throws?"* → It can't by construction (reserved capacity, nothrow moves, `noexcept` observer commit); if an assumption broke, `terminate` runs rather than leaving partial state.
5. *"Why not just call `reserve(size+1)` before each `push_back`?"*
   Listen for: exact capacity, so O(n²); the review finding; geometric growth.
6. *"How do subscriptions learn about new topics?"*
   Listen for: hooks on Subtree roots; walking up the ancestors, O(depth); `weak_ptr` slots; serials; RAII handles; de-duplication (and its O(A²) cost).
   - Push: *"Why doesn't the registry own the subscriptions?"* → It would create cycles and keep them alive forever.
7. *"There's a raw `Registry*` in the subscription. Convince me it's safe."*
   Listen for: `weak_ptr<Lifetime>` plus the `alive_` flag; **the retained-anchor bug**; registry non-movable; ASan test.
   - Push: *"Why not `shared_ptr<Registry>`?"* → Subscriptions would extend the registry's life; I chose "inert after the registry dies".

---

## 3. Deep dive: subscriptions and the oracle (10 minutes)

8. *"Normalize this on the whiteboard: `{Subtree a, Subtree a-foo, Subtree a/b, Exact a, Exact a-foo/x}`."*
   Expected: `{Subtree a, Subtree a-foo}`. Then: *"Why can't you just sweep the sorted list?"* → `-` sorts before `/`, so tree order isn't byte order.
9. *"What did you change in P6, and how did you make sure you didn't change the semantics?"*
   Listen for: O(n²) to hash lookups of each term's ancestors; the 100k-partition timeout; the old algorithm kept as the test reference; 512 random specs; idempotence; CC-2, RC3 and F3 re-run on the final source.
10. *"What does a compiled filter look like, and what does matching cost on the hot path?"*
    Listen for: a sorted vector of `{partition, all, bits}`; binary search plus a bit test; `all` short-circuits future topics; **the atomics in `weak_ptr::lock()` per record** (unmeasured); Indexed vs Scan usage.
11. *"Your oracle reports FellBehind even though the matching message is still in the ring. Bug or feature?"*
    Listen for: conservative by design; one rule across modes (Q7); checked before touching memory; the cost (unnecessary failures for narrow, slow readers); what a precise rule would require.
12. *"Why does a full budget return More even if there's nothing left?"*
    Listen for: no look-ahead, so checkpoints are identical across modes; the next positive call establishes Done; completion is checked before expiry.

---

## 4. Design extension (12 minutes): pick one or two

13. *"Make this registry and filter layer safe for 8 reader threads and 1 publisher."*
    A strong answer covers:
    - **What breaks:** vector reallocation invalidating spans, hash-map mutation during lookups, the race between hook registration and the initial scan, filter swaps racing with readers.
    - **Design:** a single writer for intern; topics in stable chunked storage (IDs never move); readers on immutable snapshots published through an atomic pointer, reclaimed with epochs or RCU; subscriptions **pull** new topics from an append-only log at batch start; hooks (if kept) registered before scanning.
    - **Cost:** atomic loads per batch, not per record.
14. *"Support `itch/*/trade` subscriptions."*
    Listen for: inherently cross-partition, so effectively wide; the hook at the fixed prefix; per-partition compilation; Auto will choose Scan; the oracle and reference matcher must be extended independently.
15. *"We have 1M subscribers and 10k new topics a second at the open. What hurts?"*
    Listen for: per-subscription memory; O(A²) de-duplication on hot roots; push hooks; sharing identical compiled specs; pull model; inverted index for fan-out.

---

## 5. Curveballs (5 minutes): rapid fire, 30 seconds each

16. *"What's the partition of `itch`?"* → Its own, containing only `itch`.
17. *"Is `compile` transactional?"* → Partly: validation comes first, so malformed specs change nothing, but a limit failure on a later root can leave earlier roots interned. Basic guarantee for registry contents.
18. *"Why u32 for partitions when ITCH has 8,907?"* → T3 needs 100,000; `UINT32_MAX` is P4's sentinel.
19. *"Why not `uniform_int_distribution` in the driver?"* → It is implementation-defined across standard libraries; raw engine output is portable; the modulo bias is negligible and disclaimed.
20. *"What's one thing your tests can't catch?"* → A spec bug shared by oracle and engine; performance; concurrency.
21. *"Where did Jane Street's article end and your design begin?"* → Article: hierarchy, subtree subscriptions, two-segment partitions, heap merge. Mine: normalization, local-ID bitsets, transactional hooks, oracle, driver.

---

## 6. Close (2 minutes)

22. *"What would you do differently?"* Pick one or two of: the handle/ID ownership model; pull-based topic log; hoisting the lifetime check; sort-once filter construction. Say they're **unmeasured** and how you'd measure them.
23. *"Questions for me?"* Have one ready, e.g. *"How does your bus handle subscription churn at the open?"*

---

## Scoring rubric (score each 1–4)

| Dimension | 1: weak | 2: borderline | 3: solid | 4: strong |
|---|---|---|---|---|
| **Correctness** | Wrong facts about the code (e.g. "Subtree uses `starts_with`") | Mostly right, shaky on edges | Accurate, including edge cases | Accurate, and spots subtle edges unprompted (lexical interleaving, exact-budget completion) |
| **Depth** | Describes *what* only | Some *why* | *Why* plus costs | *Why*, costs, alternatives, and when they'd win |
| **C++ fluency** | Vague on ownership and exceptions | Knows the terms | Explains RAII, guarantees, `weak_ptr`, transparent lookup in context | Explains node handles, nothrow-move requirements, init-order traps, atomics cost |
| **Trade-off reasoning** | Defends everything as best | Names an alternative | Compares two with a criterion | Quantifies (memory, complexity) and picks per scenario |
| **Testing mindset** | "I wrote unit tests" | Names test types | Independent oracle, fault injection, reduced limits | Explains what the tests *can't* catch, and the evidence trail |
| **Honesty and ownership** | Overclaims (speedups, "I wrote it all") | Hedges vaguely | Clear about measured vs inferred | Precise about AI assistance, what was verified, and limitations |
| **Communication** | Rambling, no structure | Understandable | Structured, uses examples | Leads with the answer, then layers detail, and draws diagrams |

**Target:** 3 or more on every dimension before a real interview. Write anything below 3 in `weak-spots.md` with the question number, then redo the matching guide section and drill.

## After each mock

1. Note which questions took longer than 60 seconds.
2. Redo the matching `09-exercises.md` drill from memory.
3. Re-run the mock a few days later with the questions shuffled, and push harder on the weakest dimension.
