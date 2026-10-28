# P6 integration evidence review — 2026-10-23

This is a development review, not a P6 acceptance claim. The original execution
instruction remains [P6–P8](../../PHASES_6_TO_8_IMPLEMENTATION_PROMPT.md). No
measurement campaign or optimizer implementation was executed by this reviewer.

## Saved checks independently inspected

- The instrumented, **pre-prefix-lookup-repair** F3 gate completed 1,802.145102438
  confirmed monotonic seconds in 15 successful segments: 100,617 executions,
  peak RSS 816 MiB. Independent verification reconciled each original log hash,
  unique final statistics and DONE marker, all 39 frozen source/build files,
  the actual fuzz binary, all 1,391 final corpus hashes and an empty artifact
  directory. Leak checks, UBSan halt and `TIPLOG_FUZZ_MODE=all` were recorded.
  See [verification](fuzz-gate-verified.json),
  [executed command](F3-independent-terminal-verification-20261023T143211.679744Z.json)
  and [verifier](../../scripts/verify_p6_fuzz.py). These results are historical
  once `subs/compiled.cpp` changes; the final repaired core needs affected
  acceptance reruns. Preserve the original freeze record when creating a new one.
- Both saved ctest logs state **163/163 passed**, including six additional digest
  and actual replay-work tests. Release took 2.59 s ctest time; ASan/UBSan took
  7.52 s ctest time. Commands and sanitizer settings are in
  [release record](release-tests-observer-20261019T012930.012253Z.json) and
  [sanitizer record](sanitizer-tests-observer-20261019T012938.955831Z.json).
  These checks also precede the prefix lookup repair.
- [CC-2](CC2-all-configurations.json) records nine configurations per preset:
  90,000,000 release operations and 18,000,000 ASan/UBSan operations. All 18
  saved command JSONs and actual log JSON outputs were independently reconciled
  against the terminal table, and canonical outcome fields agree within each
  preset after its explicit mode-specific exclusions. Release canonical digest
  is `1217005992737911606`; sanitizer digest is `14647895778461039806`.
  Final-source validity requires rerunning after the compiler repair.
- A fresh Clang core-only build passed via
  [saved command](RC3-clang-core-build-20261023T143108.438836Z.json).
  [Fresh RC-3 attempt](RC3-instrumented-functional-20261023T143216.541774Z.json)
  retained all 180 repeated GCC/Clang functional child outputs, including real
  trace success/expiry and synthetic modes. Functional comparisons passed, but
  the terminal source-identity assertion **failed** because the authorized
  subscription compiler repair changed source during the run. It is not a
  passed RC-3 gate. All failed evidence is retained under `results/p6/rc3-*`;
  [P6 checker](../../scripts/check_p6_rc3.py) never writes P5 evidence. After
  final source stability, rebuild the two functional targets in both compiler
  directories and rerun this checker. Its scope excludes unrelated benchmark
  tools, with a separate broad source snapshot and exact tested binary hashes.
- After the repair stabilized, the Clang core-only rebuild passed and
  [final repaired-core RC-3](RC3-prefix-final-functional-20261023T143848.939102Z.json)
  **passed**: 180 children and 170 equalities, 335.584 s. Independent terminal
  verification also passed: all 180 child file hashes/raw outputs and 45
  case/configuration GCC/Clang groups, all cross-configuration real-trace
  observables, the current frozen source/binaries and actual trace checksum.
  See [verification command](RC3-prefix-final-independent-verification-20261023T144510.915624Z.json),
  [verification result](rc3-final-verified.json),
  [immutable summary archive](rc3-summary-20261023T143849.079765Z.json) and
  [independent verifier](../../scripts/verify_p6_rc3.py). The archived summary
  hash is `87b906957826c15674ae84e79e673bd34604ec83f5e81e801d2b9413b489a77f`.

## Findings, changes and validation

| Finding / approved requirement | Decision and implementation | Executed evidence |
|---|---|---|
| VALIDATION §§5–7: retain and report frequency deviations, without treating missing observations as zero | `analysis.summarize.hydrate_noise` reads and indexes the final frequency sidecar once at analysis time. Exact block **and** attempt matching prevents another micro retry's flags from leaking into a row. Any flagged endpoint conservatively marks that block's repetitions. T observations join exact configuration/process round/repetition/warm-up annotations; T2 annotations cover all cohort and publisher endpoints. Unknown observations remain null and separately counted. Raw JSONL is never rewritten and noisy observations remain in statistics. | [Final regression command](analysis-T5-facet-final-20261023T144329.232590Z.json), 19 tests passed. Includes mixed blocks/retries, exact T process/repetition/warm-up identities, missing sidecars, explicit false flags, raw-file preservation and unknown counts. |
| Approved measurement preconditions: a failed process/AC check cannot produce accepted timing merely because GBench emitted rows | `analysis.summarize.report_status` reports `ok` rows with `measurement_command_ok=false` as `invalid_config`; raw status remains recorded. Such rows cannot enter CIs or paired ratios. | Same regression command; explicit failed-command oracle-valid row and withheld pairing test. |
| T3 requested Indexed and Auto arms share F12 panels | `figures.tip.build` colorbar says “Scan CPU / requested arm CPU”, which covers both requested modes accurately. | Same tests exercise generation from explicitly synthetic temporary format fixtures; these are not experimental results. |
| T5 actual snapshots use `snapshot_ts`/`anchor_ts`, and both cache treatments repeat each B | `figures.tip.build` facets F13 by the actual snapshot key and cache treatment, preserving legacy fixture-key fallback. Its manifest records every panel's exact configuration IDs. | Same final regression command: explicit synthetic temporary rows with two actual-key anchors × two caches at the same B values remain four separate panels; legacy keys remain supported. |
| Required T5 snapshots may exceed retained history | Review found that `after_seq=0` can produce valid expiry outcomes yet hide all memory metrics when performance filtering is reused. Root/Python implementer were notified; use a valid captured checkpoint for the memory-only request or explicitly separate validated memory accounting from replay failure. | Correction and actual snapshot checks remain owned by the experiment driver task. |
| Required T3 `P=100000` exposes quadratic subscription compilation | Root authorized a scope-preserving lookup/normalization repair, with unchanged semantics and fresh affected gates. | Final repaired-core RC-3 passed as recorded above. The fresh F3 and CC-2 campaigns remain root-owned; this review does not infer their final status from elapsed time. |

Statistical review confirms the seeded 10,000-resample median bootstrap and
whole-paired-round ratio design, explicit non-ok/CC-4 failure accounting,
separate micro interleaving labels, and actual T2 signed writer delta divided by
its own publisher market duration once per reader cohort. F06–F13 still require
actual completed campaign input. Tests using synthetic temporary rows establish
the analysis format and invariants only.

No new paper algorithm, source-code reuse or unpublished Aria implementation
claim was introduced by these integration fixes. The primary-source reading
limitations remain in [method review](method-review.md) and the existing saved
research. P6's full CC-4, actual pilot/calibration/evaluation, RC-1 and raw-linked
claims gate remain open; P7 and P8 have not passed.
