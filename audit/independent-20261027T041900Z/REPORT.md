# Independent project audit and remediation

Run `independent-20261027T041900Z`; completed 28 October 2026 (Asia/Kolkata).

Authorized remediation is complete: **14 confirmed, 14 fixed, 14 verified, zero unresolved confirmed findings** (10 medium, 4 low). This is a systematic, bounded audit, not a claim that every possible bug has been eliminated. The machine-readable [ledger](findings.json), detailed [findings](findings/), [coverage](COVERAGE.md), [performance](PERFORMANCE.md), [reproduction](REPRODUCE.md), and separate [current-source acceptance](acceptance.json) define the result.

## State, scope and independence

The initial Git HEAD was `aa13c1824ba5a7a3593a0f63c6f455cac851e822`, with substantial pre-existing uncommitted P5–P8, audit and F-01 work. The audit used `scripts/git.sh` and `.tiplog-git`; it did not reset, clean, commit, push, deploy, download datasets or alter managed `.git` metadata. [Initial status](initial/status.txt), [binary diff](initial/diff.txt), [226-file source inventory](initial/source-manifest.json), source archive and [42 auxiliary source identities](initial/auxiliary-sources.json) preserve that state. New changes are separately identified by the final freeze and change inventory. No applicable repository AGENTS.md was found. An inherited `git diff --check` warning about a blank line at the end of `docs/plan/PROGRESS.md` is unchanged from the initial source; the audit patch introduces no trailing whitespace.

Three independent reviewers covered core C++, Python/evidence, and layout/parsers/tools/builds; root reviewed F-01 evidence and integrated remediation. Findings were recorded before their corrections. Important fixes received independent review. Review exposed additional boundaries in the uint64 retention oracle, leading-PAD fixture model, indirect sanitizer suppression, test-selection environment and acceptance composition; those corrections and failed attempts remain in this directory.

The architecture, implementation/validation/reproduction documents, prior audits/remediation and F-01 polling contract/results were examined together with callers and tests. Historical passing gates were treated as evidence to examine. The accepted traversal-only polling contract and its compatibility rules remain intact. Repeated cursor preparation is still outside the inspection cap; it was measured and retained as an explicit tradeoff.

## Findings and changes

| ID | Severity | Confirmed issue | Final status/detail |
|---|---|---|---|
| CORE-01 | medium | Tail error loses delivered prefix after allocation failure | [Verified](findings/core.md) |
| PY-01 | medium | TraceIndex allocates from unvalidated record count | [Verified](findings/python_evidence.md) |
| PY-02 | low | TraceWriter finish failure leaks staging | [Verified](findings/python_evidence.md) |
| PY-03 | medium | Quiescence accepts absent or invalid samples | [Verified](findings/python_evidence.md) |
| PY-04 | medium | Analysis outputs overwrite input or sibling output | [Verified](findings/python_evidence.md) |
| PY-05 | low | Retention oracle invalid input, overflow and u64 precision | [Verified](findings/python_evidence.md) |
| TOOL-01 | medium | Tool outputs alias and corrupt input files | [Verified](findings/layout_tools.md) |
| TOOL-02 | medium | Request read errors become empty successful campaigns | [Verified](findings/layout_tools.md) |
| TOOL-03 | low | Malformed or ignored verification options | [Verified](findings/layout_tools.md) |
| TOOL-04 | medium | Valid request id skipped as header | [Verified](findings/layout_tools.md) |
| TOOL-05 | medium | Benchmark result-file write failure returns success | [Verified](findings/layout_tools.md) |
| F01-01 | medium | Forged benchmark digest and positions pass validation | [Verified](findings/f01.md) |
| EVID-01 | medium | Execution evidence lacks build and instrumentation binding | [Verified](findings/f01.md) |
| DOC-01 | low | Obsolete prospective/current acceptance wording | [Verified](findings/docs.md) |

Tail now retains its private delivered-prefix sequence when an append throws, so a later expiry error reports the actual prefix; public exception caches and unread retry behavior retain their documented contract. Trace indexing rejects impossible metadata before count-sized allocation and cleans failed construction. Writer/analysis staging is cleaned or rolled back on handled failures. Retention arithmetic rejects invalid/overflowing inputs and preserves exact uint64 searches beyond floating-point precision.

Tools reject destructive path aliases, malformed/inapplicable options and read/write failures; a valid request named `id` executes. Google Benchmark's pinned archive remains unchanged; a deterministic SHA-checked local source patch propagates its owned result-file flush/close failures after timing. [Patch evidence](evidence/layout_tools/dependency-patch-check.json) covers original/patched identity, idempotence and unexpected-source rejection.

The maintained F-01 validator independently reconstructs deterministic topic IDs, payload bytes, DATA/PAD positions, candidate/output counts, digest, final range, effective mode and preparation-resource feasibility. Historical result scripts remain unchanged. Build evidence now binds actual executables, compiler/configuration/compile database and patched dependency to successful full builds. Required preset instrumentation, hidden compilation inputs/suppression controls and full-suite environment controls are enforced. These are local provenance checks, not malicious-host attestation.

## Final validation actually executed

| Final check | Result |
|---|---|
| Debug, Release, ASan/UBSan, fuzz configure/build/CTest | **230/230 each**, no failures/errors/skips; final selector-environment-aware runs supersede earlier matrix results |
| Full Python package/script suite | **499 passed**, no failures/errors/skips; exact sources stable during execution |
| Provenance/F-01 checker/independent fixture regressions within that suite | **193 cases**; includes meaningful negative controls |
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
