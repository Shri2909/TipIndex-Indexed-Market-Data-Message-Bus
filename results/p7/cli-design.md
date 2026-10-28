# P7 layout CLI contract

`tools/tiplog_layout/main.cpp` is a standalone front end to the layout model,
heuristic, exact, and global-curve APIs. It has no engine or JSON-library
dependency. All integer parsing is digit-only and checked; rational inputs are
nonnegative `numerator/denominator` pairs (an integer is shorthand for denominator
one). Zero denominators, negative/floating inputs, repeated options, duplicate
case/curve IDs, malformed directives, unfinished records, and invalid model
inputs produce an explicit JSON error row and a nonzero exit code. IDs and
messages receive JSON string escaping. Canonical input/output aliases are
rejected before output truncation.

Case input is tab-separated, with implicit node IDs in NODE order:

```text
CASE	three-node	2
COST	1	0	0
NODE	-	1	r
NODE	0	2	r/a
NODE	1	3	r/a/b
CLASS	one	1
TERM	E	r
TERM	E	r/a/b
CLASS	two	1
TERM	E	r/a
END
```

An explicit COST is required in every CASE. NODE parent `-` is the root marker;
other parents are uint32 node IDs. TERM `E` means exact and `S` means subtree;
terms attach to the most recent CLASS and form a union. Blank lines and lines
beginning with `#` are ignored. CRLF is accepted. Node and term semantics are
validated by the model's `prepare` function. CASE budget is a uint32 materialized
store budget. Real study inputs must set it to that partition's actual baseline
count; synthetic inputs may use their declared K.

```sh
build/release/tiplog_layout --input cases.tsv --output rows.jsonl \
  --methods base,km-min,km-max,enum,dp --full-curves \
  --enum-max-edges 22 --dp-max-classes 16 \
  --max-states 2000000 --max-work 2000000 --time-limit-ms 500
```

`--full-curves` asks exact methods for all counts through positive_nodes, while
the selected layout still uses the CASE budget. Without that flag, the requested
exact count domain stops at the CASE budget. `at_most` is called only for solved
curves. `exact=true` requires a certified feasible selected optimum at the CASE
budget; a solved full curve with no feasible selected layout keeps it false.
A non-solved exact result retains its explicit solver status and any
noncertified curve entries, with no certified chosen optimum. Every chosen
layout is independently evaluated with both the formula and raw materialization
evaluators; objective, count, and all four metric vectors must match.

Each layout JSONL row contains `id`, `budget`, `method`, `status`, `solver_status`,
`exact`, exact decimal-string `scale` and `objective`, actual `stores`,
`nodes`, `positive_nodes`, `classes`, `total_bytes`, normalized `alpha/beta/gamma`,
`threshold`, `work`, `states`, `seconds`, `verified_seconds`, `read_bytes`,
`useful_bytes`, `waste_bytes`, `stores_touched`, and cut-node IDs in `cuts`.
Unavailable layout metrics are null. Baseline layouts exceeding the requested
budget retain their measured metrics and report `infeasible_budget`. Exact rows
also include an actual-count-indexed `curve` of cost strings/null and
`complete_domain`; incomplete finite entries are incumbents, not certificates.

`seconds` excludes the CLI's independent layout verification. For exact solvers
it is the solver-reported duration; for baseline and heuristics the timer ends
immediately after their construction call. `verified_seconds` is the full
per-method duration including the CLI check. Neither field includes shared
case preparation. `active_class_weight/class_weight_scale` gives the exact sum
of the active prepared class weights in rational units; this supports the
per-partition weight coverage denominator without repeating class names or
individual weights in every row. Bytes and metric-vector entries are JSON
integers; exact objective/scaling arithmetic is never emitted as floating point.
Output is flushed after each completed CASE, and on errors, preserving completed
rows for a caller-managed resume.

Global input uses the separate mode:

```text
CURVE	partition-one	1	3	1
POINT	1	10
POINT	2	8
POINT	3	0
END
```

CURVE fields are ID, exact integer scale, maximum actual count, and certification
flag `0` or `1`. POINT fields are actual count and scaled cost, or `null`.
Unspecified entries are null: proven infeasible only when the supplied domain is
certified complete, otherwise unknown. Duplicate POINT counts and out-of-domain
counts are rejected. The per-curve allocation must fit `--max-states`.

```sh
build/release/tiplog_layout --global-curves curves.tsv --output global.jsonl \
  --multipliers 0,1/2,5 --budgets 1,2,3
```

Global point rows contain exact common scale, objective, penalized cost, actual
total stores and per-partition counts. Bound rows contain the signed scaled
bound as a string, scale, and an explicit `available/certified` guard. The global
API withholds certificates for incomplete curves. If no finite candidate is
observed and no complete partition proves infeasibility, the CLI reports
`no_feasible_incumbent`, preserving the distinction between unknown and proven
infeasible. The empty forest is supported. `-` selects stdin/stdout.

The source was checked with the project's warning flags using a logged
`g++ -fsyntax-only` invocation via `scripts/run_check.py`; see
`layout-cli-syntax-timing-20261025T083637.436518Z.{json,log}`. Link, execution,
sanitizer, and study evidence are owned by root integration and are not claimed
by this source note.

`worked_example.cpp` is a separate executable for the L4/V32 article example.
It computes baseline and both common-threshold endpoints on the separate L/R
partitions, independently allocates their ENUM and MASK-DP curves at every joint
budget 1–8, and saves the budget-four layouts and raw node models. Its eight rows
include the manual figure cut set, both exact solvers, both heuristic endpoints,
and the two specified fixed-threshold checks. Every reconstruction is evaluated
by both evaluators and all required waste totals/plateau endpoints are asserted.
Example invocation: `build/release/tiplog_layout_example --output
results/p7/worked-example.json`. Its warning-clean syntax-only check is logged as
`layout-example-syntax-20261025T083902.889283Z`; execution evidence remains root
owned.

The dependency audit saved `results/p7/dependency-impact.json`: all 38 baseline
core files apart from the intentional top-level CMake addition, all 19 existing
binary hashes, original release/ASan compile-command entries, P6 gate, and master
prompt matched their captured baselines. Removing exactly the one additive P7
include restored the baseline CMake content. The audit snapshot precedes the
worked-example target addition and excludes the separately planned P6 figures
compatibility build.

The isolated CLI check covered quoted IDs with full curves selected at a smaller
CASE budget, unsupported-budget bounds, incomplete no-incumbent withholding,
mixed exact global scales, and the computed release worked-example output.
The initial attempt is retained as
`cli-isolated-boundaries-20261025T084027.890211Z`: LSan reported that it cannot
operate under the sandbox's ptrace. The diagnostic rerun
`cli-isolated-boundaries-no-lsan-20261025T084043.395259Z` completed with leak
detection disabled and is **not accepted sanitizer-validation evidence**. Its
sanitizer assertions require a later leak-enabled rerun outside ptrace using the
approved escalation fallback. The temporary runner has been restored to inherit
`run_check.py`'s `detect_leaks=1`; no further checks run during the serial solver
campaign. The deferred command is `python3 scripts/run_check.py p7
cli-isolated-boundaries-outside-ptrace -- python3 /tmp/p7_cli_isolated.py`.
