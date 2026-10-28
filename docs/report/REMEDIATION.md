# Approved audit remediation — 2026-10-26

This phase completes the approved corrections for **AUD-001–AUD-026 and observations OBS-01–OBS-05** from the [independent audit](../../audit/AUDIT_REPORT.md). The original audit findings and their reproductions remain historical evidence. Final integrated validation and the separate current-source acceptance passed; the implementation decisions and executed evidence are recorded below.

**F-01, work-budgeted replay/tail polling, remains deferred at the user's request.** Replay and tail calls still have their existing output budgets and completion semantics. That feature requires a separate subsequent phase.

## Evidence and acceptance boundaries

[P0–P8 acceptance](REPORT.md) describes the pre-remediation implementation and its saved measurements. Its phase gates, accepted ledger, artifact manifest, raw measurement rows and original gate hashes are preserved. The historical binaries were identified and retained before replacement; see [historical binaries](../../audit/remediation/historical-binaries.json) and [historical artifact identities](../../audit/remediation/historical-identities.json).

Corrected source and freshly built binaries naturally have new identities. They are validated separately by [scripts/check_remediation.py](../../scripts/check_remediation.py), with current acceptance recorded in [audit/remediation/acceptance.json](../../audit/remediation/acceptance.json). The [current-source gate](../../audit/remediation/checks.json) passed with zero failures. The historical `scripts/check_core_closeout.py` is not evidence that the corrected source matches the old frozen source/binary hashes, and this phase does not relabel it as passing for the current source.

No fresh quiet-host P6/P7 performance campaign or full-length historical fuzz campaign is claimed. Local diagnostic probes, deterministic correctness checks and saved-evidence reconstruction do not replace those measurements. Hosted CI execution is also not claimed.

## Findings and implemented resolutions

Each finding below is closed by its correction or explicit compatibility decision and the final integrated validation. Observation resolutions are included in the same current-source acceptance.

