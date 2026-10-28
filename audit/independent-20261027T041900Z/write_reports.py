#!/usr/bin/env python3
"""Render this run's final human reports from retained evidence."""
import collections
import json
from pathlib import Path
import xml.etree.ElementTree as ET

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[1]


def main():
    ledger = json.loads((RUN/'findings.json').read_text())['findings']
    tests = list(ET.parse(RUN/'evidence/python-accepted.xml').getroot().iter('testcase'))
    python_count = len(tests)
    classes = collections.Counter(x.get('classname') for x in tests)
    focused = sum(n for name,n in classes.items() if name in ('test_build_provenance','test_f01_checker','test_f01_fixture'))
    perf = json.loads((RUN/'evidence/performance.json').read_text())
    control = json.loads((RUN/'evidence/performance-followup.json').read_text())
    findings_table = '\n'.join(f"| {x['id']} | {x['severity']} | {x['title']} | [Verified]({x['detail']}) |" for x in ledger)
    (RUN/'REPORT.md').write_text(f'''# Independent project audit and remediation

Run `independent-20261027T041900Z`; completed 28 October 2026 (Asia/Kolkata).

Authorized remediation is complete: **14 confirmed, 14 fixed, 14 verified, zero unresolved confirmed findings** (10 medium, 4 low). This is a systematic, bounded audit, not a claim that every possible bug has been eliminated. The machine-readable [ledger](findings.json), detailed [findings](findings/), [coverage](COVERAGE.md), [performance](PERFORMANCE.md), [reproduction](REPRODUCE.md), and separate [current-source acceptance](acceptance.json) define the result.

## State, scope and independence

The initial Git HEAD was `aa13c1824ba5a7a3593a0f63c6f455cac851e822`, with substantial pre-existing uncommitted P5–P8, audit and F-01 work. The audit used `scripts/git.sh` and `.tiplog-git`; it did not reset, clean, commit, push, deploy, download datasets or alter managed `.git` metadata. [Initial status](initial/status.txt), [binary diff](initial/diff.txt), [226-file source inventory](initial/source-manifest.json), source archive and [42 auxiliary source identities](initial/auxiliary-sources.json) preserve that state. New changes are separately identified by the final freeze and change inventory. No applicable repository AGENTS.md was found. An inherited `git diff --check` warning about a blank line at the end of `docs/plan/PROGRESS.md` is unchanged from the initial source; the audit patch introduces no trailing whitespace.

Three independent reviewers covered core C++, Python/evidence, and layout/parsers/tools/builds; root reviewed F-01 evidence and integrated remediation. Findings were recorded before their corrections. Important fixes received independent review. Review exposed additional boundaries in the uint64 retention oracle, leading-PAD fixture model, indirect sanitizer suppression, test-selection environment and acceptance composition; those corrections and failed attempts remain in this directory.

The architecture, implementation/validation/reproduction documents, prior audits/remediation and F-01 polling contract/results were examined together with callers and tests. Historical passing gates were treated as evidence to examine. The accepted traversal-only polling contract and its compatibility rules remain intact. Repeated cursor preparation is still outside the inspection cap; it was measured and retained as an explicit tradeoff.

## Findings and changes

| ID | Severity | Confirmed issue | Final status/detail |
|---|---|---|---|
{findings_table}

Tail now retains its private delivered-prefix sequence when an append throws, so a later expiry error reports the actual prefix; public exception caches and unread retry behavior retain their documented contract. Trace indexing rejects impossible metadata before count-sized allocation and cleans failed construction. Writer/analysis staging is cleaned or rolled back on handled failures. Retention arithmetic rejects invalid/overflowing inputs and preserves exact uint64 searches beyond floating-point precision.

Tools reject destructive path aliases, malformed/inapplicable options and read/write failures; a valid request named `id` executes. Google Benchmark's pinned archive remains unchanged; a deterministic SHA-checked local source patch propagates its owned result-file flush/close failures after timing. [Patch evidence](evidence/layout_tools/dependency-patch-check.json) covers original/patched identity, idempotence and unexpected-source rejection.

The maintained F-01 validator independently reconstructs deterministic topic IDs, payload bytes, DATA/PAD positions, candidate/output counts, digest, final range, effective mode and preparation-resource feasibility. Historical result scripts remain unchanged. Build evidence now binds actual executables, compiler/configuration/compile database and patched dependency to successful full builds. Required preset instrumentation, hidden compilation inputs/suppression controls and full-suite environment controls are enforced. These are local provenance checks, not malicious-host attestation.

## Final validation actually executed

| Final check | Result |
|---|---|
| Debug, Release, ASan/UBSan, fuzz configure/build/CTest | **230/230 each**, no failures/errors/skips; final selector-environment-aware runs supersede earlier matrix results |
| Full Python package/script suite | **{python_count} passed**, no failures/errors/skips; exact sources stable during execution |
| Provenance/F-01 checker/independent fixture regressions within that suite | **{focused} cases**; includes meaningful negative controls |
| Legacy independent differentials | **108,000,000 operations**: 9 supported mode/kernel pairs × (1,000 Release + 200 sanitized seeds) × 10,000 operations |
| Independent budget-aware model | **12,000,000 operations**, all 12 mode/kernel choices represented; separate **2,000,000 Release operations** exactly match the sanitized cohort's counters/digest |
| Fuzzing | **10,000 runs each on all four targets**, private writable corpora; ASan/UBSan/leak checks enabled; historical corpora unchanged |
| Allocation/exception/lifetime | 24 polling tests; independent 74-configuration/538-failure-point campaign, including registry rollback, aliased publication, Replay/Tail retry; independent 2,046 Python retention boundary cases |
| Exact layout + worked example | Fresh Release and sanitizer **10,000-instance CC5** results, 57,461 exact-count + 57,461 at-most comparisons/build; worked examples and CC5 outputs byte-identical to preserved historical values |
| Supplementary audit tests | 5 layout and 3 trace tests pass, including larger rational cases, 20,000 trace mutations and 2,000 chunk campaigns |
| Evidence checks | All **2,274** historical F-01 timing rows independently revalidated; summaries match original statistics; frozen P7 quiescence rechecked **11/11** |
| Current comparisons | **192 primary timing rows** plus **160 counterbalanced/CPU-affined follow-up rows**, all equivalent-work/output checks pass |
| Dependencies/tooling | `pip check` and independent saved-output auditor self-test pass; four actual preset configurations/instrumentation verified |
| Preservation | **4,262 historical artifacts** and **5,364 P6 raw files / 4,105,957,437 bytes** rehashed unchanged; Git HEAD unchanged |

The final command/log/JUnit records are under [evidence](evidence/), and the [acceptance verifier](acceptance.py) checks exact commands, source sets, binary/config identities, test inventories, output destinations, raw/derived bindings and preservation. Sanitizers ran through the required outside-tracing execution mechanism with leak detection enabled; no sanitizer suppression was used to obtain a pass. Deliberately suppressed/sharded/filtered negative controls are separate from accepted evidence.

C++ inputs remained stable after the final build. Later changes affected Python evidence validation and documentation; C++ campaigns reuse those unchanged compiled-input and binary identities. The final Python/CTest suites were rerun after the final verifier/environment corrections. Earlier intermediate suites, original-source negative controls and failed attempts are supporting evidence, not relabeled as final runs.

## Performance and remaining uncertainty

No throughput improvement or universal nonregression is claimed. The actual initial/final binary comparison uses the same GCC flags, input/output/service policy and timing boundaries. Primary paired poll-time ratios ranged **0.939–1.775**; all slower cases remain reported. A predeclared 10-pair, counterbalanced child-affinity follow-up ranged **0.958–1.195** across eight arms. That narrower result does not prove the original losses were noise or establish deployment performance. [PERFORMANCE.md](PERFORMANCE.md) retains all arms, process observations, CPU/wall time, percentiles/sample counts, memory and limitations.

Large Indexed selections still pay repeated setup at small budgets. No unsafe removal of validation, cursor-lifetime checks or approved contract change was used to reduce cost. Analysis output staging can temporarily retain old and new bundles; handled failure rollback is tested, while power-loss/multi-file crash atomicity is outside the contract.

No new full-day data conversion, quiet-host P6/P7 campaign, historical full-duration fuzz gate, hosted CI execution or online vulnerability advisory refresh is claimed. Raw datasets and vendored libraries were not line-by-line first-party audits; pins, the local dependency patch, framing/integrity tests and preservation checks cover their stated boundary. Local toolchain/system libraries and truthful host execution remain trust assumptions. Concurrency, durability, adversarial concurrent path replacement and Tier-C/roadmap features remain outside scope. Potential untested inputs, allocator schedules and platform behavior remain uncertain; zero unresolved confirmed findings does not mean zero possible defects.
''')
    (RUN/'COVERAGE.md').write_text('''# Coverage matrix and exclusions

| Area | Reviewed together | Newly executed evidence | Boundaries |
|---|---|---|---|
| Ring/storage | Alignment/size framing, DATA/PAD, wrap, FIFO retention, sequence/logical overflow, checked/unproven locators, publish rollback/aliasing | Four full CTest configurations; allocation probes; legacy/budget differentials; engine and polling fuzz targets | Finite campaigns, single-threaded lifetime rules; no concurrent mutation guarantee |
| Index | Block sizing/pools, pressure policies, generations/recycling, stale cursors, seek/count, gauges/ownership | Index/engine tests, low-pool/stale/failure probes, wrapping/expiry random schedules | No assertion of exhaustive generation/allocator states |
| Registry/subscriptions | Registration/observer transaction and rollback, limits, dynamic growth, exact/subtree normalization, filtering/ownership | Registry/subscription suites, 538 injected failure points across core probes, dynamic-topic campaigns | Documented path/depth bounds retained |
| Merge/planning | All four kernels, ordering/duplicates/sentinels/packed limits, Auto threshold/range selectivity, setup | Merge tests, independent mode/kernel campaigns, equivalent-output timing arms | Packed limits and Auto fallback preserved; no new kernel/policy |
| Replay/Tail/F-01 | Captured ranges/checkpoints, moves, expiry, payload lifetimes, zero/absent/max/changing limits, exact rejected/DATA/PAD/posting+fetch charging, output precedence, shared rollover allowance and cumulative work | 24 focused tests; all supported legacy pairs; 12-way independent logical model; private fuzzing; first/second append failures and eviction retry | Public exception cache lag remains documented; inspection cap excludes opening/seeking/planning/allocation |
| C++ trace/ITCH/driver | Bounds/count/dictionary/UTF-8 checks, original framing, EOF/terminator offsets, mmap ownership and callback error propagation | Trace/driver tests, 20,000 mutations/2,000 chunk campaigns, two parser fuzz targets | Existing immutable mapped-input validation contract retained; no full-day parse rerun |
| Layout/numerics | Independent evaluator, scaled/rational overflow, ENUM/DP pruning/reconstruction/limits, KM endpoints, global certificates and incomplete domains | 10,000 CC5 cases/build, worked example, 1,500 larger rational and 2,000 global supplemental cases | Exact feasible-set coverage remains conditional; no promotion of timeouts/heuristics to exactness |
| CLI/microbenchmarks | All command frontends, request/payload parsing, output aliases/read and flush/close errors, arguments/exit statuses, benchmark timing boundaries | 13 CLI contract groups inside each full CTest; frozen/current red and compatibility controls; deterministic dependency patch checks | Paths must remain stable during invocation; host/allocator effects disclosed |
| Python data/experiments | ITCH/gzip/trace readers/writer, acquisition checksum, oracle/native byte hash, retention, synthetic generation, journal/recovery, normalization/cohorts | Full package/script suite, malformed/allocation/staging failures, 2,046 independent high-u64 scalar cases, original-source negative controls | No download/full reconversion; invalid huge cases bounded rather than exhausting resources |
| Analysis/statistics/figures | Whole-round/bootstrap/paired ratios, missing/failed cohorts, sidecars, exact fractions/coverage, complete output write sets and rollback | Full tests; source/output and output/output alias controls; preserved accepted statistics; P7 quiescence recheck | Observational intervals and modeled bytes keep their original limitations; no fresh historical figure regeneration |
| Build/CI/evidence | Presets/dependency pins/CI definition, recorder/checker/assembler, benchmark arm equivalence, source/binary and actual instrumentation binding, selector/repeat/sharding/plugin controls | Four configure/build/test presets; helper/checker/fixture negative controls, independent auditor self-test, acceptance composition controls and fresh hashes | Hosted CI not run; local provenance is not signed or malicious-host attestation |
| Documentation | Architecture/implementation/validation/reproduction, README/current acceptance references, previous audits/remediation and F-01 contract/results | Context corrections, report/ledger/reproduction/current gate; historical identity preservation | Historical dated reports/results preserved; their measured numbers are not current-source measurements |

## Inventory and ownership

The initial first-party inventory contains 226 files (2,568,745 bytes): 25 under src, 48 under py, 13 tools, 39 tests excluding corpus, 41 scripts, 4 bench, 13 cmake, 4 configs, 28 docs, CI and root build/project documents. Forty-two auxiliary Python sources beside historical results/audits were separately inventoried/archived and reviewed in their relevant slices. The current freeze lists every source/document identity and separates C++ and Python dependency sets; it also identifies existing corpus inputs without treating mutated private copies as production source.

Generated build trees, caches, binaries, figures/derived tables, historical logs, private fuzz outputs and virtualenv installed packages are not project-owned source. Verified dependency archives and their generated source trees are vendored inputs; one explicit SHA-checked Benchmark finalization patch is project-owned and reviewed. Nasdaq raw inputs/traces and raw campaign datasets are data, not code. They were not downloaded or republished. Existing data/measurement manifests, input validation/fuzzing and read-only preservation cover their declared scope. Educational interview/plan documents were treated as documentation; they do not override implemented contracts or expand implementation scope.

All important corrections have independent review evidence in the core/python/layout_tools slices. No source area is claimed exhaustively proved by the tests in this table.
''')
    (RUN/'REPRODUCE.md').write_text('''# Reproduction and evidence identities

Run from `/home/abc/Desktop/Jane Street`. Use `scripts/git.sh` for this workspace. Do not rerun historical writers into accepted result paths. The current [acceptance.json](acceptance.json) binds the final [source freeze](source-freeze.json), [artifact manifest](artifact-manifest.json), and command/log records. GCC 15.2, Clang 21.1.8, CMake 4.4 and the project virtualenv were used; exact compiler executables, cache/compile flags and hashes are in each final build record. Initial environment capture and manifests are under `initial/` and `evidence/initial-environment-*`.

## Recheck the retained final evidence

```sh
.venv/bin/python audit/independent-20261027T041900Z/acceptance.py
```

This performs read-only source/binary/raw checks and reconstructs summaries; it writes only this run's current acceptance/artifact inventory. It intentionally rejects later source/build changes. It does not regenerate old phase gates.

## Rebuild/retest in a fresh evidence namespace

```sh
cmake --preset debug
cmake --build --preset debug --parallel 2
ctest --preset debug --parallel 2 --no-tests=error --output-junit /tmp/tiplog-debug.xml
# Repeat for release, asan-ubsan and fuzz.
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -c py/pytest.ini py/tests tests/scripts -q
.venv/bin/python -m pip check
.venv/bin/python scripts/check_p6_experiments.py --self-test
```

Keep ASan/UBSan/leak checks enabled. In this managed environment sanitizer execution used the tool approval mechanism to run outside tracing, with `ASAN_OPTIONS=detect_leaks=1:abort_on_error=1` and `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1`. Full-suite evidence requires explicitly empty/unset GoogleTest filter/shard/repeat/Bazel selection, CTest selection and pytest option/plugin variables, plus disabled plugin autoload. The recorder captures these settings rather than accepting missing metadata.

The exact independent campaigns are executable in [campaigns.py](campaigns.py): 1,000 Release and 200 sanitizer seeds, 10,000 operations/seed, all nine legacy pairs and the budget-aware model. Its saved summaries list each exact command and bound record. Choose a fresh directory/labels before rerunning: the original harness deliberately refuses existing corpus/evidence namespaces. Fuzz corpora are private copies (up to128 historical seeds/old target,64 deterministic new-grammar seeds); seeds and fuzzer arguments including fixed seed20261027 are in each record. Do not point fuzzers at historical corpora.

For standalone layout checks, use the exact argv in final-layout-* records with new output paths: `tiplog_layout_cc5 --instances 10000 --seed 20191230`; the worked example has its own frontend. Core failed-allocation reproducers, Python scalar/high-u64 controls, old-source red controls and dependency patch negative controls are retained under their respective evidence slices.

## Source, performance and preservation

The initial source archive plus auxiliary-source archive preserve pre-existing uncommitted source. `initial/status.txt`, `initial/diff.txt` and initial hashes describe it. The final source freeze/change inventory identifies this audit's edits without relying on HEAD alone. The actual pre-change benchmark was built from that initial archive, not selected as an API path on the changed binary. Its archive/compiler/flags/binary identities are in `evidence/layout_tools/baseline-poll-bench-identity.json`.

Both performance protocols were written before their timing. [run_performance.py](run_performance.py) and [performance_followup.py](performance_followup.py) retain original files, normalization maps, fresh process labels and host observations. They refuse existing output namespaces; choose new paths before repeating them. Every arm and non-winning result remains in PERFORMANCE.md and JSON evidence. These are shared-host diagnostics, not replacements for controlled P6/P7 historical measurements.

[verify_preservation.py](verify_preservation.py) rehashes the 4,262-file historical manifest and original 5,364-file P6 raw inventory, checking size/SHA-256/unique paths. The acceptance verifier independently rechecks these identities. No acquisition or source dataset rewrite is necessary. Original measurements and report/gate hashes remain preserved; the final source has its own acceptance.
''')
    rows = []
    for x in perf['comparisons']:
        rows.append(f"| {x['case']} | {x['shape']} | {x['configured_partitions']} | {x['budget']} | {x['initial_poll_ns']/1000:.3f} | {x['final_poll_ns']/1000:.3f} | {x['paired_poll_ratio']:.3f} | {x['initial_drain_ns']/1000:.3f} | {x['final_drain_ns']/1000:.3f} |")
    controls = '\n'.join(f"| {x['configured_partitions']} | {x['budget']} | {x['initial_poll_ns_median']/1000:.3f} | {x['final_poll_ns_median']/1000:.3f} | {x['paired_ratio_median']:.3f} |" for x in control['comparisons'])
    (RUN/'PERFORMANCE.md').write_text('''# Actual before/after diagnostics and tradeoffs

No performance improvement or universal nonregression is claimed. The primary experiment compares two separately built implementations: the preserved initial source and the final C++ source, both GCC15.2, `-O2 -g -march=x86-64-v3 -DNDEBUG`. It is not a comparison of two API paths on one changed binary. All32 workloads and non-winning observations are retained below. [Protocol](evidence/performance-protocol.json), [raw/normalization/process evidence](evidence/performance.json) and initial archive/binary identities make the comparison reproducible.

## Method

4096 DATA records, no-match/dense, small/wrapped-variable payloads, K64/K256, Indexed/StdPQ, budgets legacy/unlimited/1/32, output allowance128, seed20261027. Every arm uses immediate redrain and exactly one victim-reader and separate-engine publisher service after completion. Inputs, outputs, work counters, checkpoints, call counts and service policy are equal between source builds. Three fresh processes/source run in alternating initial/final pairs. The fixed seed/arm order and warm OS caches are retained. No process affinity, cache flushing or host-setting change was used in the primary run. Project-owned builds/tests/campaigns had finished before timing; the host remained shared, with observed load around1.2–3.2 in the saved host snapshots.

The experiment contains192 timing rows (32arms ×3processes ×2sources). Original tool repetition0 rows stay intact; derived files change only the process repetition label. Per-process nearest-rank percentiles are summarized by their median, with actual sample counts retained. The paired poll ratio is the median of three per-pair final/initial ratios; it need not equal a ratio of separately calculated medians.

Opening is measured separately. Public-poll latency includes internal preparation. Cumulative poll time excludes output hashing/caller service; drain CPU/wall include those operations. JSON evidence retains every opening, p50/p95/p99/max/sample count, cumulative work, CPU/wall and process peak RSS. Those RSS values are process-wide high-water observations across fixtures/arms, not an exact live fixture allocation or leak measure. Maximum reported primary peaks were35,463,168B initial and35,434,496B final; this small difference establishes no memory improvement.

## All primary workloads

Times are microseconds; initial/final columns are medians of three fresh-process observations. The ratio uses paired observations.

| Case | Shape | K | Budget | Initial poll total µs | Final poll total µs | Paired final/initial | Initial drain µs | Final drain µs |
|---|---|---:|---|---:|---:|---:|---:|---:|
'''+'\n'.join(rows)+'''

Primary paired ratios range0.939–1.775. The largest losses occur in the first K64/small/no-match fixture; they are not discarded or labeled proven noise. Static Replay's functional path was unchanged by the Tail diagnostic fix, but binary/layout, allocator, startup, CPU scheduling/frequency and host effects are not causally separated by these short observations. No stable throughput-regression conclusion follows either.

## Predeclared follow-up for the observed loss

The retained loss justified a bounded follow-up, not a replacement of the primary result. The [follow-up protocol](evidence/performance-followup-protocol.json) specifies ten fresh process pairs, counterbalanced source order and child CPU affinity to the first allowed CPU (CPU0), with the same4096-record no-match workload and K64/K256 budgets. All160 rows, every pair ratio and host observation remain in [follow-up evidence](evidence/performance-followup.json). No privileged host setting changed. This run occurred on28October after the primary27October observations.

| K | Budget | Initial poll total µs | Final poll total µs | Median of10 paired ratios |
|---:|---|---:|---:|---:|
'''+controls+'''

The follow-up ratios range0.958–1.195. It does not reproduce the original1.48–1.78 K64 loss magnitude, while retaining slower outcomes. Affinity/order/date changed together, so this does not prove which cause mattered, prove the first result was noise, or establish deployment nonregression. Further host-controlled inference remains a limitation, not a confirmed unfixed implementation bug.

## Cost mechanism retained by design

On the final primary K256/small/no-match fixture, legacy uses one poll and256 index seeks; budget32 uses128 polls/32,768 seeks; budget1 uses4096 polls/1,048,576 seeks. Cumulative poll medians are133.738µs,1,221.485µs and19,739.586µs respectively. Budget1's per-process p99 median is6.413µs versus legacy's single133.738µs call. These API-path comparisons on the same final binary explain the traversal/preparation tradeoff; they are separate from the actual source before/after table. A budget is not a complete-call deadline, and immediate redrain supplies no interleaved service benefit. No cursor/filter lifetime checks or approved semantics were removed to improve this timing.

The malformed-trace allocation correction also has direct structural before/after evidence: a68-byte invalid input formerly created a260,192-byte cache; the corrected parser rejects before count-sized allocation. Cleanup removes owned staging on handled failures. These are measured/verified resource effects, not a claimed engine throughput speedup. Analysis staging temporarily retains old/new output bundles to protect data; crash atomicity across several renames remains outside the contract.
''')
    print(json.dumps({'reports':4,'python_tests':python_count,'focused_cases':focused}),flush=True)


if __name__ == '__main__': main()
