# P6 report source → implementation → validation map

Finalized2026-10-25. Measurement, saved-output audit, statistical and final
rendering/regeneration checks have passed. The P6 acceptance record is
`phase-gate.json`; the explicit stop boundary leaves P7/P8 unstarted.

| Source/finding | Decision/task | Code/symbol | Validation/evidence |
|---|---|---|---|
| VALIDATION §§5–7; S41/S42/S44 with reading limits in method-review.md | P6.2 frozen protocol, process rounds, truthful cache/noise labels | `exp.run.execute`, `run_p6_micro.py`, `analysis.stats` | pilot-response.json, protocol-freeze.json, actual micro sessions and campaign/evaluation states |
| FINDINGS45,49,52–53; V27/CC-4 | P6.1 independent full-outcome expectations and saved evidence | `exp.oracle`, `check_p6_experiments.py` | prepared-evaluation/plan.json; evaluation/independent-audit.json passed10295181 checks,zero failures after exact T5 enriched-work comparison repair; original failed audit/source preserved |
| S01 motivation; H1/H2 are project hypotheses, not source results | P6.3 selective/dense recovery and merge/data-touch comparisons | `tiplog_bench`, merge kernels, micro harnesses | M1/M2/M3 passed terminal records; T1/T3 complete paired rounds; actual summary and report C01–C09 attach config/raw identities and95% intervals |
| VALIDATION T2; shared cohort accounting review | P6.4 charge actual writer delta once using separate durations | `analysis.summarize.t2_amortized`; new report-only `scripts/summarize_p6_t2_adjusted.py` |14 fixture self-checks, completed8-cohort20-round analysis; results/derived/t2-adjusted-paired.json with raw paths and source/input hashes |
| FINDINGS28; v1.1 capacity/reclamation contracts | P6.3 T5 full requested-memory/slack/recount and allocator boundary | `index::Index::stats/recount`; benchmark allocator replay; report generator | All12 T5 workloads passed; final audit verifies allocator enrichment from raw allocator arithmetic while requiring original replay counters unchanged; report C10 includes requested-byte components and slot counts |
| IMPLEMENTATION P4/P6 memory high-water requirement | P6.4 historical allocation peaks must use accepted attempts and raw records, not a final live recount | New report-only `scripts/summarize_p6_t5_highwater.py` | `results/derived/t5-high-water.json`:12 workloads×20 accepted rounds, raw/command/state/source hashes, exact coverage/single-memory-record/current≤peak≤capacity assertions |
| VALIDATION §5.4/RC-1 | P6.4 medians/IQR/range/n, seeded10000-resample CIs, paired ratios and F06–F13 | `analysis.summarize`, `figures.tip.build`, `figures.build` | Actual results/derived/tip-summary.json and CSVs, results/figures/p6-figures.json; final `figure-regeneration-verification.json` and actual `figures-final-title-regeneration-20261025T075429.868488Z.json` passed; all numerical summary/table hashes unchanged |

New report-only T2 command records:

- `results/p6/t2-adjusted-report-selftest-final-20261025T042015.276071Z.json` — exit0,14 checks over explicit temporary format fixtures; no benchmark.
- `results/p6/t2-adjusted-report-analysis-final-20261025T042021.275937Z.json` — exit0,8 real completed cohorts/64 paired comparisons, exact20-round and per-arm saved warm-up coverage checked.

Final postprocessor SHA-256:
`0799948cb70e8ccc11e7b4252b4c05b8b2138e7488adab0d9a4623eadac13848`.
The first13-check development run and its output command remain preserved;
the final14-check run also rejects replacement of a missing arm's warm-up by
a duplicate warm-up from another arm.

T5 high-water extraction:

- `results/p6/t5-high-water-report-analysis-20261025T043318.669440Z.json` — exit0,12 workloads/240 accepted measured processes; each raw and command file is hashed and the interrupted attempt is excluded by state-selected process ID.
- Script SHA-256: `a03d799953ad5dec40de8b4a591e85b2064d23e421aa6fac5ea74b76dc88cad6`.
- Artifact: `results/derived/t5-high-water.json`, with per-workload min/median/max and accepted raw paths. No engine, benchmark or existing frozen source was changed.

The T2 postprocessor is an independent report addition. It does not mutate raw
observations, existing frozen code, timing binaries, Auto thresholds or protocol.
It retains negative writer deltas and withholds ratios for unusable/nonpositive
paired costs. The report's C01–C11 claims table now binds numerical selections
to raw files/config IDs and distinguishes raw/normalized request counts. Measured
outcomes are125700ok,4320expected packed-limit invalids and1preserved crash;
all noisy observations are retained. Final actual regeneration passed, with143
Python tests and the original numerical artifact hashes preserved. The gate and
`closeout-evidence.json` bind final commands and checks; no planned test is used
as executed evidence.


Execution-review corrections → independent raw allocator arithmetic and exact
work equality → `check_p6_experiments.py` →2487 fixture checks/13 tamper
rejections and10,295,181 actual audit checks → original failure/source/provenance
snapshots in `auditor-t5-compatibility/`;5364 measurement files unchanged.

Actual figure-review findings → visible arm slots, factorized legends and
physical title inset → `figures.tip._crossover_panel/_lines/_save` →3 focused
figure tests,143 full Python tests, one-command actual regeneration, exact
ratio/position metadata review and four byte-identical numerical artifacts →
`f12-layout-fix.md`, `f12-layout-compatibility/`,
`f12-title-position-compatibility/`, `figure-regeneration-verification.json`.
These are postprocessing corrections, not changes to approved semantics,
workload scope, acceptance criteria or any timed source.
