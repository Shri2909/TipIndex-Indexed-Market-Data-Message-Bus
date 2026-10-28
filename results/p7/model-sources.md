# P7 model, evaluator and threshold implementation traceability

Implementation scope: `src/tiplog/layout/model.cpp`; accepted P0–P6 code is
unchanged by this task. This note records implementation reasoning and reused
research, not an executed validation gate.

## Requirements and source limits

- Approved project contract: `docs/plan/ARCHITECTURE.md` §§6 and 13,
  `docs/plan/VALIDATION_PLAN.md` V28, V30, V31 and V39, and the P7 API in
  `src/tiplog/layout/model.hpp`.
- Reused targeted ST-09 study: `results/p6/p7-study.md`, including its independent
  exact-rational, zero-volume, threshold-endpoint and worked-example reasoning.
  No new external-source reading or new dependency was needed for this model
  implementation. Its original-source reading limits remain unchanged.
- S33 Kundu–Misra's full original text remains unread. Threshold code follows
  the approved project pseudocode, independently implemented with deterministic
  node-ID ties. It is a heuristic for M-store's cost objective; its separate
  minimum-count threshold claim requires V30's exhaustive executable check.
  There is no claim to reproduce unavailable Aria internals or an unspecified
  article algorithm, and no external implementation code was reused.

## Implementation decisions and findings

`prepare` retains the raw input, validates one rooted tree with node zero as
root, unique valid slash paths and immediate topic-parent ancestry, and checks
the uint64 byte sum even when alpha is zero. It preserves all input classes
one-to-one, including zero-weight classes. Incidence vectors have no 64-class
mask ceiling. Matched zero-volume nodes have empty incidence and never cause a
read or materialize a store. An unread positive-volume store still pays gamma.

Every rational is reduced before denominator LCMs. Let `A` be the common
coefficient denominator and `F` the common class-weight denominator. Stored
alpha/beta use scale `A`, weights use `F`, gamma uses `A*F`, and the public
objective scale is `A*F`. Thus the integer objective is exactly the rational
objective times that scale. All LCMs, scaled values, arithmetic and the bound
`(alpha*total_bytes + beta*node_count)*sum_weights + gamma*node_count` are checked
before solving. The all-one uint128 value is reserved for infinity; finite
arithmetic cannot produce or consume it. Denominator zero, negative/nondecimal
integer text, uint64 volume overflow and cost/scale overflow throw exceptions.
Signed/rational CLI syntax is parsed by the caller into the unsigned Rational
API; `parse_cost` accepts unsigned decimal integer text only.

The formula evaluator walks prepared parent-before-child order, merges
precomputed class incidence per component, and charges each component once.
The independent simulator instead follows raw parent links separately for
each positive-volume record, materializes record lists, and matches raw terms
using segment comparisons. It never calls the optimized matcher or uses the
formula evaluator's component/incidence construction. It computes objective
from each class's total bytes and store touches, plus the materialized-store
gamma term. Both return per-class read/useful/waste bytes and touches.

The baseline cuts root-to-child edges. Threshold hot means `bytes > T` and
isolates both parent and child edges; remaining components cut the largest
positive child residual first, using the lowest child node ID for equal
residuals. Only positive-volume components count. `km_min` finds the first
feasible threshold in `[0,total_bytes]`; `km_max` finds the last threshold at
that attained count. The upper midpoint uses `lower + difference/2 +
difference%2`, which remains safe when total bytes equals uint64 maximum.
Empty/all-zero input with budget zero is feasible; positive bytes with budget
zero return an explicit infeasible result.

## Complexity accounting

Let n be nodes, b classes, I the number of positive-node/class incidences, h
tree height, and d(v) child counts. Matching costs additionally depend on the
number and length of raw terms.

- Preparation scans raw terms per positive node/class, builds O(n+I+b) stored
  metadata, and performs checked scale arithmetic. Path uniqueness uses a hash
  table with its usual expected-time qualification.
