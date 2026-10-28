# P7 exact solver implementation and provenance

The implementations in `src/tiplog/layout/exact.cpp` follow the approved project
contracts in `docs/plan/ARCHITECTURE.md` §§6.3–6.5 and the full
`results/p6/p7-study.md` audit. The multiplier-mask recurrence and capped
convolution argument are independent project reasoning. No implementation or
recurrence was copied from Aria, Kundu–Misra, or Buchin–Selbach; the original-paper
reading limits recorded in the P6 note remain unchanged. This note records source
traceability and code behavior, not a claim that validation has passed.

ENUM visits all parent-edge cut sets in reflected Gray-code order. Each candidate
builds connectivity independently with disjoint sets, totals component bytes,
unions positive-node consumer incidences, and prices only materialized
components. Its sorted incidence representation supports arbitrary prepared class
counts, including baskets and more than 64 classes. It shares neither DP masks
nor either evaluator's component/read helper. Exact checked cost arithmetic and
the prepared incidence/weight contract are shared inputs.

MASK-DP implements the documented closed-count `k`, multiplier `Lambda`, and
positive-open-component flag `z` recurrence. Positive nodes alone constrain the
local mask. Joining uses the same multiplier; closing charges `beta*F+gamma`
only for `z=1`. Child stages retain their argmin decisions and the complete child
state. Their count arrays are capped by the processed positive-node cardinality
and the requested budget, including during joins and cuts. Subset weights and
byte/closing prices are precomputed. Root finalization constructs an exact
materialized-count curve. Every reconstructed curve entry is checked with the
independent component-formula evaluator before the solver can report `solved`.
External exact/evaluator tests additionally check raw materialization; its
per-record parent walks and raw term matching are not repeated inside the
bounded solver.

Both curves stop at `min(maximum_stores, positive_nodes)`: counts above that are
provably infeasible and need no padded allocation. All-zero/empty inputs return
the zero-store, zero-cost curve; a positive tree with budget zero is infeasible.
`complete_domain` is true only after solving every count through
`positive_nodes`. `at_most` accepts only a `solved` result and chooses minimum
objective, then the fewest actual stores; strict improvement and fixed iteration
orders preserve deterministic cut ties within each solver. Zero-node placement
need not match between the independent solvers.

Representation checks precede exponential shifts, state products, and table
allocation. DP masks use at most 31 class bits and also honor `dp_max_classes`;
ENUM's Gray-code edge word uses fewer than 64 bits and honors `enum_max_edges`.
The defaults are 22 ENUM edges, 16 DP classes, 2,000,000 states, 2,000,000 work
units, and 500 ms. ENUM preflights its candidate count as states and its
`candidates*(nodes+positive incidences+1)` node/incidence visits as work. DP states
count all retained child-stage table entries (including unreachable entries);
work counts preprocessing scans, candidate state/transition inspections, and
reconstruction steps. The elapsed clock is an additional cap, including after
independent reconstruction checks. Trivial mathematical outcomes require no
search and are returned before execution caps.

An edge/class representation failure reports `representation_limit`; a state or
work cap reports `state_limit`; elapsed exhaustion reports `timeout`. Checked
arithmetic or allocation representation failures also report a limit. Any
already saved candidate layouts remain feasible incumbents inside a non-solved
result, without certified optimality. Such a result cannot produce an exact
same-budget gap or a global lower-bound certificate; `at_most` deliberately
returns no certified optimum for it. Actual build, random equivalence,
sanitizer, coverage, and study evidence belong to the root-owned integration
artifacts.