| Finding | Correction / decision | Main evidence |
|---|---|---|
| AUD-001 | Topic paths are limited to **4,096 UTF-8 bytes and 128 nonempty segments**. Registry/subscription validation rejects excess before mutation; C++ and Python trace entry points and the independent Python oracle enforce the same policy. | [Core notes](../../audit/remediation/core.md), [Python notes](../../audit/remediation/python.md), [tools notes](../../audit/remediation/tools.md) |
| AUD-002 | Observer notification uses hash-based deduplication of observers and visited ancestors, retaining deterministic encounter order and preparation-before-commit behavior. | [Core notes](../../audit/remediation/core.md) |
| AUD-003 | Four negative invariant-checker controls now run in the normal CTest suite. Each Ring/Index/Engine no-op checker mutation is detected. | [Mutation summary](../../audit/remediation/core/mutation-summary.json) |
| AUD-004 | Differential schedules exercise more live retained readers and useful delivery, while retaining expiry/stale/future cases. Payloads include nonuniform bytes and expose a coverage counter. | [New differential sample](../../audit/remediation/core/campaign-summary.json) |
| AUD-005 | Malformed symbol fields raise typed Python framing errors with absolute byte offsets. C++ ITCH framing errors also carry offsets consistently across chunks and failure classes. | [Python notes](../../audit/remediation/python.md), [tools notes](../../audit/remediation/tools.md) |
| AUD-006 | The test matrix path is anchored to the repository; P7 figure-source provenance is independent of the current directory. | [Python notes](../../audit/remediation/python.md) |
| AUD-007 | pytest is patched to **9.0.3**. The project dependency advisory check reports no vulnerabilities for the installed locked snapshot. | [Advisory result](../../audit/remediation/pip-audit.json), [dependency lock](../../audit/remediation/dependency-lock.json) |
| AUD-008 | `Ring::at` retains O(1) access with an explicit proven-boundary precondition. New `Ring::at_checked` validates arbitrary locators by walking retained boundaries and rejects fabricated interior headers. | [Core notes](../../audit/remediation/core.md), [ring.hpp](../../src/tiplog/ring/ring.hpp) |
| AUD-009 | Acquisition verifies a recorded SHA-256 before replacing the manifest, including when reacquiring a missing local file. Mismatches preserve the existing manifest and downloaded bytes for inspection. | [Mocked acquisition regressions](../../py/tests/test_audit_remediation.py) |
| AUD-010 | Python project/tool requirements carry verified wheel hashes and are installed with `--require-hashes`. CMake defaults to the pinned SHA-256-verified GoogleTest archive; exact system GoogleTest requires explicit opt-in. | [Requirements](../../py/requirements.txt), [CI tool lock](../../configs/ci-requirements.txt), [dependency configuration](../../cmake/deps.cmake) |
| AUD-011 | The architecture now documents actual exceptions, diagnostic invariant checks and intentionally permitted undersized index pools handled by the selected pressure policy. | [Architecture](../plan/ARCHITECTURE.md) |
| AUD-012 | Fuzzer fixed pressure fixtures run once per process; subscriptions compile when used; full invariant recounts run periodically and at final state. Per-operation retention/output/oracle comparisons remain. | [Core notes and separate smoke evidence](../../audit/remediation/core.md) |
| AUD-013 | Duplicate trace paths are checked with temporary views into immutable input bytes, avoiding a second owned path copy. Retained dictionary ownership is unchanged; individual path limits also apply. No arbitrary aggregate dictionary cap is introduced. | [Tools notes](../../audit/remediation/tools.md) |
| AUD-014 | Conversion/measurement preflight covers every final output, metadata/count/table destination, inode/symlink alias and lexical/resolved ancestor overlap. Unique owned temporary files stage the whole bundle; handled publication failures restore old outputs. | [Fault-injection and preservation regressions](../../py/tests/test_audit_remediation.py), [Python notes](../../audit/remediation/python.md) |
| AUD-015 | Pending journals save collection boundaries. Recovery streams complete rows and requires exact authoritative row order after each boundary; only an owned incomplete final prefix can be repaired. Torn bytes are preserved and journalled before truncation. Interior/extra/reordered/corrupt rows reject. | [Every-byte interruption and peer-review regressions](../../py/tests/test_audit_remediation.py) |
| AUD-016 | Retention-oracle PAD deltas are applied by one prefix sum instead of repeated suffix rewrites. | [Independent scalar comparison and structural work bound](../../py/tests/test_audit_remediation.py) |
| AUD-017 | Independent aligned record sizes use u32, supporting the full u16 payload range. Parser-version-1 caches are invalidated and rebuilt as version 2. | [Large-payload/cache regressions](../../py/tests/test_audit_remediation.py) |
| AUD-018 | T2 preserves configured duration and validates constituent workload/process agreement. New version-2 cohort identities include duration and workload/source identity; the independent auditor retains explicit historical version-1 compatibility. | [Python notes](../../audit/remediation/python.md), [independent saved-output auditor](../../scripts/check_p6_experiments.py) |
| AUD-019 | Standalone acceptance requires explicit true measurement controls and exact repetition labels. An optional expected manifest checks absent/unexpected configurations; otherwise the result states `supplied-rows-only` and leaves campaign coverage unverified. | [Acceptance helper](../../py/tiplog_py/exp/audit.py), [regressions](../../py/tests/test_audit_remediation.py) |
| AUD-020 | Partial posting-block boundaries are counted exactly using binary search. Auto's policy is unchanged; the reproduced sparse recent range now chooses Indexed and fetches one record instead of Scan's 4,001. | [Core notes](../../audit/remediation/core.md) |
| AUD-021 | Registry mutation is guarded for the complete observer transaction. Nested `intern`/`observe` reject before mutation; reads and observer-handle reset remain supported. | [Core callback/rollback regressions](../../audit/remediation/core.md) |
| AUD-022 | Evidence writers check final flush/close errors and fail explicitly. This includes final benchmark branches, layout frontends, CC-5, worked examples and microbenchmark manifests. | [Tools `/dev/full` and success-path regressions](../../audit/remediation/tools.md) |
| AUD-023 | Both synthetic C++ harnesses use a checked payload-mixture parser, including strict row semantics and cumulative uint64 overflow checks before workload publication. | [Tools notes](../../audit/remediation/tools.md) |
| AUD-024 | Simulator Auto fractions must be finite and within `[0,1]` before backend selection; recording mode cannot bypass the check. | [Tools CLI regressions](../../audit/remediation/tools.md) |
| AUD-025 | Quiescence validation selects the exact accepted attempt and verifies its saved status/acceptance/log identities. The eligibility fields consumed from the campaign record are bound to the accepted status record. | [Quiescence checker](../../scripts/check_p7_runtime_quiescence.py), [regressions](../../tests/scripts/test_quiescence.py) |
| AUD-026 | All four derived analysis artifacts were reconstructed exactly to frozen accepted identities, divergent copies retained, and canonical accepted files restored. Output redirection and explicit evidence-workspace resolution prevent the demonstrated reporting failure from recurring silently. | [Reconstruction](../../audit/remediation/reconcile-baseline.json), [semantic comparison/restoration](../../audit/remediation/reconcile-semantic.json) |

