# Layout, trace, command-line, microbenchmark and build review

This scope identified **5 confirmed findings; all 5 are fixed and pass focused verification; no confirmed finding remains unresolved in this scope**. The detailed before-fix ledger is [findings/layout_tools.md](../../findings/layout_tools.md). The parent audit records final whole-project acceptance independently. No source reset, commit, dataset download, primary historical result rewrite or managed `.git` change was performed.

## Corrections and compatibility

| ID | Severity | Correction | Direct evidence |
|---|---|---|---|
| TOOL-01 | Medium | Reject source/result file aliases, including hard links and symlinks, before any owned output opens. Covers CASE/global layout inputs, walker input, benchmark trace/requests/mix/term dictionary, and microbenchmark result/diagnostic outputs. Preserve normal explicit append/replace semantics for distinct files. | `baseline-probes.json`, `frozen-source-probes.json`, CLI alias/source-preservation assertions |
| TOOL-02 | Medium | Reject request stream read failures before returning parsed requests or creating result output. Empty regular files remain allowed. | Directory-source negative control in baseline probes and CLI assertions |
| TOOL-03 | Low | Use complete unsigned decimal conversions in M1 with checked `size_t` narrowing; reject ignored leftover options on all microbenchmark verification paths. | Numeric sign/suffix/whitespace/overflow controls; nonempty M3 verification control; valid UINT64_MAX seed comparison |
| TOOL-04 | Medium | Recognize only the complete documented TSV header. A request named `id` now runs normally. | `baseline-request-id.json`, regression requiring its replay row |
| TOOL-05 | Medium | Explicitly flush/check/close/check the Google Benchmark owned result stream through a deterministic project-owned patch to generated pinned dependency source. | `baseline-gbench-full.json`, `/dev/full` regression, valid JSON/metadata checks, dependency patch controls |

Production edits are limited to the shared file-identity helper, affected CLI entry points, and dependency finalization patch/inclusion. Solver/trace/driver implementations are unchanged. No exact-objective, budget, work limit, timing boundary, trace format, replay or polling API contract was changed.

The Google Benchmark 1.9.5 archive retains SHA-256 `f82705a2726d8f6cdcda274b841f6314dbfc6f731cdda06c946f310ec1cc3ad9`. Original `benchmark.cc` SHA-256 is `93dd058ff126b0e50f53f8d5d31d6fa5132b345b3132781c692b7d8538c72da3`; patched SHA-256 is `4fc57e51c4bf1aa76e8c61bc4538f4a00fce0f03dd96e8f8ba577870da16fce8`. Configure accepts exactly those two source identities, transforms/checks the original before writing, reuses the patched file unchanged, and rejects anything else. Exceptions must remain enabled for owned-file failure propagation; this is already the default in every supported preset.

Independent review found a compatibility edge in the new argument guard: a consumed custom input filename beginning `--benchmark_out=` must not become a Benchmark flag. The correction supplies filtered library arguments; the filename regression passes. The guard also follows the pinned library's `BENCHMARK_OUT` environment setting and last command-line override, and checks only actual output protocols in measurement mode.

## Coverage matrix

| Area | Review and newly executed coverage | Result / remaining boundary |
|---|---|---|
| `src/tiplog/layout/model.{hpp,cpp}` | Rational reduction/scaling, checked 128-bit arithmetic and sentinel, uint64 volumes, connected immediate-parent paths, zero nodes, union membership, independent materialization, baseline, threshold/hot-singleton rules and finite KM endpoints. Focused tests; CC5 10k; supplementary 3,000 evaluator, 1,500 brute-force threshold and 800 KM campaigns. | No new numerical defect established. Worst-case-bound rejection is intentional; preparation/materialization remain outside solver intervals. |
| `src/tiplog/layout/exact.{hpp,cpp}` | Enumeration Gray order, work/state preflight, arbitrary class incidence, mask representation guards, capped child convolution, zero components, stable ties, reconstruction, partial-result status and `at_most` refusing incomplete solves. CC5 plus 1,500 larger rational instances, up to 15 nodes / 6 classes, comparing every count. | 8,890 supplementary exact-count comparisons agree. Time/state/representation stops are not labeled exact. Logical limits are not exact RSS bounds. |
| `src/tiplog/layout/global.{hpp,cpp}` | Common rational scale, declared count domains, incomplete-curve certificate suppression, nonnegative penalties, own-budget optimality, signed lower bounds. Focused cases and 2,000 supplementary brute-force allocation cases. | No invalid optimum/certificate established; no inference from incomplete curves. |
| `src/tiplog/trace/*` | Header arithmetic, exact regions/counts, dictionary IDs/paths/UTF-8/depth/size, payload/padding bounds, complete-file validation, borrowed mapping ownership/moves; all 23 ITCH lengths, byte offsets, chunking, missing terminator and malformed tails. Focused tests + 500 generated valid traces, 20,000 mutations, 2,000 chunk campaigns. | 18,866 mutated inputs rejected, 1,134 validated/fully iterated; no unexpected exception. Immutable backing-file/span assumption remains explicit. |
| `src/tiplog/driver/*` | Sparse dictionary IDs, payload borrowing, dense callback sequence validation, pause range arithmetic, cadence/jitter/max-record limits, tick/digest accounting and callback failures. | All 5 focused driver tests pass. Actual valid-file byte counts bound driver payload/tick counters. |
| All `tools/*` except `tiplog_poll_bench.cpp` | Entire tool implementations and benchmark contracts read: option parsing, source reads, output modes/finalization, request taxonomy, SHA/FNV scope, synthetic distribution, simulator backend behavior, differential bounds and index allocator diagnostic. Caller/test review includes frontend aggregate budgets. | TOOL-01/02/03/04 fixed. Poll benchmark is owned by the parent audit. Large request/term inputs still require memory proportional to input; no unsupported universal end-to-end latency/RSS bound is claimed. |
| `bench/micro/*` | Input generation, deterministic schedules, independent digests, timing boundaries, Google Benchmark filters and fixture retention, env diagnostics, result output, verification modes and provenance. | TOOL-01/03/05 fixed; valid M1/M2/M3 verification output is byte-identical to frozen binaries. No new throughput claim. |
| Build/CI | All `cmake/*`, `CMakeLists.txt`, `CMakePresets.json`, `.github/workflows/checks.yml` read. Checked target/test wiring, pinned archives/system opt-in, warnings, sanitizer/fuzz links, PRE_TEST discovery, Python CLI CTest and CI suite shape. New patch tested with exact hashes, repeated configure and unexpected-source control. | Focused isolated Release build succeeds using existing verified archives. Parent owns complete preset/sanitizer/fuzz matrix. Remote CI itself was not triggered. |
| Prior evidence/docs | Read prior audit/remediation scope, architecture optimizer/trace contracts, validation/reproduction documents and F-01 contract/results. Historical measurements/gates are preserved. | Existing historical measurements were not regenerated. Plan sections with old prospective wording were reported to parent for documentation closeout. |

