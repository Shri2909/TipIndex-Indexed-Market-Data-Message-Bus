# P7 L3 runtime protocol review

2026-10-25 UTC. Read-only requirement review; no builds, tests, optimizer runs,
or machine-setting changes were performed. This supplements the implementation
audit in `independent-design-review.md` and does not mark an execution gate.

## Requirement and finding

Inspected `docs/plan/VALIDATION_PLAN.md` principles, section 5.1–5.4, L3,
optimizer coverage and protocol qualifications; `ARCHITECTURE.md` core scope
and section 6; `IMPLEMENTATION_PLAN.md` P7 and “Never cut” requirements;
`results/p7/protocol.json`, `timing-clarification.md`, `analysis-design.md`;
and `scripts/run_p7_studies.py`. A second read-only reviewer independently
checked the interpretation of the benchmark requirements.

L3 expressly requires **DP runtime scaling**. Timing used to support that
result falls under the approved benchmark environment/statistical controls.
The original P7 campaign deliberately reports solver seconds as diagnostics
on a nonexclusive host. CPU-2 taskset, AC/environment snapshots and resumed
campaign provenance are useful, but they do not establish the per-run CPU and
frequency observations, idle-block treatment, repetitions or uncertainty
required for a controlled runtime result. Calling those original observations
diagnostic does not by itself complete the runtime-scaling requirement.

This finding does **not** invalidate exact integer costs, reconstruction
checks, correctness validation, state/work limits, or the existing complete
quality/coverage matrix. The original timing rows should be retained with
their original diagnostic qualification.

Section 5.1 says environment fields are recorded “in every run”, requires
CPU-2 affinity and actual `sched_getcpu()` endpoints, frequency endpoints,
AC power, retention/reporting of >10% frequency flags, and 60 seconds idle
between blocks. Section 5.4 requires median, IQR, min/max, n, and a seeded
10,000-resample percentile-bootstrap CI for the median.

Section 5.3's >=10 process-level repetitions plus one saved, excluded warm-up
is explicitly labeled **End-to-end**, rather than explicitly naming the
offline solver. Applying that design to the solver CLI is a conservative
interpretation that avoids weakening the approved baseline; it is not an
assertion that the document literally gives a solver-specific repetition
count. The five synthetic tree seeds are different input instances, not five
timing repetitions of one configuration. The M1/T1 30-repetition pilot and
tip-only scratch-thrashed/repeat-warm treatment do not create new P7 duties.

## Recommended within-scope repair

Add a separately declared controlled **runtime supplement**, after the live
frozen campaign finishes. Keep all **900 existing synthetic case IDs**,
their trees, class incidence, rational weights, budgets, and solver caps
unchanged. DP alone supports the required DP-scaling result; repeat any other
method only if the report makes controlled runtime comparisons involving it.
Do not modify dependencies or rebuild underneath the running campaign.

One efficient faithful design is:

1. Freeze input/binary/source hashes, runtime protocol, random-order seed,
   timing boundary, and environment regime before timing starts.
2. Use 11 fresh process rounds: one declared saved warm-up, followed by 10
   measured rounds. Each process executes every one of the 900 fixed cases
   once, with case order shuffled from a recorded seed per round. Each case
   then has ten measured observations from ten distinct process IDs.
3. Declare each process round a measurement block and idle 60 seconds between
   blocks. If retaining size-based blocks instead, declare that blocking
   scheme, shuffle block/configuration order per round, and preserve the same
   60-second between-block treatment. There is no requirement for a 60-second
   gap between individual cases within a declared block.
4. Use release flags and CPU 2, preserve the authorized governor/turbo regime,
   keep the sibling idle, require AC, and avoid concurrent builds, fuzzing,
   conversion, analyses or research work during measurement blocks. Attempt
   per-process ASLR disabling only within the documented permitted/failure
   regime; do not introduce privileged machine-setting changes.
5. Record actual in-process CPU and CPU-2 frequency endpoints for each timed
   solver invocation, outside the solver timing interval. A supervisor's own
   CPU samples are not the child's `sched_getcpu()` observations. Link each
   result row to the complete process/session environment, release flags,
   git/dirty state, input hash, configuration, seed and process/round ID.
6. Keep the established `ExactResult.seconds` boundary, including internal
   reconstruction/formula consistency checks and excluding preparation/CLI
   independent full-metric verification. Report whole-process wall/CPU/RSS
   separately; do not reinterpret it as solver-only time.
7. Retain every warm-up and measured outcome, all frequency flags and all
   state/representation/timeout outcomes. Independently check expected case
   identities, unique measured process/round observations and warm-up count.
   Where both campaigns solve, verify costs/counts against the original
   frozen study. Do not promote capped runs to solved runtimes.
8. Summarize each fixed case separately with measured count, solved count,
   status counts, median/IQR/min/max and seeded median CI. Label any summary
   over solved observations conditional on solving and retain its cap
   fraction; a timeout is a censored outcome. A scaling plot may then group
   the predeclared sizes/shapes/classes/budgets, retaining instance identity
   and the different-input versus repeated-timing distinction.

This repairs measurement evidence within the existing authorized Tier-B P7
runtime study. It changes neither the optimizer model nor the original quality
matrix, and requires no scope reduction. No additional user permission is
indicated by these requirements for such a supplement. Approval would become
relevant only for a separate material change, such as changing machine
settings beyond authorization or revising the approved scope/acceptance rule.

The controlled supplement remains **proposed, unexecuted** in this review.
The P7 gate must not describe the original diagnostic campaign as controlled
or claim that this requirement review itself supplies timing evidence.