## Additional observations addressed

| Observation | Implemented resolution |
|---|---|
| OBS-01: benchmark failure taxonomy | Known configuration rejection retains `invalid_config`. Timed/untimed disagreement emits `validation_failure`; unexpected execution failure emits `runtime_error`. Internal failures make the process exit nonzero and cannot pass the independent expected-outcome audit. Existing explicit Indexed representation-limit rejects remain expected configuration outcomes; Auto retains its fallback. |
| OBS-02: M3 preparation/resident references | Google Benchmark filtering precedes fixture preparation. Only selected B values construct pools; a no-match filter avoids opening the trace. Build-only chronological/per-partition references are released after independent validation. Verify-only behavior remains explicit. |
| OBS-03: prefill CLI flag | `--measure-prefill` is retained as a documented compatibility alias expressing intent. Prefill timing/emission remains unconditional, preserving existing callers and artifact semantics. |
| OBS-04: optimizer preparation resources | Both layout frontends enforce aggregate input, curve, preparation-work and membership budgets before the corresponding allocation/work. Final defaults are compatible with all frozen input batches; details follow. |
| OBS-05: automated enforcement | [Local checks](../../scripts/check_all.sh) include package and script regressions. The new [CI workflow](../../.github/workflows/checks.yml) configures/builds/tests all four presets, runs Python/script checks, checks dependencies and performs bounded fuzzer smoke tests. This is the implemented workflow, not a claim that a hosted run has completed. |

The detailed tools evidence and compatibility checks are in [tools.md](../../audit/remediation/tools.md).

## Resource and compatibility decisions

Topic limits intentionally narrow accepted input: paths over 4,096 encoded UTF-8 bytes or 128 segments reject. Exact limits remain accepted. Subscriptions validate all terms before interning any of them, preventing a later invalid term from registering earlier valid terms.

`Ring::at_checked` is intended for arbitrary caller-supplied locators and costs O(retained items). Callers that already have a proven retained boundary keep O(1) `Ring::at`; alignment and range alone do not prove that precondition.

The layout frontend defaults are:

| Limit | Default | Scope |
|---|---:|---|
| `--max-input-bytes` | 134,217,728 (**128 MiB**) | Entire input stream, including comments/separators |
| `--max-curve-entries` | 2,000,000 | Aggregate retained global-curve entries |
| `--max-prepare-work` | **200,000,000** | Aggregate conservative preparation work across CASE records |
| `--max-prepared-entries` | 2,000,000 | Materialized node/class memberships in a prepared case |

The library's default per-call preparation work budget is 100,000,000, with 2,000,000 memberships; explicit `PreparationLimits` remain available. These are logical input/work/storage budgets, not an exact process RSS guarantee. Preparation remains outside reported solver time; exact arithmetic and solver state/work/time caps are unchanged.

