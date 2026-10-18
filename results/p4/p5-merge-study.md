# Read-only P5 merge study while the P4 gate runs

Access date: **2026-10-18 (Asia/Kolkata)**. This is source/design preparation,
not P5 implementation or acceptance. The P4 production/test source freeze is
unchanged. P5 implementation starts only after the P4 gate passes, within the
user's existing joint P1–P5 authorization.

## Original material actually inspected

- S18 [Peter Sanders, *Fast Priority Queues for Cached Memory*](https://ae.iti.kit.edu/documents/people/sanders/papers/spqjea.pdf):
  original PDF extracted text, **§2's loser-tree paragraph, PDF page 5**, and
  **complete Appendix A.5, PDF pages 23–24**. Also inspected **Appendix A.2,
  PDF page 20**, for the discussion of child-group alignment. These PDF page
  numbers use the printed pages, which match the one-based PDF positions.
  The screenshot endpoint failed; the relevant original extracted text was
  available and inspected. This is targeted reading, not a complete-paper claim.
  No repository revision applies to this published paper, and no source code
  was copied.
- Re-read the approved local ARCHITECTURE §5.7 and VALIDATION §6.1, and STUDY
  ST-06's specified scope. The contracts below are our independent approved
  design, informed by the paper's tournament description.
- S23/S49 discussions were **not reopened in this study**. Their prior targeted
  original-message reading and limitations remain in
  [P1 source review](../p1/review-sources.md). In particular, neither an adopted
  PostgreSQL implementation nor inaccessible ACM full text is claimed read or
  reused.

Jane Street's published partition/block-pool observations remain distinct from
our kernel layouts. These notes do not reconstruct unpublished Aria internals
or transfer a published speedup to this project.

## Tournament initialization and replay

A tournament can be initialized independently from leaf keys: each internal
match retains its losing packed key and sends the smaller key upward. The
final winner is stored separately at node 0. Replacing the current winner
replays its **previous leaf's fixed path** to the root, comparing against the
stored losers. If the candidate's identity changes during a comparison, the
traversal still follows that original update path. This supplies the intended
loser-tree invariant without copying the paper's C++ implementation.

Our approved packed key contains both logical position and cursor ID. Therefore
winner/loser identity travels inside the compared word; a separate copied leaf
index is unnecessary for ordinary valid keys. Initialization must preserve the
original cursor-to-leaf mapping even if some inputs are initially exhausted.
The update path must use the old valid winner ID before replacing its key with
the exhaustion sentinel.

For arbitrary k, round the tournament leaf count up to the next power of two
and pad absent/exhausted leaves with `UINT64_MAX`. Empty input must construct an
empty kernel; k = 1 requires no internal replay comparisons. Track exhaustion
without extracting a usable cursor ID from the sentinel. The approved limit
is k ≤ 65,535 with IDs 0…65,534; the all-ones ID belongs to the exhaustion sentinel.
Check positions/boundaries below 2^51 before packing and preserve the existing
exclusive position bound. Unit tests must include k = 0 / k = 1, non-power-of-two k,
initially empty lists, staggered exhaustion, skew and near-limit values.

The tournament account is informed by the targeted paper sections. Its
bottom-up initialization formulation, packed words, padding and limit/sentinel
contracts are independent project decisions. No conclusion about modern CPU
performance follows.

## Quad child-group geometry

For an ordinary zero-based four-ary heap, logical node i has children
`4i+1 … 4i+4`. With 8-byte keys and a 64-byte aligned physical base, the first
child's offset modulo 64 is 8 or 40. The latter 32-byte group extends through byte71,
so base alignment alone cannot prevent a cache-line crossing.

Put **three u64 padding slots** before the logical root and retain a 64-byte
aligned physical allocation. The first child's physical byte offset becomes
`(4i+1+3)*8 = 32*(i+1)`. Each four-child group then occupies one aligned 32-byte
half of a 64-byte line. Its addresses are either line offsets 0…31 or 32…63.
This is a geometrical argument for an explicitly represented padded variant,
not evidence of lower runtime, fewer measured misses or a universally better
layout. Capacity arithmetic must include the three padding words, and allocator
alignment must be verified rather than inferred from a normal vector.

## Hypotheses and later evidence

The four Tier B kernels remain StdPQ pop+push, inline early-exit BinHeap,
explicitly laid-out Quad and a padded loser tree. Galloping remains Tier C and
is excluded. Preserve a fair early-exit heap baseline: a long run can leave a
replacement at the root with constant work, while a fixed tournament path still
has logarithmic depth. No winner is assumed.

Predictable loser-tree addresses and the Quad layout do not prove branch-free
machine code or actual cache behavior. Before machine-code claims, inspect
representative generated inner loops from the actual release compiler/build.
P5 pilot comparisons must use identical lists and output digests, setup outside
timing, all output contributing to the protected sink, and the required isolated
measurement protocol. Hardware-counter denial remains a measured environment
constraint; simulated Cachegrind results must carry that label. P6 calibration
and broader experiment conclusions remain later work.
