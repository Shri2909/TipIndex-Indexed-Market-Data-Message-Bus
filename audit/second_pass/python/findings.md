# Independent second-pass Python audit

Audited 2026-10-26. All 31 Python package modules and all 12 Python test files were read, including the complete previously scanned experiment runner, analysis and figure pipelines, and layout input/analysis/global-study modules. Also read the oracle's 33-line `hash_bytes.c` FFI implementation. No production source, configuration, accepted measurement, trace or report was modified. Mutated inputs and indexes were created in `/tmp` and removed; retained evidence is confined to this directory.

Executed the two probe programs below. All their demonstration assertions passed, i.e. the defects described below are **CONFIRMED**. These are not expected passing regression tests for a repaired implementation.

```sh
PYTHONPATH=py PYTHONDONTWRITEBYTECODE=1 .venv/bin/python audit/second_pass/python/probe_python_second_pass.py > audit/second_pass/python/probes.json
PYTHONPATH=py PYTHONDONTWRITEBYTECODE=1 .venv/bin/python audit/second_pass/python/probe_oracle_scaling.py > audit/second_pass/python/oracle_scaling.json
```

Additionally executed 109 existing tests covering all affected subsystems: **109 passed in 1.78 s** (`targeted-pytest.log`). Exact invocation:

```sh
PYTHONPATH=py PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -c py/pytest.ini -p no:cacheprovider --basetemp=/tmp/tiplog-second-pass-python-tests py/tests/test_analysis_stats.py py/tests/test_exp_protocol.py py/tests/test_exp_oracle.py py/tests/test_itch_cli.py py/tests/test_itch_protocol.py py/tests/test_itch_routing.py py/tests/test_trace_format.py py/tests/test_layout_analysis.py py/tests/test_layout_cli.py > audit/second_pass/python/targeted-pytest.log 2>&1
```

## PY2-01 — CLI output alias checks omit temporary paths and measurement mode can overwrite its input

**MEDIUM; CONFIRMED data loss.** Sources: `py/tiplog_py/itch/__main__.py:69-85`, `:95-109`, `:138-147`; `py/tiplog_py/trace/format.py:57-61`, `:97-104`.

`convert()` validates the final trace, metadata and counts paths against the source, then `TraceWriter` opens `<output>.partial` with `w+b`. That actual write target is absent from the alias check. Given a source named `source.mdt.partial` and `--output source.mdt`, the preflight permits the invocation, hashes the source, then truncates it. In the executed 16-byte complete BinaryFILE fixture, the input was **absent after the failed conversion**. The exception happened during subsequent metadata handling (`FileNotFoundError`): the temporary file had become the final output, so the source path no longer existed. The deletion/truncation itself is already sufficient to establish the defect; exact later error timing depends on buffering/input type.

`measure()` does not perform source/output checks at all. Running it with `--output` equal to its input successfully replaces the original BinaryFILE with the JSON measurement. The second isolated fixture changed from 16 bytes to approximately 1.7 KB of JSON. The tests already establish source preservation for ordinary `convert()` final outputs (`test_cli_rejects_source_overwrite_and_duplicate_outputs`), but neither missing case is covered.

The same incomplete write-set preflight permits a dual conversion's final output to alias the other writer's temporary path; this variant is code-confirmed, not separately executed. CSV/table destinations can also be included in a future write-set audit rather than assuming the current `targets` list represents all writes.

Impact: an otherwise accepted local CLI invocation can destroy the local source or another selected artifact. A full Nasdaq source is expensive to reacquire. Existing accepted source data was not touched and this does not imply historical corruption.

Recommendation: validate every actual write target, including temporaries, before opening any writer; apply source preservation consistently to measurement and conversion; reserve unique sibling temporary files for each operation and clean up only owned temporary artifacts. Where existing hard links are possible, pathname resolution alone does not establish different file identity. Construction/cleanup should also encompass failure to initialize the second writer.

Proposed regression validation: source equals final output, source equals `<output>.partial`, symlink/hardlink aliases, primary final equals secondary temporary, and failure opening writer two must preserve the source and all preexisting files. Existing conversion repeatability/count tests must still pass.

## PY2-02 — Independent retention oracle repeatedly rewrites whole suffixes for each PAD

**LOW; CONFIRMED performance defect, scalable to quadratic preparation work.** Sources: `py/tiplog_py/exp/oracle.py:121-157`, specifically `:144-146`; reached from `OutcomeOracle.__init__()` at `:188-194` and preparation at `py/tiplog_py/exp/run.py:117-120`, `:127`.

The PAD discovery step is followed by `positions[index:] += padding` for every wrap with padding. Its cost is the sum of all remaining suffix lengths, **O(N × PAD_count)**. With a fixed small valid capacity and regular records, PAD_count grows linearly with N, making the suffix-update phase O(N²). A 64-byte ring with 24-byte records is valid: records fit the half-capacity maximum and the alternating PAD is 16 bytes.