[Read-only compatibility preflight](../../audit/remediation/tools/frozen-budget-preflight.json) checked all 32 frozen P7 input batches and 24 global-curve batches. Maximum input size was 88,718,316 bytes; maximum aggregate preparation work was 120,300,000. They fit the final **128 MiB / 200M** defaults. The earlier proposed 64 MiB / 100M defaults were rejected because they would exclude an existing frozen batch. Larger intentional offline jobs can select explicit frontend budgets.

New prepared plans and T2 aggregate rows declare `t2_group_identity_version=2`. The independent auditor reconstructs those identities from authoritative request/case fields. Missing version denotes the historical version-1 evidence format; unsupported versions reject. Historical rows and group identifiers are not rewritten. Configurable 1/10/20/60-second regression cohorts check both replay rates and the writer contribution charged once to the reader group.

Legacy pending journals without byte offsets retain prior complete history and recognize a contiguous exact prefix of their authoritative pending rows; subsequent rows must continue that sequence. New journals record boundaries explicitly. Damaged interior records or ambiguous/unrelated tails fail instead of being silently discarded.

Multi-output staging restores prior artifacts on handled publication failures. Each rename is atomic, but process termination/power loss between several filesystem renames cannot make the whole bundle atomic. Source paths are never used as temporary write targets; owned old-file backups are retained if rollback itself cannot complete.

## AUD-026 reconstruction and restored evidence

The preserved pre-remediation analysis implementation regenerated the four P6 derived files from the immutable saved observations and their available frequency sidecars. **Every regenerated SHA-256 matched its frozen accepted identity exactly**, after which the accepted files were restored to canonical `results/derived/` paths. The divergent copies remain under `build/remediation/retained/derived/`.

| Restored artifact | Accepted SHA-256 |
|---|---|
| `tip-summary.json` | `ec27e7f3cb5050c61e54fad211708fd64f45fa297af215f8a2c39a4412d4bccb` |
| `tip-statistics.csv` | `7b728d08490344bef5eb1f0bda25a99450048c9a4a1b8e0ea6030e0880002549` |
| `tip-outcomes.csv` | `ca13ebcd1a7457c8a865970a043a4b06ed35a56eb42cca0f218170f905ae3e24` |
| `tip-paired-ratios.csv` | `678ca1b40b1308c7d73372cbba3fa0ddb700563b36a23fb5e74fe10cf865c866` |

The [semantic comparison](../../audit/remediation/reconcile-semantic.json) found changed noise counters in **6,542 configurations** and their corresponding CSV columns; all other summary fields and numerical/statistical fields were identical. The paired-ratio file was already identical. Reconstructed noise evidence covers 125,700 measured rows, with 74,935 flagged; all rows remain retained. No raw measurement was changed. This establishes the content difference and its correction; the original invocation that produced the divergent files is not asserted.

Future redirected figure builds place their analysis beside the redirected output by default, with `--summary-output` for an explicit destination. Analysis and P6 figure APIs accept `--evidence-root`: relative sidecar references resolve exclusively against the declared workspace, and a missing referenced sidecar fails before derived output is written. Legacy diagnostic mode keeps missing evidence explicit as unknown. These controls prevent a copied analysis implementation or redirected figure run from silently writing the canonical summary or borrowing an unrelated workspace's sidecar.

## Validation status

All final checks passed. Earlier focused checks are supporting evidence; the final matrix below validates the combined source. JUnit results contain zero failures, errors or skips.

