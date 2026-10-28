# Layout, trace, tools, benchmark and build audit

Findings below were recorded before source corrections. Initial source: `../initial/source-snapshot.tar`; bounded reproductions (private temporary fixtures only): `../evidence/layout_tools/probe_tools.py`, `baseline-probes.json`. Existing Release binaries are identified by SHA-256 in each row; a frozen-source build will separately establish regression causality. No performance result is asserted by these functional probes.

## TOOL-01 — Output aliases corrupt source inputs

- Severity: **medium** (local input data loss). Status: **fixed and verified** (focused current Release checks; root final matrix recorded separately).
- Locations: `tools/tiplog_layout/main.cpp:191-194,501-516`; equivalent `runtime_main.cpp`; `tools/tiplog_bench/main.cpp:691-697`; `tools/tiplog_walk/main.cpp:52-58`; microbenchmark diagnostic output paths.
- Trigger/reproduction: pass a hard link to a CASE file as layout `--output`; pass the requests file itself as integrated benchmark `--output`. See `tiplog_layout_hardlink`, `tiplog_layout_runtime_hardlink`, `bench_requests_alias` in baseline probes. All exit zero and change source bytes; layout empties its input before reading, yielding a vacuous successful run. Walk also accepts its input as output, replacing BinaryFILE bytes with JSON. Integrated benchmark uses append mode (rather than truncation), so input becomes corrupt after a successful run.
- Root cause: lexical/canonical pathname comparisons do not establish inode identity; several tools have no source/output separation check. Diagnostics selected via environment variables can also alias benchmark inputs.
- Correction: reject any existing same-file identity (including hard links and symlinks) before opening writable outputs, while retaining existing append/replace behavior for distinct explicitly requested outputs. Check ordinary path aliases as well. Preserve standard-stream behavior. No concurrent hostile pathname race guarantee is introduced.
- Validation: regressions assert nonzero and exact preservation of private source bytes for direct, hard-link and symlink aliases, across both layout input modes, walk and benchmark sources. Valid distinct outputs and `/dev/full` errors remain covered.

## TOOL-02 — Request input read errors become successful empty campaigns

- Severity: **medium** (misleading evidence). Status: **fixed and verified** (focused current Release checks; root final matrix recorded separately).
- Location: `tools/tiplog_bench/main.cpp:197-223`, especially unchecked stream state after `getline`.
- Trigger/reproduction: `--requests` names a directory on Linux; opening succeeds, reading sets `badbit` without EOF, and the benchmark exits zero with a successful prefill row and no requests. See `bench_requests_read_error` in baseline probes.
- Root cause: EOF and read failure are conflated by loop termination; request parser alone omits the final state check already present in term dictionaries and payload mixtures.
- Correction: require normal EOF and reject any bad stream state before returning parsed requests; keep intentionally empty regular request files supported.
- Validation: directory/read-failure regression must fail before output creation; valid empty, header-only and nonempty inputs still work.

## TOOL-03 — Microbenchmark verification accepts malformed or ignored options

- Severity: **low** (wrong configuration/evidence). Status: **fixed and verified** (focused current Release checks; root final matrix recorded separately).
- Locations: `bench/micro/merge_bench.cpp:340-350` (`stoull` without consumed-length check); verification argument paths in all three microbenchmark mains.
- Trigger/reproduction: `merge_bench --diagnostic --profile=uniform64 --outputs=8garbage` succeeds and labels N=8; `--seed=-1` succeeds as UINT64_MAX. Unknown options with `--verify-only`/`--diagnostic` are collected for Google Benchmark but never validated in verification mode. Baseline proves this for merge and publish; index code has the identical omission and will be probed with a nonempty fixture.
- Root cause: permissive integer conversion and bypassed leftover-argument validation.
- Correction: parse complete unsigned decimal integers with checked uint64 and size_t representation; reject leftover arguments in verification mode rather than silently ignoring them. Normal Google Benchmark arguments remain supported on measurement paths.
- Compatibility: valid unsigned values and supported verify invocations retain exact schedule/digest behavior; previously malformed or inapplicable arguments fail explicitly.
- Validation: suffix/sign/whitespace/overflow negative controls and unknown verification-option controls; valid maximum seed, deterministic tiny functional profiles, and selected real benchmark arms remain valid.

## TOOL-04 — A valid request named `id` is silently skipped

