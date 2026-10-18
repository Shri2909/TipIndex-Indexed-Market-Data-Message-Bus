# P1 restartable fuzz-gate execution

Date: 2026-10-17 (Asia/Kolkata). Scope remains approved v1.1 / Tier B P1–P5. This record covers P1 F1/F2 only; no P2 code or later benchmarks.

The original long child invocations ended successfully but accumulated only about910 monotonic seconds after wall-clock jumps. The later `F1-trace-gate-20261017T105935.973200Z.json` and `F2-framing-gate-20261017T110135.269411Z.json` were left `running` by worker interruption with no confirmed child exits. All remain historical, **unaccepted gate evidence**. No time from them is transferred to new gates.

## Original-source inspection

Inspected LLVM release **llvmorg-21.1.8**, commit **2078da43e25a4623cab2d0d60decddf709aaea28**, matching the installed Clang21.1.8 release. The commit was resolved from the official [release page](https://github.com/llvm/llvm-project/releases/tag/llvmorg-21.1.8) and [release commit](https://github.com/llvm/llvm-project/commit/2078da43e25a4623cab2d0d60decddf709aaea28).

- [FuzzerFlags.def](https://github.com/llvm/llvm-project/blob/2078da43e25a4623cab2d0d60decddf709aaea28/compiler-rt/lib/fuzzer/FuzzerFlags.def), declarations for `max_len`, `len_control`, `max_total_time`, `print_final_stats` and `detect_leaks` (lines15–22,55–56,138,161–162). `len_control=0` makes the full configured maximum length available immediately. It avoids repeatedly resetting a gradual input-length ramp when short segments restart.
- [FuzzerLoop.cpp](https://github.com/llvm/llvm-project/blob/2078da43e25a4623cab2d0d60decddf709aaea28/compiler-rt/lib/fuzzer/FuzzerLoop.cpp), `PrintFinalStats` (334–349), `ReadAndExecuteSeedCorpora` (742–806), `Loop` (807–853), and interrupt/leak-handling methods. The loop's disabled length-control branch selects `MaxMutationLen`; seed corpus execution preserves files present at startup. `system_clock` usage in loop/callback timing confirms why an independent monotonic duration is necessary in this environment. This is bounded source inspection; LLVM implementation code is not copied into the project.

## Runner contract and traceability

Clock discontinuity + interrupted workers → require confirmed monotonic runtime → `scripts/run_fuzz_gate.py::{run,save_atomic,verify_completed,verify_corpus,final_stats}` → F1/F2 completed-child logs and final JSONs.

The runner splits work into at most120-second libFuzzer processes. Each process keeps the same target binary, persistent corpus directory, dictionary, CPU, maximum input length65536, RSS2048MiB, timeout10s and required sanitizer/leak settings. Seed20191230 is incremented per segment and recorded. `-len_control=0` exposes the full length range in every segment. Input-length maximum and total required runtime are not reduced.

Only exit0 with all five final-stat counters, positive executed units, a completed-loop marker and no sanitizer/libFuzzer error is accepted. Each successful segment records command, seed, times, clock discrepancy, log hash, final stats and corpus hashes, then atomically saves totals. On `--resume`, binary, runner, dictionary, configuration and sanitizer environment must match; prior completed logs/statistics/totals and checkpointed corpus files are verified. Additions from an interrupted segment survive. An active segment without confirmed child exit is recorded `interrupted_unconfirmed` with zero credited time. Failed outcomes are not automatically resumed. A sidecar advisory lock prevents simultaneous resumption of the same gate.

## Current gate paths and exact continuation

F1 candidate: `results/p1/F1-trace-segmented-gate-20261017T142028.416744Z.json` (outside-tracing session86393).

```sh
TIPLOG_EXECUTION_CONTEXT=outside-sandbox .venv/bin/python scripts/run_fuzz_gate.py --phase p1 --label F1-trace-segmented --binary build/fuzz/fuzz_trace_reader --corpus tests/fuzz/corpus/trace_reader --dictionary tests/fuzz/trace_reader.dict --cpu 6 --seconds 1800 --segment-seconds 120 --resume results/p1/F1-trace-segmented-gate-20261017T142028.416744Z.json
```

F2 candidate: `results/p1/F2-framing-real-segmented-gate-20261017T142151.850263Z.json` (outside-tracing session65322).

```sh
TIPLOG_EXECUTION_CONTEXT=outside-sandbox .venv/bin/python scripts/run_fuzz_gate.py --phase p1 --label F2-framing-real-segmented --binary build/fuzz/fuzz_itch_walker --corpus data/raw/fuzz_itch_walker --dictionary tests/fuzz/itch_walker.dict --cpu 7 --seconds 1800 --segment-seconds 120 --resume results/p1/F2-framing-real-segmented-gate-20261017T142151.850263Z.json
```

Launches occurred sequentially through the approved outside-tracing execution mechanism; the two independent targets run concurrently on permitted E-cores6/7. ASAN_OPTIONS=`detect_leaks=1:abort_on_error=1`; UBSAN_OPTIONS=`print_stacktrace=1:halt_on_error=1`; DEBUGINFOD_URLS empty. The scripts check configured options remain enabled. No measured conversion or benchmark runs overlap these gates.

F2's first segmented launch used only synthetic seeds; it was deliberately stopped when the required real-prefix seed was identified. Its child received SIGTERM and exited72; `F2-framing-segmented-gate-20261017T142044.989922Z.json` is preserved as **failed / superseded**, with zero credited runtime, not a parser crash. The fresh F2 working corpus includes copied golden/synthetic files plus exactly65536 decompressed source bytes from offset0. Source/prefix hashes and `git check-ignore` result are recorded in `fuzz-F2-real-seed.json`; source bytes and all resulting mutations remain under ignored `data/raw/fuzz_itch_walker/`. No real Nasdaq seed is written into tracked `tests/fuzz/corpus/`.

Both target binaries remain unchanged from the original fuzz build. Actual terminal acceptance requires status=`passed`, at least1800 confirmed monotonic seconds, complete logs, and no unresolved crash. Until then this document describes execution in progress.

## Accepted checks and local-data handling

Both candidates subsequently passed: F1 1,801.8978 confirmed seconds / 53,139,553 executions; F2 1,801.7637 seconds / 2,043,899 executions. Each completed 15 exit-0 segments. `fuzz-gate-verified.json` independently recomputes saved log hashes/final statistics/totals and verifies current target/runner hashes and preserved corpus files.

Full F2 logs stay local and ignored by `.gitignore`: libFuzzer can print recommended dictionary fragments derived from the real-prefix seed. Gate JSONs retain commands, final statistics and complete-log SHA-256 without publishing payload fragments. Raw fuzz artifact directories are ignored too. The full local logs are preserved at their original paths, so hash verification and local review remain possible; ignored logs are not claimed packaged in source control.
