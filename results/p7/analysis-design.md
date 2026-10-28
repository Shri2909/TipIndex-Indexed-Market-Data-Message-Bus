# P7 analysis design

`py/tiplog_py/layout/analyze.py` consumes the generated `case_index` and shared
class metadata plus actual CLI JSONL. Input rows are streamed one case at a time;
all methods for one case must be contiguous. It writes a compact JSON summary
and a CSV observation for every valid requested case/method, retaining caps and
infeasible outcomes. It never treats an unsolved incumbent as OPT.

Claims use Python `Fraction`. Each feasible objective is independently rebuilt
from metadata coefficients, effective consumer weights and the saved read-byte,
useful-byte, waste-byte and touched-store arrays. The analyzer checks volume,
node/class count, requested budget, coefficient identity, class weight scaling,
byte accounting and the selected exact curve's prefix minimum. Complete curves
must span all feasible materialized counts. ENUM and DP optima must agree when
both solve the same case. A layout cheaper than a certified optimum is a failure.

L2 summaries group hierarchy, workload, coefficient triple, source kind, budget
policy and method. They retain weighted read/useful/waste bytes, weighted stores
touched, actual stores, maximum waste and worst read amplification with and
without the 4 KiB useful-byte floor. Effective classes are expanded through
their saved raw memberships into consumer roles; `EXACT:path` contributes to the
`EXACT` role, and market `BOOK:symbol` contributes to `BOOK`. Rational weights
are retained. Coverage uses every expected metadata case as its denominator,
with separate count, record-byte and active **per-partition** class-weight
fractions. Missing methods, timeout/state/representation limits and incomplete
curves remain explicit.

L3 comparisons require the same case and requested budget, matching metadata
and a solved certified exact result. Absolute gaps remain defined at zero OPT;
relative gaps are null. Baseline improvement is null if the baseline is absent,
infeasible or zero-cost. Runtime summaries group n, b, K and shape and retain
solver statuses. Solver seconds include solver-internal reconstruction and
formula consistency checks; they exclude preparation and CLI independent
formula/materialized verification. State/work counts are exact-solver proxies,
not allocated bytes or RSS. Process RSS belongs to the campaign resource logs.

L5 presents H-spec and H-flat observations in parallel, without claiming a
cross-hierarchy optimality gap. Every feasible H-flat W0 baseline must have
exactly zero weighted exact-read waste. Modeled record bytes remain distinct
from physical disk I/O.

Fractions in JSON have `{ "exact": "numerator/denominator", "value": number }`
with reduced integer strings where possible. Plotting conveniences do not
replace exact claim arithmetic. CSV fractions are exact strings. Missing or
zero-denominator metrics remain null/blank with a reason. Provenance includes
the metadata and JSONL SHA-256 values. A failed audit writes explicit failure
counts and exits nonzero; an analyzed result does not mark a phase gate passed.

Small functional fixtures were executed successfully for rational class
weights, state-limit coverage, zero byte/weight denominators, no gap without an
exact result, invalid byte accounting rejection and denominator-zero rejection.
These fixture checks are not study observations or CC-5 evidence. Full study
analysis and the actual campaign are executed separately by the root workflow.

```sh
PYTHONPATH=py python -m tiplog_py.layout.analyze --metadata results/raw/P7/inputs/metadata.json --input ACTUAL-ROWS.jsonl --output results/derived/layout-summary.json --csv results/derived/layout-claim-metrics.csv
```