| Final check | Status / count |
|---|---|
| Debug CTest | **205/205 passed** — [JUnit](../../audit/remediation/debug.xml) |
| Release CTest | **205/205 passed** — [JUnit](../../audit/remediation/release.xml) |
| ASan/UBSan CTest | **205/205 passed**, leak detection enabled — [JUnit](../../audit/remediation/asan.xml) |
| Fuzz-preset CTest | **205/205 passed**, leak detection enabled — [JUnit](../../audit/remediation/fuzz.xml) |
| Complete Python package/script regressions | **259 passed** (225 package + 34 script cases) — [JUnit](../../audit/remediation/python.xml) |
| Python package from CWD `py/` | **225 passed** — [JUnit](../../audit/remediation/python-from-py.xml) |
| Differential independent-oracle campaign | **108,000,000 operations passed**: 1,000 Release and 200 sanitized seeds × 10,000 operations in each of nine supported pairs; equal digests within each cohort — [summary](../../audit/remediation/core/final-validation/summary.json) |
| Fuzzer smoke checks | **10,000 runs each**, all three targets, ASan/UBSan/leak checks enabled; original corpora unchanged and no crash artifacts — [independent verification](../../audit/remediation/core/final-validation/independent-final-check.json) |
| Layout oracle and worked example | **10,000 cases each** in Release and ASan/UBSan, matching historical results exactly; worked examples byte-identical — [closeout](../../audit/remediation/tools/layout-closeout.json) |
| Independent saved-output auditor self-test | Passed both historical/new T2 identities and 13 evidence-tampering controls; temporary synthetic processes only — [command records](../../audit/remediation/checks/) |
| P6 raw measurement preservation | **5,364/5,364 files unchanged**, 4,105,957,437 bytes — [verification and provenance limits](../../audit/remediation/tools/frozen-p6-measurements.json) |
| Current-source remediation gate | **Passed, zero failures** — [acceptance](../../audit/remediation/acceptance.json), [result](../../audit/remediation/checks.json) |

Already executed focused evidence includes the three killed invariant-checker mutations, a deterministic 1.2-million-operation differential sample over all 12 mode/kernel combinations, independent Auto/Scan outcome equivalence, every-byte journal recovery, multi-output fault injection, payload/cache boundaries, mocked acquisition checks and frozen-budget compatibility. Logs and exact invocations are indexed in the [core](../../audit/remediation/core.md), [Python](../../audit/remediation/python.md) and [tools](../../audit/remediation/tools.md) notes. Final integrated command records live under [audit/remediation/checks/](../../audit/remediation/checks/).

Seventeen script regressions exercise the new current-source verifier itself: altered logs, wrong commands, stale/changing tested sources, disabled sanitizers, failed/skipped/empty/duplicate JUnit cases, unreviewed sources, missing prerequisites and exact dependency coverage. Command records bind their inputs before and after execution. The gate rehashes the original raw files, retained binaries, current sources, frozen derived/figure artifacts and cited evidence; it does not accept a saved success flag alone.

Short local fanout, planner and fuzzer-harness comparisons are diagnostics only. They do not establish new quiet-host engine throughput, campaign timing or full-length fuzz-gate results. The original performance tables remain associated with their historical source and host observations.

## Reproducing current checks

Use a compatible CPython 3.14 interpreter on Linux x86_64 for the locked wheel set. Follow the [current setup](../../README.md#python-setup), then run from the repository root:

```sh
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r py/requirements.txt
.venv/bin/python -m pip check
scripts/check_all.sh
```

The CI/audit tools have a separate hash-locked [requirements file](../../configs/ci-requirements.txt). The local test runner saves fresh command/log records and does not run controlled performance campaigns. Sanitizer runs require an execution environment that supports their runtime checks; the final sanitizer checks ran outside tracing with `ASAN_OPTIONS=detect_leaks=1:abort_on_error=1` and `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1`.

Use the separate [current remediation checker](../../scripts/check_remediation.py) and its [acceptance artifact](../../audit/remediation/acceptance.json) for the corrected tree:

```sh
.venv/bin/python scripts/check_remediation.py
```

This verifies the reviewed snapshot; later source edits require fresh affected evidence and a separately reviewed inventory. The one-time [phase inventory assembler](../../audit/remediation/build_acceptance.py) records this remediation phase and does not replace verification. Use [REPRODUCE.md](REPRODUCE.md) for the preserved historical experiment ledger and its local-data requirements.

Implementation stopped after these corrections. F-01 remains unimplemented; the engine replay/tail source files are byte-identical to the remediation-start baseline, as recorded in [scope confirmation](../../audit/remediation/core/scope-confirmation.json).

Copied/mutated fuzz corpora, crash-artifact directories and fuzzer byte-dictionary logs remain ignored local evidence. Command/statistics/hash summaries are reviewable; the saved-data verifier still requires the original local raw measurements and retained evidence described above.
