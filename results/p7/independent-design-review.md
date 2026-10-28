# P7 independent implementation review

Review snapshot: 2026-10-25 14:10 UTC. This is a source and saved-evidence audit performed
while the full study campaign was in progress. It is not the P7 execution gate.
No build, test, optimizer campaign, or timing workload was run by this reviewer.
The reviewer made no production-source edits. A delegated read-only reviewer
independently inspected the Python input/analysis/global-study path; findings
were checked against the cited source and sent to the root implementation owner.

## Material actually inspected

- Complete `src/tiplog/layout/model.hpp` (64 lines), `model.cpp` (479),
  `exact.hpp` (27), `exact.cpp` (444), `global.hpp` (35), and `global.cpp` (117).
- Complete `tools/tiplog_layout/main.cpp` (519 lines).
- Complete `py/tiplog_py/layout/inputs.py` (430 lines), `analyze.py` (initially
  631 lines, then 640 after focused inspection of the subsequent cohort/output
  changes), and `global_study.py` (initially 179 lines, then 194 after the
  output-completeness correction). The delegated Python review covered all
  three original files; the principal reviewer also inspected the relevant
  input construction, accounting, cohort, certificate, and timing paths.
- Complete `tests/layout/layout_test.cpp` (564 lines) and
  `tests/layout/layout_cc5.cpp` (403 lines), including raw matching, undirected
  component oracles, exact-count comparisons, reconstruction validation,
  threshold enumeration, rational arithmetic, and global-bound cases.
- Approved `docs/plan/ARCHITECTURE.md` section 6 (including arithmetic,
  threshold endpoints, and global-certificate preconditions), workload
  definitions in section 2.3, `VALIDATION_PLAN.md` CC-5, V28–V32, V39,
  L2–L5, metric definitions, and the optimizer coverage paragraph;
  `IMPLEMENTATION_PLAN.md` P7 requirements and definition of done.
- `results/p6/p7-study.md`, `results/p7/protocol.json`, `model-sources.md`,
  `exact-sources.md`, `analysis-design.md`, `test-design.md`,
  `p7-source-map.md`, and `timing-clarification.md`.
- Saved `unit-release-20261025T083504.089969Z.log` and
  `unit-asan-ubsan-outside-ptrace-20261025T083520.487603Z.log` endings;
  complete `cc5-release.json` and `cc5-asan-ubsan.json` summaries.

No external paper was newly opened for this audit. The reading limits recorded
in `results/p6/p7-study.md` remain unchanged: S33 full original text unread;
S34 original abstract and section 1.1/PDF pages 1–3 through Table 1 inspected
in the earlier study; S35/S36 retain their recorded limited reading. The
review does not attribute the project's exactness or complexity argument to
unread paper text or claim to reproduce unavailable Aria code.

## Findings and corrections

1. **Global study output completeness needed an explicit check.** The original
   `global_study.py::execute` accepted successful empty/truncated JSONL;
   `run` validated only rows present. Consequently, 24 input strata could be
   marked passed without all required multiplier points and budget-bound
   observations. This was a validation hole, not an observed wrong C++ result.
   The root owner added an exact expected identity set and cardinality check
   for `(type, lambda, budget)`, rejecting missing/duplicate/unknown output
   rows. Follow-up inspection confirms `validate_observation_rows` is called
   for both the initial discovery sweep and final sweep, before initial
   supported counts extend the final budget set. This source finding is
   closed; runtime validation remains part of the root-owned integration.

2. **New exact-cohort aggregates initially included misleading empty totals.**
   A synthetic baseline may exceed its requested budget. The first cohort
   implementation retained such rows while summing only feasible metrics,
   potentially exporting objective/read/store totals of zero for an entirely
   infeasible baseline. The corrected source selects the same exact-solved
   cases on which every requested heuristic is feasible and labels that scope.
   Cohort consumer output now projects only fields populated by its accumulator
   and reports `class_observations`; unused zero-valued objective/store/volume
   fields are removed. Empty runtime distributions now include null p25/p75
   keys. These corrections were checked by source inspection; executed fixture
   evidence remains the root owner's integration responsibility.

3. **The 4 KiB worst-ratio convention must remain explicit in reporting.**
   Current `analyze.py` computes the raw maximum `R/U` over positive-weight,
   positive-useful classes; its `floor4096` maximum includes only classes with
   `U >= 4096`. This is a useful-byte eligibility cutoff. It does not compute
   `R/max(U,4096)`. The approved prose says “useful-bytes floor” without an
   equation, so this is a reporting-definition clarification, not a confirmed
   model or arithmetic bug. Reports/figure labels should identify the cutoff.