Executed three diagnostic samples for each size, saved in `oracle_scaling.json`:

| Records | PAD count | Array elements incremented | Median elapsed |
|---:|---:|---:|---:|
| 4,000 | 1,999 | 3,998,000 | 0.0071 s |
| 8,000 | 3,999 | 15,996,000 | 0.0198 s |
| 16,000 | 7,999 | 63,992,000 | 0.0707 s |
| 32,000 | 15,999 | 255,984,000 | 0.2347 s |
| 64,000 | 31,999 | 1,023,968,000 | 0.8695 s |

These are diagnostic timings on the active development host, not quiet-host performance claims. The work counts follow directly from the executed PAD schedule: N(N−2)/4 for this even-N fixture. A 16× input increase produced 256× suffix-element work. Larger retention-pressure correctness studies/preparation become disproportionally expensive even though the C++ engine can consume the schedule in linear publication work.

Current frozen P6 capacities are much larger than this fixture, so these measurements do not establish that existing preparation dominated campaign time. They reveal a real small-retention / long-input scaling failure and should not be presented as a new engine hot-path defect.

Recommendation: accumulate padding at each affected record once and prefix-sum those deltas; add that prefix to `starts` once. Preserve the independent mathematical oracle rather than reusing production retention logic.

Proposed regression validation: retain the existing scalar whole-item queue differential checks, include many wraps at small capacity, and verify padding application visits O(N + PAD_count) entries. Any timing check should be broad/scaling based, with structural work bounds preferred over machine-specific microsecond limits.

## PY2-03 — Process journal cannot resume after an append leaves a torn JSONL tail

**MEDIUM; CONFIRMED recoverability defect.** Sources: `py/tiplog_py/exp/run.py:49-54`, `:61-81` (especially `:72`); resume replay at `:401-403` (look up `for marker in sorted(directory.glob('*/*.commit.json'))`).

The pending commit marker contains the complete batch before publication, and the docstring promises recovery after interruption. However, recovery reads every existing JSONL line with `json.loads()` before comparing row identities. A process termination, failed write, or disk-full condition partway through the append can leave a partial final JSON object. `fsync()` after the loop cannot prevent an interruption *during* that loop, and Python may flush large rows using multiple underlying writes.

Executed a fixture with one complete saved observation, a torn final JSONL line and the intact pending marker holding both complete original observations. `publish_commit()` immediately raised `JSONDecodeError: Unterminated string`; the marker remained pending. Thus an interrupted long-running session cannot be resumed automatically despite enough authoritative journal information being available. This extends the existing idempotence test, which only simulates interruption between complete rows.

Impact: previously completed expensive process measurements remain on disk but the runner refuses recovery; manual evidence repair or rerunning a session is needed. This is not proof that any current accepted JSONL file is torn or that committed successful observations are wrong.

Recommendation: make publication recoverable at record boundaries, e.g. immutable per-process segments with manifest publication, or validate the JSONL tail and preserve/recover only the incomplete final record from the owned pending journal. Do not silently discard arbitrary corruption inside earlier committed rows. If retaining append files, scan them incrementally so recovery does not require a complete file copy in memory.

Proposed regression validation: inject interruptions after every byte boundary of a representative multirow publication, resume from the pending marker, and require each row exactly once. Include empty final line, partial UTF-8/JSON tokens, disk-full/write exceptions, and a corrupt interior committed row which must be reported rather than dropped.

## PY2-04 — Valid maximum trace payloads do not fit the oracle's aligned-size dtype

**LOW; CONFIRMED valid-input rejection.** Sources: `py/tiplog_py/exp/oracle.py:19-20`, `:89-96`; `py/tiplog_py/exp/synthetic.py:63-69`, `:102`; supported format limit at `py/tiplog_py/trace/format.py:67-71`.

Trace payload length is u16, permitting 0..65,535 bytes. The independent index also stores **aligned record size** in u16, although align8(16+payload_length) reaches 65,552 and first crosses 65,535 at payload length 65,513.

Executed payload lengths 65,512, 65,513 and 65,535. All three produced a valid trace accepted by both the Python `TraceReader` and the release C++ `tiplog_trace_check` (exit 0). `TraceIndex` indexed the first (65,528-byte aligned record), but raised `OverflowError` for the other two (`65536` and `65552` out of bounds for uint16). The synthetic generator explicitly accepts such a payload mix and fails with the same error at row assignment. Evidence is in `probes.json`.

Impact: the independent experiment/oracle tooling cannot handle the full format/synthetic input representation it accepts. The current ITCH payloads and frozen P6 empirical mix are small, so this does **not** invalidate existing measurements or parser results.

Recommendation: store aligned size as at least u32, bump the local cache/parser schema version, and rebuild incompatible caches; or explicitly impose/document a narrower tooling contract before allocation if intentionally unsupported. Widening size is consistent with the declared full u16 payload representation.

