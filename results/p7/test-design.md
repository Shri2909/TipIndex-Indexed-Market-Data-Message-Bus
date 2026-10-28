# P7 independent validation design

The validation sources are `tests/layout/layout_test.cpp` (GoogleTest) and
`tests/layout/layout_cc5.cpp` (standalone campaign executable). This document
describes their design; executed results belong in the campaign JSON and the
coordinated release/sanitizer logs, rather than being inferred from this note.

| Requirement | Independent check |
|---|---|
| V28 | Hand-computed read, useful, waste, touched-store and cost vectors for internal messages, a duplicated basket, a term above the root, a segment-boundary nonmatch and a matched zero-volume node. CC5 compares both production evaluators with a third raw-path/undirected-component evaluator. |
| V29 / CC-5 | ENUM versus MASK-DP feasibility and exact cost for every count from zero through the number of positive nodes; compare every at-most prefix too. Independently evaluate every feasible reconstruction, including its actual materialized count. |
| V30 | Exhaust all cut sets on 64 independently seeded trees of 2–6 nodes. For every integer threshold from zero through total volume, flood-fill components and minimize the valid materialized count. Valid means volume at most the threshold or an actual singleton component. Independently check returned-layout feasibility as well as threshold count equality, nonincreasing counts, hot-node isolation, deterministic node-id ties and equality boundaries. |
| V31 | Baseline cuts only root-child edges; internal messages and positive root-own messages remain represented. Zero-only components do not create stores. One- and two-segment singleton paths are covered. |
| V32 | Reconstruct all three article-example layouts without changing decimal byte labels. Independently allocate exact count curves of the two separate partitions under joint budget four, and show fixed counts `(2,2)` exclude the `(3,1)` optimum. Verify waste `5517460497`, `39881491`, `30029491`, threshold endpoints `28648000` and `38647999`, and the subtree-A consumer's different preference. |
| V39 | Exact rational coefficients **and** consumer weights, equivalent reduced inputs and scale preservation; infinity/sentinel, objective and denominator-scale overflow; uint64 volume overflow even with alpha zero; empty/all-zero and unread-positive trees; zero budget; maximum-uint64 finite plateau; explicit representation, state, work and time statuses. Global checks independently enumerate own-budget allocations for supported selections, verify the unsupported `(10,8,0)` curve's lambda-five bound, retain exact rational scales, handle negative lower bounds/empty forests and withhold certificates if any partition term is incomplete. |

CC5 defaults to **10,000 instances**, each with at most 12 nodes and at most four
consumer classes. Alternating instances use integer or rational nonnegative
coefficients and weights, including zero coefficients and weights. The topology
mix includes random recursive trees, chains and stars. Zero-volume nodes,
all-zero trees and empty trees are present. Node paths are built from their real
parents using slash-separated segments. Classes include exact terms, subtrees,
internal-node terms, above-root subtrees, nonmatching terms and baskets with
duplicates/overlap; reads are checked once per class per materialized store.
The campaign also checks two random cut layouts per instance so evaluator
agreement is not restricted to optimum reconstructions.

The third evaluator deliberately uses segment-vector matching of the retained
raw subscription terms, builds an undirected adjacency list from uncut edges,
and flood-fills components. It does not use production `matches`, prepared
incidence, postorder, owners, ENUM, DP or either production evaluator. It uses
the prepared exact integer coefficient/weight representation so all three costs
are compared at the declared normalized scale. Rational scale correctness is
checked separately against hand-derived fractions in the unit test.

ENUM and MASK-DP each receive explicit limits: 22 enumeration edges, 16 classes,
10,000,000 states, 100,000,000 work units and 60,000 milliseconds per instance.
A cap, incomplete domain, exception, count disagreement or cost disagreement
fails the campaign immediately and preserves the failed zero-based index in the
summary. It does not remove difficult trees or reduce their budgets.

The executable accepts `--instances`, `--seed` and `--output`. The default seed is
`0x5047434335000001`; each case has a reproducible independent `mt19937_64` stream
seeded by the campaign seed XOR `0x9e3779b97f4a7c15 * (index+1)` modulo 2^64.
JSON records requested and completed counts, exact/at-most comparisons,
reconstruction counts, coverage counters, explicit limits and FNV1a64 input and
result hashes. The input hash includes paths, topology, volumes, rational inputs
and terms. The result hash includes exact-count feasibility, evaluated costs,
counts and reconstructed/random cut layouts; reconstruction tie choices are
therefore visible. Timing is intentionally excluded from deterministic hashes.

Example invocation after the coordinated build:

```sh
./build/release/tiplog_layout_cc5 --instances 10000 --seed 0x5047434335000001 --output results/p7/cc5-release.json
```

Acceptance requires a complete campaign with zero unresolved mismatches and
the coordinated release plus ASan/UBSan checks. A short smoke invocation is
useful during integration but does not satisfy CC-5's 10,000-instance gate.