No current defect was identified in the inspected C++ model arithmetic,
materialized-store counting, DP recurrence/reconstruction, threshold bisection,
or complete-curve Lagrangian calculation. This conclusion is limited to the
inspected implementation and saved validation, not a proof of arbitrary
unexecuted inputs or of all study/report claims.

The final reviewed reporting-source SHA-256 identities are:

| File | SHA-256 |
|---|---|
| `py/tiplog_py/layout/analyze.py` | `41cca8adacb4838285c15075c90886c5694a8e2919d9e1fe3dd9fe40b26a2a5a` |
| `py/tiplog_py/layout/global_study.py` | `aa81fff240b471d05d6d9f8a59db2c9121dec28ee48ce02cca6d66861de24d49` |
| `src/tiplog/layout/model.cpp` | `43f93d00faa010bffdce5f95895a9b91ce27dd66d032c32c315717c0d877cd2a` |
| `src/tiplog/layout/exact.cpp` | `9a099018607b8706de3de2ec1e189aadb17025a842fa378596a1a55b068c26ff` |
| `src/tiplog/layout/global.cpp` | `00bc7c4cc1f964da64605de7a78b8d66d2b72df92d09132ddfb5d3bd31ae6fc0` |
| `tools/tiplog_layout/main.cpp` | `f4a8769795d5a341e5cb8122d99e88f17ccbc22e25e2d61791a19a2188b34517` |
| `py/tiplog_py/layout/inputs.py` | `6b56c82534087c4a1a5837acfa36d8ea1a372c84a098fcaa85364e7c0528b2be` |

## Checks supporting that assessment

`prepare` checks the uint64 total byte sum independently of alpha, reduces
rationals before LCMs, reserves the uint128 infinity sentinel, and checks an
objective upper bound before solving. With coefficient scale A and weight
scale F, alpha/beta use A, weights use F, gamma uses A*F, and the public cost
scale is A*F. Both evaluators therefore compute the declared rational objective.

The formula evaluator uses prepared incidence and parent-first component IDs;
the materialized evaluator follows raw parent links and matches raw terms by
segments. ENUM uses Gray-code cuts, disjoint sets, and per-component class
deduplication. MASK-DP uses the same open pricing mask for joins, retains z,
charges fixed read/store fees only when positive volume materializes the open
component, finalizes the root, and reconstructs actual exact-count layouts.
The raw-term/undirected-component test oracle does not share prepared
incidence or either production component construction. It intentionally shares
the normalized integer representation; independent hand-derived rational unit
cases supply a separate scaling check. Agreement alone is not treated as a
proof that shared arithmetic is valid.

Per-partition curves retain exact materialized counts, with at-most selection
performed separately. The global code scales actual counts and nonnegative
rational penalties, chooses fewer stores on a tie, and withholds bounds unless
every curve has a certified complete declared domain. Its certification flag
is a caller precondition; the study adapter derives it from solved complete
exact solver output. Unknown/timed-out feasible incumbents are not promoted
to lower bounds. Python independently reconstructs J from rational metadata
weights/coefficient values and reported class metrics, and restricts gaps to
agreed solved exact results. Python alone does not independently reconstruct
the input topology/incidence: frozen input hashes and the CLI's raw
materialization provide that additional identity/verification layer.

The inspected saved unit-log endings report 20/20 tests passed in release and
ASan/UBSan. Each saved CC-5 summary reports 10,000 completed instances with
seed 20191230, zero mismatches, 57,461 exact-count comparisons, 57,461 at-most
comparisons, 96,322 reconstructed layouts, and 20,000 random layouts. The two
builds have identical input hash `112398f36f943dbe` and result hash
`c4b17e0577e35cab`. These are inspected saved results, not reviewer reruns.

## Timing and remaining execution boundary

The existing `results/p7/timing-clarification.md` agrees with source:
preparation occurs before CLI timing; `ExactResult.seconds` includes internal
reconstruction and its formula consistency check; H-KM timing includes its
own formula evaluation. The independent CLI formula/materialized full-metric
verification occurs after the solver timing boundary. `verified_seconds` is
the total elapsed method-plus-verification time, not a measurement of the
verification step alone. These values are nonexclusive-host solver diagnostics,
not engine latency or physical disk-recovery measurements. The clarification
does not move any cap, timing boundary, input, or acceptance threshold.

The full real/synthetic campaign, complete analysis, global-sweep execution,
figures, and phase gate remain the root owner's work. This audit neither
substitutes partial aggregates for full-population results nor marks P7 done.