Proposed regression validation: trace and synthetic payload boundaries at 65,512, 65,513 and 65,535, correct alignment/retention/digests at an adequate capacity, and old cache rejection/rebuild. Include the independent C++ trace-check acceptance comparison.

## PY2-05 — T2 cohort aggregation silently hardcodes a 10-second market window

**LOW; CONFIRMED nondefault-configuration measurement error.** Sources: `py/tiplog_py/exp/matrix.py:108-113` (configured backlog/market duration), `py/tiplog_py/exp/run.py:239-240`; downstream use in `:522-528` (look up `amortized_index_cpu_ns`) and `py/tiplog_py/analysis/summarize.py:163-176`.

The matrix passes `config['t2']['backlog_seconds']` into both `backlog_seconds` and `market_seconds`. `aggregate_t2()` then replaces `market_seconds` with literal `10`. The runner and analysis subsequently use that value for CPU per market second and writer amortization.

Executed a complete, oracle-passed single-reader group whose configuration declares a 20-second backlog and whose replay uses 20 billion CPU ns. Aggregation changes its duration to 10 seconds: the reported CPU rate becomes **2 CPU seconds/market second instead of 1**. This is a source-level measurement interpretation error, independent of benchmark timing noise.

Current frozen P6 configuration uses 10 seconds, so its recorded T2 rates are **unaffected**. This is a defect when legitimately adjusting the declarative experiment matrix.

Recommendation: preserve the group's declared `market_seconds` and verify that all constituent readers agree on the duration and workload identity before aggregating. Include duration in the cohort comparison identity where necessary.

Proposed regression validation: parameterize complete T2 groups at 1, 10, 20 and 60 seconds and validate both raw replay CPU rate and amortized writer rate. Reject mixed-duration groups.

## PY2-06 — Lightweight acceptance helper reports missing measurement controls as verified

**LOW; CONFIRMED validation-helper weakness, qualified by stronger final campaign checks.** Source: `py/tiplog_py/exp/audit.py:42-68`, particularly `:43-46`, `:57`.

`measurement_command_ok` defaults to `True` when absent. The helper can therefore label `measurement_commands_valid=true` and the whole supplied cohort `passed` with no measured command evidence. The executed fixture has the required one warmup and ten distinct measured processes and oracle fields, but omits `measurement_command_ok` from every row; it passes. Likewise, this helper only knows configurations which appear in its input and cannot detect an entirely missing configuration without an expected plan. This is why its result must not be interpreted as complete campaign acceptance.

The final `scripts/run_p6_campaigns.py` separately invokes `scripts/check_p6_experiments.py`, whose independent session audit validates the supplied plan, process/command evidence, requests, outputs and repetition coverage. That stronger step materially mitigates this helper's weakness. Do **not** claim that this probe bypassed the final P6 gate or invalidated the current accepted campaign. The issue matters to callers of `audit_file()` / `acceptance()` in isolation and to the truthfulness of their field name/status.

Recommendation: require explicit `measurement_command_ok is True`, and either supply the expected configuration/repetition manifest or name/mark this result as a limited supplied-row audit. Consolidating acceptance contracts would reduce future caller confusion.

Proposed regression validation: missing/false/null command controls fail; complete control evidence passes; expected-but-absent configurations and repeated/wrong repetition labels fail when a plan is supplied; retain the final independent audit tests.

## Checks yielding no additional confirmed issue

- Read and assessed seeded median and whole-paired-round bootstrap logic, failure retention, missing-pair withholding, per-configuration binary/input strata checks, frequency sidecar joins, and T2 signed writer-delta arithmetic. No new numerical/statistical defect was confirmed in those paths for the current prescribed inputs.
- Read all P6/P7 plotting code and adversarial figure tests; existing conditional-cohort, unavailable-ratio and exact-coverage distinctions are explicit. No new defect is claimed merely from statistical intervals being host-specific or from modeled layout bytes differing from physical I/O.
- Read layout input construction, rational weights, class compression, exact-curve coverage and global bound reconstruction. The analyzer is not a substitute for verifying raw layout reconstruction; no blanket claim of independent proof for every emitted byte vector is made here.
- Stage-1 observations AUD-005/006/009 (blank-symbol diagnostics, CWD-sensitive test, acquisition checksum policy) remain outside the new finding count.
- Full-day conversion, full P6 saved-output oracle audit, full P7 campaign and controlled benchmark timing were not rerun by this sub-audit. Existing stage-1 evidence is not relabeled as executed second-pass work.

Suggested feature from this slice: one manifest-driven experiment/evidence validation entry point which validates complete expected coverage, immutable input/source identities, resumable process segments and measurement controls, then feeds the figure/report builders. It would reduce the split acceptance contracts illustrated by PY2-03/06. This is a feature suggestion, not a claim that the current final independent P6 gate is missing.