- Formula evaluation uses O(n+I+b) auxiliary/output memory and
  O(n+b+I log(max(2,I))) time as a conservative bound for sorting per-component
  incidence. It does not claim constant-time unbounded class-mask operations.
- Materialized simulation intentionally trades speed for independence: O(nh)
  raw parent-walk work plus per-class store/record/term scans; O(n+b) auxiliary
  memory beyond its output. This is not the evaluator used for timed solving.
- One threshold call takes O(n + sum_v d(v) log(max(2,d(v)))) time and O(n)
  memory. Each bisection has at most 64 iterations; `km_max` performs both
  endpoint searches, plus final construction/evaluation. The final formula
  evaluation has its own incidence-dependent cost described above.

## Validation handoff

| Task/check | Required evidence | Status in this implementation task |
|---|---|---|
| V28 evaluator agreement | Random layouts with exact/subtree/basket/above-root/internal/zero cases; every returned metric agrees | Test implementation and execution delegated to P7 integration |
| V30 threshold minimum count | Independent exhaustive connected partitions, hot-singleton exemption, monotonicity and deterministic ties | Test implementation and execution delegated to P7 integration |
| V31 baseline | Root-child boundaries, short root paths, internal messages, no phantom zero stores | Test implementation and execution delegated to P7 integration |
| V39 arithmetic/empty/endpoints | Exact rational objective, invalid inputs, reserved infinity/LCM/product/sum boundaries, uint64-max threshold midpoint, K=0 | Test implementation and execution delegated to P7 integration |
| V32/ST-09 worked example | Saved separate-partition totals and finite threshold endpoints | Executable regression belongs to P7 integration; reused study contains hand calculations only |

No build or test was run by the model implementation task: the root agent owns
CMake/build/integration. Passed checks must be established by the root's saved
P7 validation evidence; this note does not mark pending checks as passed.

## Global penalty and budget-bound follow-up

Authorized follow-up added `src/tiplog/layout/global.hpp` and `global.cpp` under
ARCHITECTURE §6.5 / V39. `CostCurve` uses actual counts; a complete-domain
certificate requires both the caller's solved/full-domain certification flag
and exactly `maximum_count+1` entries. Infinity denotes proven infeasibility
only for such a certified complete curve; otherwise it may be unknown.
Truncated or extra-length curves can yield known feasible incumbents, labeled
`feasible_uncertified`; extra entries beyond the declared domain are ignored.
One incomplete term withholds every global certificate and lower bound.
The API's `infeasible` status with `certified=false` means that no evaluated
feasible combination is known; it does not prove infeasibility for incomplete
curves. Reporting must preserve this distinction.

`penalized` reduces the nonnegative rational penalty, computes the checked LCM
of all curve scales and its denominator, and minimizes each scaled
`c_p(k)+lambda*k`. Equal prices choose the smallest actual count. Summed costs,
penalties, scales and uint64 store counts are checked. A zero curve scale or
zero penalty denominator is invalid. Signed CLI text validation remains with
the caller because Rational's fields are unsigned.

For complete terms only, `budget_bound` returns exactly
`sum_p min_k(c_p(k)+lambda*k) - lambda*B`, represented by a sign and unsigned
magnitude at the common scale. It compares and subtracts unsigned terms rather
than converting to signed128, so a finite negative magnitude can use the full
finite unsigned range. There is no general knapsack allocator, certificate from
a timed-out incumbent, claim that all budgets are supported, or cross-partition
store construction. An empty forest has cost/count zero; its bound is the same
formula, including `-lambda*B` when that expression is negative.

The implementation scans each declared available count once and uses O(P)
additional memory for the selected counts, where P is the number of partitions;
integer LCM/arithmetic costs are explicit and bounded by the 128-bit domain.
The hand-derived unsupported curve `(10,8,0)` at counts `(1,2,3)`, penalty 5,
budget 2 gives bound 5. Executable checks for this example, scale normalization,
missing certification, overflow, ties and empty forests are assigned to the P7
tests/integration owners; this follow-up did not build or run them.