- Severity: **medium** (missing benchmark evidence). Status: **fixed and verified** (focused current Release checks; root final matrix recorded separately).
- Location: `tools/tiplog_bench/main.cpp:210-211`.
- Trigger/reproduction: a normal nine-column request with first field `id` (followed by `T1`, numeric after_seq, valid terms/mode/kernel/cache/batch/readers) yields exit zero and a prefill row only. Exact bytes, command, binary SHA-256 and observed output: `../evidence/layout_tools/baseline-request-id.json`.
- Root cause: any line whose first field is `id` is classified as a header without checking the other eight header names. There is no reserved request-ID contract; headerless request files are intentionally supported and used by existing regression tests.
- Correction: skip only the exact documented TSV header (`id experiment after_seq terms mode kernel cache batch readers`, tab-separated). A request ID `id` then follows normal validation and execution. A malformed putative header fails as malformed input.
- Compatibility: generated request headers and all other valid IDs retain behavior; valid `id` requests now run instead of disappearing.
- Validation: a header followed by an `id` request must produce prefill plus exactly that replay row; malformed short header must fail before output creation. Frozen-source negative control must establish the regression.

## TOOL-05 — Google Benchmark result-file failures still report success

- Severity: **medium** (lost measurement evidence). Status: **fixed and verified** (focused current Release checks; root final matrix recorded separately).
- Locations: pinned Google Benchmark `src/benchmark.cc`, `RunSpecifiedBenchmarks` around lines 628-649 and 677-678; all three project microbenchmark mains delegate `--benchmark_out` to this function. The dependency archive is hash-pinned by `cmake/deps.cmake`.
- Trigger/reproduction: a frozen-source `index_bench` using a private 64-record trace, `--benchmark_filter=^M3-seek/B64$ --benchmark_min_time=1x --benchmark_out=/dev/full` exits zero. See `../evidence/layout_tools/baseline-gbench-full.json`; all input construction and the independent reference check succeed.
- Root cause: Google Benchmark owns a separate result ofstream, checks its initial open only, and relies on an unchecked destructor close. The frontend's stdout flush checks cannot observe this stream's write failure.
- Correction: retain the exact pinned archive and apply a small project-owned, deterministic, SHA-checked patch to its generated source, explicitly flushing/checking/closing/checking the owned result stream at normal completion. Existing frontend exception handling then returns nonzero. Original and patched dependency source hashes are checked at configure time; unexpected source contents fail rather than silently receiving a best-effort patch.
- Compatibility: successful result bytes and timing boundaries are unchanged. The finalization check occurs after all benchmark measurements. Archive authenticity and version pins remain intact; the local behavior correction is explicit in source and audit evidence.
- Validation: selected M3 result to `/dev/full` must fail; valid temporary JSON output must parse and retain independent metadata/digests. M1 and M2 link the same patched target and their valid functional verification paths remain covered. Full supported builds/test matrix checks patch application in every configuration. No historical measurements or gates are regenerated.


## Verification closeout

All five findings are confirmed, fixed and verified by focused current-source Release checks. Six regression groups fail against freshly built frozen initial source (`baseline-red-controls.json` / `.log`), and all thirteen CLI contract groups pass on changed source as part of **52/52** focused CTests (`focused-tests.log`). The compatibility test using input filenames that resemble `--benchmark_out=` was added after independent review; the output guard now sees only filtered Google Benchmark arguments. The first attempted strict-size implementation accidentally selected `std::size` through argument-dependent lookup; regression testing caught it, the helper was renamed `parse_size`, and the failed run remains in `focused-tests-first.log`.

`dependency-patch-check.json` proves exact original→patched contents, idempotent no-write reuse and rejection of unexpected source without mutation, with the pinned archive unchanged. `configure-repeat.json` additionally proves a repeated full CMake configure retains the approved patched hash and mtime. The new Google Benchmark result-file regression fails with `/dev/full` and valid saved JSON remains readable and has identical independent fixture metadata.

`functional-compatibility.json` compares frozen and changed binaries on identical valid M1 maximum-seed, M2 verified synthetic, and M3 verified trace workloads: all stdout bytes match. It also separately proves the nonempty M3 unknown-verification-option defect and correction. This is a functional comparison, not a performance result.

`release-layout-closeout.json` records a newly executed Release CC5 10,000-instance run and worked example. Both outputs are byte-identical to their immutable historical counterparts. Supplementary current-source audit tests also pass: `extended-layout.log` / `.xml` (five tests, including 1,500 larger rational instances and 8,890 exact-count comparisons) and `extended-trace.log` / `.xml` (three tests, including 20,000 mutations). Commands and final source/binary hashes are in `scope-identities.json`. The parent audit owns the complete Debug/Release/ASan/UBSan/fuzz matrix and final current-source acceptance records; these focused results do not stand in for that matrix.