## Executed validation and identities

- `focused-tests.log`: **52/52** current Release CTests, including thirteen CLI regression groups. `focused-tests-first.log` preserves the initial failed remediation attempt; its unqualified `size` helper accidentally selected `std::size` via argument-dependent lookup. Renaming it `parse_size` fixes that error; the malformed-input tests then pass.
- `baseline-red-controls.json` / `.log`: all six selected regression groups fail against binaries freshly compiled from `initial/source-snapshot.tar`. `baseline-configure.log` / `baseline-build.log` retain the build. Old-source probes have explicit binary hashes.
- `functional-compatibility.json`: identical valid input/output comparisons for M1 maximum uint64 seed, M2 default verification and M3 trace verification; all stdout bytes agree. Separately confirms unknown M3 verification options were previously ignored with nonempty input.
- `dependency-patch-check.json`: original→patched exact hash, no-write idempotence, unexpected-source rejection, archive unchanged. `configure-repeat.json` adds a repeated full-configure no-write check.
- `release-layout-closeout.json`: **10,000 CC5 instances, zero mismatches, 57,461 exact-count comparisons, 57,461 at-most comparisons, 96,322 reconstructed layouts**. CC5 and worked-example output bytes match their frozen historical artifacts. New outputs are local to this audit run.
- `extended-layout.log` / `.xml`: 5/5 freshly compiled supplementary audit tests; `extended-trace.log` / `.xml`: 3/3. Historical test source was reused read-only, but binaries and executions are new.
- `python-output-review.log`: independent review of the Python agent's PY-04 transaction/caller changes; **27 relevant output/analysis tests pass**; no blocking issue found.
- `scope-identities.json`: final reviewed-source and binary SHA-256 values, compiler, flags and supplementary build commands. `baseline-poll-bench-identity.json` records the parent's requested frozen polling benchmark build with exact Release flags; this scope did not time it.

The focused build uses GCC 15.2.0, C++20, `-O2 -g -march=x86-64-v3 -DNDEBUG`. Build logs and exact standalone commands are retained next to the evidence. Example reproduction from the repository root:

```sh
ctest --test-dir build/independent-layout-tools-final --output-on-failure -R '^(trace|driver|layout|bench_contract)\.|^tools.cli_contracts$'
python3 audit/independent-20261027T041900Z/evidence/layout_tools/check_dependency_patch.py
python3 audit/independent-20261027T041900Z/evidence/layout_tools/compare_compatibility.py
python3 audit/independent-20261027T041900Z/evidence/layout_tools/release_layout_closeout.py
```

## Performance and limits

These corrections prevent source/evidence corruption and invalid configurations. Their filesystem checks run before fixture setup, and result finalization runs after measured work. **No material performance change or before/after speedup is claimed.** Functional comparisons above use actual frozen and changed binaries but are not timing experiments. Diagnostic test durations are not quiet-host benchmark results, and no old measurement is presented as a timing of this source.

File-identity checks assume stable local paths during an invocation; they do not implement a concurrent hostile symlink-race protocol. Shell-owned standard-stream redirection remains the caller's responsibility. Trace backing storage must remain immutable for the reader's lifetime. Logical frontend/solver caps bound specified work/storage counts, not a complete-call time limit or exact process-memory ceiling. This scope adds no new aggregate cap to intentionally large benchmark request/term dictionaries. No new numerical mismatch, parser crash, leak or allocation-failure bug was established here; the parent's sanitizer/fuzz matrix supplies broader memory validation. Finite tests and review do not prove the absence of every defect.
