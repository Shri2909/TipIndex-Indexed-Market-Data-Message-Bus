# P7 bounded preparation and ST-09 — 2026-10-19

**Preparation only.** P6 execution remains in progress. No optimizer code,
optimizer test or optimizer study was executed for this note. P7 implementation
starts after P6's gate under the user's joint P6→P7→P8 authorization.

## Original material actually inspected

- [Buchin & Selbach, Partitioning algorithms for weighted trees and cactus
  graphs](https://arxiv.org/abs/2001.00204v3), **arXiv2001.00204v3,
  2022-03-02**. Inspected the original abstract and §1.1 Related work, PDF
  pages1–3 through Table1, plus metadata/version history, on2026-10-19.
  The HTML full-text endpoint failed; the versioned original PDF was available.
  No full-paper reading or implementation-code reuse is claimed.
- S34 surveys bounded connected partitions, including the linear tree
  minimum-cluster-count case and different objectives with harder complexity.
  Those results do not prove M-store's exactness or hardness. The project's
  multiplier DP and capped-convolution argument are independent reasoning.
- S33 Kundu–Misra remains a bibliographic/publisher-abstract/secondary reading;
  its full original text is still unread. The project's stated threshold greedy
  needs its own exhaustive count validation. S35 and S36 retain their previously
  recorded reading limits; no new full-text inspection is claimed.
- Read ARCHITECTURE §§6 and13, VALIDATION V28–V32/V39 and CC-5,
  IMPLEMENTATION P7, STUDY_PLAN ST-09, RESEARCH §§1.3/3.7/4/6 and the relevant
  review/finding rows. These are approved project requirements, not new external
  claims. No dependency, model, budget, scope or acceptance threshold changes.

## MASK-DP audit

The mask-pricing relaxation is valid for the approved **nonnegative** full-window
model: each connected component chooses Λ containing its true read classes.
Its relaxed price is at least its true price because f, α and β are nonnegative;
choosing the exact read mask attains equality. Local checks m(v)⊆Λ enforce this
containment. For zero-volume nodes m(v) is empty even if a subscription matches
that path. An unread but positive-volume store is still materialized and pays γ.

The open-state value already charges αF(Λ) times all open bytes. Joining a child
requires **the same Λ**, and closing it charges βF(Λ)+γ **only when z=1**.
The state needs both the count of closed materialized stores and z. Dropping z,
charging zero-volume residual components, or counting every cut as a store
breaks the contract. Finalize the root before constructing the exact-count curve.
Keep exact count c(k) separate from its at-most-K prefix minimum; global penalties
must multiply the **actual materialized count**, not the nominal budget index.

The approved O(|V|K2^b) time bound depends on capped convolutions, precomputed F,
bounded masks and constant-size z. For subtree merge sizes a,c, the specified
potential φ(s)=s² for s≤K and2Ks−K² otherwise bounds the product of capped
sizes and telescopes. A generic loop over every k1,k2 up to K at every node
without subtree caps would instead retain an unnecessary O(|V|K²2^b) bound.
Backpointers must include child-stage and the child's closed/open state; the
total number of child stages is O(|V|), so storing capped state argmins remains
O(|V|K2^b). Reconstruction must be independently re-evaluated, not trusted from
the DP objective alone.

Representation checks precede allocation and shifts: practical b/state limits,
1≪b mask safety, K/node caps, state-size products and reconstruction memory.
Normalize exact rationals (including W3's1/10), check denominator LCM/scaled
products/accumulations, reserve an infinity sentinel, and reject overflow before
performing the overflowing operation. A uint64 volume sum can overflow even
when α=0; reject it independently. `unsigned __int128` is the declared compiler
extension, not a portable ISO C++20 type. Floating input must never silently
become an exact objective.

ST-09 three-node exercise: chain r→a→b with w=(1,2,3), m=({1},{2},{1}),
f1=f2=1, α=1, β=γ=0 has four cut-set costs12,11,9,6. Its exact-count curve
is c(1)=12,c(2)=9,c(3)=6. At b, D(0,{1},1)=3 and D(0,{1,2},1)=6; at a,
the uncut state is D(0,{1,2},1)=10, while cutting b yields
D(1,{2},1)=5 and D(1,{1,2},1)=7. Closing the root reproduces the four
enumerated costs. This is hand reasoning, not a passed executable test.

## Threshold and empty-state traps

- Hot means **w>T**, not w≥T. Isolate every hot node from parent and children;
  then process the remaining forest, cutting largest residual children first
  with deterministic node-id ties. Zero-only stores do not count.
- Validate the threshold solver against independent exhaustive partitions for
  its own problem P_T, including the hot-singleton exemption, before relying on
  count(T) monotonicity. P_T exactness does not make the heuristic exact for J.
- Search integer T in **[0,W_total]**. The one-store plateau otherwise has no
  largest threshold. H-KM-min is the first count≤K threshold; H-KM-max is the
  last threshold with that attained count. Handle T=0 and equality boundaries.
- Empty/all-zero input: zero materialized stores and zero cost. Positive total
  volume with K=0 is infeasible. An unread positive-volume partition is not an
  empty tree. A forest with q positive partitions needs at least q stores.
- Use overflow-safe upper-midpoint arithmetic for a maximum uint64 threshold
  interval; `(lo+hi)/2` and `lo+(hi-lo+1)/2` are both unsafe at some limits.

## Global γ sweep and claims

Per-partition exact-count curves are combined with a **nonnegative** additional
penalty λ. A minimizer of Σ[c_p(k)+λk] is optimal for its own at-most total
count. The sweep exposes supported points, not every integer budget. For an
unsupported budget B, save the best evaluated feasible layout and the certified
bound Σmin_k(c_p(k)+λk)−λB, or state that no feasible evaluated point exists.

Example: curve c(1)=10,c(2)=8,c(3)=0 has no λ≥0 making k=2 a penalized
minimizer: it would require both λ≤2 and λ≥8. At B=2 the λ=5 bound is5,
below c(2)=8. This illustrates the unsupported-point limitation; it is independent
arithmetic, not a claim about the article or a study result. Negative penalties
fail the own-at-most-budget statement: for c(1)=1,c(2)=2, λ=−2 selects k=2
although k=1 is cheaper at budget2.

Both global claims require certified terms for **every** partition. A timed-out
feasible incumbent is an upper bound and cannot be substituted for a lower bound.
Incomplete curves do not justify a global certificate. Exact same-budget gaps
also need identical α,β,γ, scaled weights, tree/window and feasible count domain.

## Worked example: exact tree, forest and arithmetic

Use the saved decimal labels, without padding invented messages:

```
L(0)                    R(0)
├─ A(28,500,000)         ├─ R1(0): c1(197), c2(29,300)
│  ├─ a1(10,000,000)     └─ R2(0): d1(10,000), d2(421,000)
│  └─ a2(2,720,000,000)
└─ b(148,000)
```

L and R are **separate partitions**, with a **joint total budget4** for this
worked example. An artificial zero-volume super-root must not permit stores to
cross L↔R; force its boundary edges or solve independent curves and allocate
the total budget. L2's baseline-matched per-partition budgets are a different
comparison. Imposing baseline counts(2,2) would exclude the example optimum,
which uses counts(3,1).

Total useful volume is2,759,108,497 B. For uniform exact reads and β=γ=0,
each store with q positive-volume exact topics contributes waste(q−1)W.

| Layout | L stores | R stores | Waste B | Total read B |
|---|---|---|---:|---:|
| Baseline | {A,a1,a2}; {L,b} | {R1,c1,c2}; {R,R2,d1,d2} | 5,517,460,497 | 8,276,568,994 |
| Figure / H-KM-max | {a2}; {A,a1}; {L,b} | {R,R1,R2,c1,c2,d1,d2} | 39,881,491 | 2,798,989,988 |
| Optimum / H-KM-min | {a2}; {a1}; {L,A,b} | {R,R1,R2,c1,c2,d1,d2} | 30,029,491 | 2,789,137,988 |

Zero nodes can be attached differently without changing materialized-store
content/cost; do not require identical zero-node placement from independent
reconstruction ties. The baseline waste is5,517,000,000+29,497+431,000.
The figure waste is38,500,000+3×460,497. The optimum waste is
28,648,000+3×460,497. Subtree A reads2,758,500,000 B in2 figure stores and
2,758,648,000 B in3 optimum stores, so the latter wastes148,000 B for that
different consumer.

Hand threshold runs: T=30,000,000 produces the optimum arrangement;
T=38,600,000 produces the figure arrangement. The four-store threshold plateau
is [28,648,000,38,648,000) in integer bytes, so T_min=28,648,000 and
T_max=38,647,999. These endpoints need executable V32 regression checks.

## Required validation and study guardrails

| Requirement | Implementation/check target | Required executed evidence (still pending) |
|---|---|---|
| V28 | Direct component formula vs independently materialized class reads; baskets/above-root/internal/zero nodes | Random evaluator equality, release and ASan/UBSan |
| V29 / CC-5 | Independent Gray-code ENUM vs MASK-DP, every k; random α/β/γ and masks/terms | ≥10,000 random trees (|V|≤12,b≤4), zero exact-integer mismatches |
| V30 | Threshold count vs independent exhaustive P_T minimum; all small thresholds | Monotonic count and deterministic ties; hot/equal/zero cases |
| V31 | First-three-segment baseline with shorter paths/internal messages | Materialized-count/content checks; no phantom zero-volume stores |
| V32 | Two-partition example above | All three exact waste totals, threshold endpoints and reconstructed costs |
| V39 | Rational scale and overflow, empty/K=0, finite plateaus, λ bounds, solver limits | Positive/negative boundary cases; no global certificate from an incomplete term |
| L2/L3/L5 | Save limits before studies, solve identical objectives/budgets | Per-workload solved counts/fractions by partitions, bytes and active class-weight; timeout/state-limit/heuristic-only explicit |
| L4 | Same worked example | Raw table and F16/example output from actual executable evaluation |

P1 topic CSV has `payload_bytes`, `framed_bytes` and `record_bytes`. M-store
requires a declared record-framing-inclusive basis: use `record_bytes`
consistently for real topic volumes, and label these modeled bytes rather than
measured physical store-pack I/O. Keep the article example's labels unchanged.
H-flat's baseline exact-read waste remains exactly zero; no positive gain can
be invented for that case. Whole-window requests stay in scope; partial-window
frequency scaling would incorrectly scale fixed per-read β.

Coverage denominators must be explicit per W0–W3. Byte coverage uses the same
framing basis as J; weight coverage should identify its denominator as the sum
of active **per-partition** class weights, so a multi-symbol basket is not
misreported as a fraction of distinct global requests. Zero-weight classes may
be removed, and identical incidence classes may have their rational weights
combined, only with preserved costs and recorded before/after b. Related-paper
hardness results and the article's unspecified greedy procedure confer no extra
exactness or Aria-reproduction claim.
