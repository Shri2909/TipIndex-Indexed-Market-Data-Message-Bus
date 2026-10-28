# Reproducing tiplog (core, plan v1.1 Tier B)

This is the historical P0–P8 command ledger. For the current audit corrections,
hash-locked setup and validation, use [REMEDIATION.md](REMEDIATION.md). Existing raw
measurements and acceptance records are preserved; their timings describe the
pre-remediation source.

This guide lists the commands that produced every accepted result, with their dependencies, seeds,
configurations and local-data requirements. Each command below was **actually executed** for the accepted
gates; the link after it is the saved execution record (exact argv, environment, exit code and log).
Commands are run from the repository root. Results and their interpretation are in [REPORT.md](REPORT.md).

> **Preserve, don't redo.** Valid local inputs and raw results are reused. Re-downloading, reconverting or
> re-running long campaigns is only needed on a fresh machine, and new timings will differ from the
> accepted ones (different host state). Correctness outputs and modeled costs are deterministic.

## 1. Requirements

| Item | Version used | Notes |
|---|---|---|
| OS / CPU | Linux, 12th Gen Intel Core i5-1235U | Timed work pins CPU 2; observers use other CPUs |
| C++ | GCC 15.2.0 (all presets); Clang 21.1.8 (RC-3 cross-compiler build) | C++20, sanitizer runtimes required |
| Build | CMake 4.4.0 (presets need ≥3.30), GNU Make | Presets in `CMakePresets.json`: `debug`, `release`, `asan-ubsan`, `fuzz` |
| Python | CPython 3.14.4 in `.venv` | Packages pinned in [py/requirements.txt](../../py/requirements.txt) |
| C++ deps | Google Benchmark 1.9.5; GoogleTest 1.17.0 | Fetched as SHA-256-verified archives, or exact system GoogleTest |
| Tools | `taskset`, `setarch`, GNU `time`, `mpstat` (optional) | No root or privileged setting is needed |
| Disk | ≈ 20 GB for source (4.0 GB incl. fuzz seeds), traces incl. repeat copies (9.1 GB) and raw results (7.0 GB) | Measured with `du` at closeout |

Environment captures: [P0](../../results/env/p0-environment.json), [P7](../../results/env/p7.json).

## 2. Setup

```bash
/usr/bin/python3 -m venv .venv
PIP_CACHE_DIR="$PWD/build/pip-cache" .venv/bin/python -m pip install --only-binary=:all: -r py/requirements.txt
.venv/bin/python -m pip check
scripts/git.sh status --short        # the managed .git/ is empty and read-only; history is in .tiplog-git/
```

`scripts/run_check.py <phase> <label> -- <command…>` is the wrapper used for every recorded check: it sets
`PYTHONPATH=py`, `MPLCONFIGDIR=build/matplotlib` and sanitizer options, and saves
`results/<phase>/<label>-<UTC>.{json,log}`. Sanitizer runs must not be under `ptrace` (LeakSanitizer).

## 3. Local data (not in Git)

| File | Size (bytes) | SHA-256 |
|---|---:|---|
| `data/raw/12302019.NASDAQ_ITCH50.gz` | 3,524,013,057 | `ef03df46a27e6bda4dead017f84c2e3979df7211f02c7868b51d53fceb99c689` |
| `data/traces/itch_20191230_0930_1000_spec.mdt` | 1,616,858,987 | `6062bdb96ec8354ecf650cdfb979574530b2120aa06047fa48d14a78e5936f70` |
| `data/traces/itch_20191230_0930_1000_flat.mdt` | 1,616,161,552 | `89cc31ac0c8907cf9552e85a60f04a221f4f2f9bc012769d0ab4de96376cbba2` |

Source URL: `https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/12302019.NASDAQ_ITCH50.gz` (downloaded
2026-10-17; [manifest](../../data/manifest.json)). Download it with any HTTP client and check
`sha256sum` against the table; the download itself was not repeated during closeout. Nasdaq publishes no
license text for these samples, so no message-level data is redistributed. The file lacks the BinaryFILE
terminator and stays `incomplete=true`.

Traces and counts (P1; [data gate](../../results/p1/data-gate.json), [CC-6](../../results/p1/cc6-reconciliation.json)):

```bash
PYTHONPATH=py .venv/bin/python -m tiplog_py.itch convert data/raw/12302019.NASDAQ_ITCH50.gz \
  --output data/traces/itch_20191230_0930_1000_spec.mdt \
  --also-flat data/traces/itch_20191230_0930_1000_flat.mdt \
  --counts-output results/data/itch_20191230_counts.json --volumes-dir results/data \
  --start 09:30:00 --end 10:00:00
bash -o pipefail -c 'gzip -dc data/raw/12302019.NASDAQ_ITCH50.gz | build/release/tiplog_walk - --out results/data/itch_20191230_counts_cpp.json'
build/release/tiplog_trace_check data/traces/itch_20191230_0930_1000_spec.mdt
```

RC-2 repeats the conversion into `data/traces/repeat/` and compares SHA-256; both hierarchies were
byte-identical. Ignored local-only paths: `data/raw/`, `data/traces/`, `results/raw/`, real fuzz seeds
under `data/raw/fuzz_itch_walker/`, and `results/p1/fuzz-artifacts/`, `results/p1/fuzz-crashes/`.

## 4. Build and full test suites (CC-1)

```bash
cmake --preset release && cmake --build --preset release --parallel 4
cmake --preset asan-ubsan && cmake --build --preset asan-ubsan --parallel 4
.venv/bin/python scripts/run_check.py p7 final-release-tests -- ctest --preset release --output-on-failure
.venv/bin/python scripts/run_check.py p7 final-asan-ubsan-tests -- ctest --preset asan-ubsan --output-on-failure
.venv/bin/python scripts/run_check.py p7 final-python-p7 -- .venv/bin/python -m pytest -q py/tests
```

Expected: 186/186 in each C++ build, no sanitizer report; 151 Python tests.
[release](../../results/p7/final-release-tests-20261025T155552.324180Z.json),
[ASan/UBSan](../../results/p7/final-asan-ubsan-tests-20261025T155555.617470Z.json),
[pytest](../../results/p7/final-python-p7-20261025T155605.212269Z.json).
`scripts/check_all.sh` builds and tests all four presets in one go (P0).

## 5. Correctness campaigns

**CC-2 differential (engine vs independent oracle).** For each of the 9 (mode, kernel) pairs — `scan/stdpq`
and `{indexed,auto} × {stdpq,binheap,quad,loser}`:

```bash
taskset -c 9 build/release/tiplog_differential --seeds 1000 --operations 10000 --seed-base 20191230 --mode indexed --kernel loser
taskset -c 9 build/asan-ubsan/tiplog_differential --seeds 200 --operations 10000 --seed-base 20191230 --mode indexed --kernel loser
.venv/bin/python scripts/run_p6_differential.py      # runs and records the full 18-row matrix
```

[CC-2 matrix](../../results/p6/CC2-all-configurations.json).

**CC-3 fuzzing** (`fuzz` preset, ≥1,800 s confirmed monotonic time each, resumable in 120 s segments):

```bash
TIPLOG_EXECUTION_CONTEXT=outside-sandbox .venv/bin/python scripts/run_fuzz_gate.py --phase p1 --label F1-trace-segmented --binary build/fuzz/fuzz_trace_reader --corpus tests/fuzz/corpus/trace_reader --dictionary tests/fuzz/trace_reader.dict --cpu 6 --seconds 1800 --segment-seconds 120
TIPLOG_EXECUTION_CONTEXT=outside-sandbox .venv/bin/python scripts/run_fuzz_gate.py --phase p1 --label F2-framing-real-segmented --binary build/fuzz/fuzz_itch_walker --corpus data/raw/fuzz_itch_walker --dictionary tests/fuzz/itch_walker.dict --cpu 7 --seconds 1800 --segment-seconds 120
.venv/bin/python scripts/run_fuzz_gate.py --phase p6 --label F3-prefix-final-segmented --binary build/fuzz/fuzz_engine_ops --corpus tests/fuzz/corpus/ops_p6_prefix --cpu 6 --seconds 1800 --segment-seconds 120
.venv/bin/python scripts/verify_p6_fuzz.py --gate results/p6/F3-prefix-final-segmented-gate-20261023T143815.176751Z.json --freeze results/p6/fuzz-source-freeze-prefix.json --output results/p6/fuzz-prefix-final-verified.json
```

F2's real-data seed is the first 65,536 decompressed source bytes and stays in an ignored directory
([notes](../../results/p1/fuzz-segmented-notes.md), [F1/F2](../../results/p1/fuzz-gate-verified.json),
[F3](../../results/p6/fuzz-prefix-final-verified.json)).

**RC-3 cross-compiler determinism** (needs a `build/clang-release` tree configured with Clang):

```bash
cmake --build build/clang-release --target tiplog_sim tiplog_differential -j 4
.venv/bin/python scripts/check_p6_rc3.py --cpu 7 --repeats 2
.venv/bin/python scripts/verify_p6_rc3.py
```

[RC-3](../../results/p6/rc3-final-verified.json).

**CC-5 optimizer exactness and the worked example:**

```bash
build/release/tiplog_layout_cc5 --instances 10000 --seed 20191230 --output results/p7/cc5-release.json
build/asan-ubsan/tiplog_layout_cc5 --instances 10000 --seed 20191230 --output results/p7/cc5-asan-ubsan.json
build/release/tiplog_layout_example --output results/p7/worked-example.json
```

[CC-5 release](../../results/p7/cc5-release.json), [CC-5 ASan/UBSan](../../results/p7/cc5-asan-ubsan.json),
[worked example](../../results/p7/worked-example.json).

## 6. P6 experiments

Matrix and protocol: [configs/P6/matrix.toml](../../configs/P6/matrix.toml),
[protocol freeze](../../results/p6/protocol-freeze.json), [Auto thresholds](../../results/p6/auto-thresholds.json).
Seeds: training 20191230, held-out evaluation 20191231.

```bash
.venv/bin/python -m tiplog_py.exp.run configs/P6/matrix.toml --suite pilot --prepare --directory results/raw/P6/prepared-pilot
.venv/bin/python -m tiplog_py.exp.run configs/P6/matrix.toml --suite training --prepare --directory results/raw/P6/prepared-training
.venv/bin/python -m tiplog_py.exp.run configs/P6/matrix.toml --suite evaluation --prepare --directory results/raw/P6/prepared-evaluation
.venv/bin/python scripts/run_p6_campaigns.py --run --directory results/raw/P6/campaign-20261024 --quiescence-record <record.json>
.venv/bin/python scripts/summarize_p6_t2_adjusted.py results/raw/P6/campaign-20261024/evaluation/runs.jsonl --output results/derived/t2-adjusted-paired.json
.venv/bin/python scripts/summarize_p6_t5_highwater.py results/raw/P6/campaign-20261024/evaluation --output results/derived/t5-high-water.json
```

The campaign runner refuses to start without a quiescence record declaring that no other build, test,
fuzz or benchmark runs; add `--resume` to continue an interrupted campaign without repeating accepted
rounds. The accepted campaign spanned about 25 hours of wall time (2026-10-24 03:35 to 2026-10-25 04:23 UTC,
including a user-requested pause), needs AC power, and runs consolidation, analysis and the figure build
at the end. The accepted records are [measurement-quiescence-resume.json](../../results/p6/measurement-quiescence-resume.json)
and the [closeout evidence](../../results/p6/closeout-evidence.json).

## 7. P7 optimizer studies

Caps, workloads and β values are frozen in [protocol.json](../../results/p7/protocol.json); seed 20191230.

```bash
.venv/bin/python -m tiplog_py.layout.inputs --output-dir results/raw/P7/inputs --metadata results/raw/P7/inputs/metadata.json
.venv/bin/python scripts/run_p7_studies.py --manifest results/p7/input-manifest.json --output results/raw/P7/studies --cpu 2
.venv/bin/python scripts/analyze_p7.py
.venv/bin/python -m tiplog_py.layout.global_study --campaign results/raw/P7/studies/campaign.json
```

The study runner resumes from accepted batches if interrupted (the accepted resume took ≈ 15 minutes). Outputs:
[layout summary](../../results/derived/layout-summary.json), [global audit](../../results/derived/layout-global.json).

**Controlled DP runtime (L3).** Run only on a quiet machine: no builds, tests, fuzzing or other CPU-heavy
work, including other projects. Launch detached so an agent or terminal session ending cannot kill it:

```bash
setsid nohup taskset -c 11 nice -n 19 .venv/bin/python scripts/p7_cpu_sampler.py --output results/raw/P7/runtime-host/cpu-samples.jsonl >/dev/null 2>&1 &
setsid nohup .venv/bin/python scripts/run_check.py p7 controlled-dp-runtime -- .venv/bin/python scripts/run_p7_runtime.py >/dev/null 2>&1 &
# after it finishes (≈ 12 minutes):
.venv/bin/python scripts/run_check.py p7 runtime-quiescence -- .venv/bin/python scripts/check_p7_runtime_quiescence.py
.venv/bin/python scripts/run_check.py p7 runtime-analysis-final -- .venv/bin/python scripts/analyze_p7_runtime.py
```

If the quiescence check fails, the campaign is rejected under the
[pre-declared rule](../../results/p7/runtime-quiescence-rule.json) and must be rerun on a quiet host.
Accepted: [campaign](../../results/p7/runtime-campaign.json), [quiescence](../../results/p7/runtime-quiescence.json).

## 8. Figures (RC-1)

With the accepted local results present, one command rebuilds F01–F18 and their manifests:

```bash
PYTHONPATH=py MPLCONFIGDIR="$PWD/build/matplotlib" .venv/bin/python -m tiplog_py.figures.build --all
.venv/bin/python scripts/check_p7_figure_extension.py
```

[Accepted regeneration](../../results/p7/figures-all-final-20261025T154953.610882Z.json) (≈ 3 minutes),
[P1/P6 compatibility check](../../results/p7/figure-extension-compatibility.json). Rebuilt P1/P6 PNGs are
byte-identical to their accepted versions, and their PDFs differ only in `CreationDate` metadata.

## 9. Gate verification

```bash
.venv/bin/python scripts/run_check.py p7 gate-checks -- .venv/bin/python scripts/check_p7_gate.py
.venv/bin/python scripts/check_core_closeout.py
```

The first verifies P7's executed artifacts ([result](../../results/p7/gate-checks.json)). The second checks
the whole core: the phase-gate chain, dependency identities, the long correctness evidence, the P7
runtime campaign, document links, packaging and the final acceptance review
([acceptance evidence](../../results/p8/acceptance-evidence.json)). It writes `results/p8/checks.json` and
`results/p8/artifact-manifest.json`. Neither script builds, tests or times anything.

## 10. Seeds and configuration summary

| Use | Seed / setting |
|---|---|
| CC-2 differential | seed base 20191230; 1,000 (release) / 200 (ASan/UBSan) seeds × 10,000 ops |
| CC-5 random trees | 20191230; 10,000 instances, ≤12 nodes, ≤4 classes |
| P6 Auto training / held-out evaluation | 20191230 / 20191231 |
| P6 bootstrap | 10,000 resamples, seeded per configuration |
| P7 synthetic trees, round shuffles, bootstrap | 20191230 (per-input bootstrap seeds derived from the case ID) |
| P7 solver caps | ENUM ≤22 edges; DP ≤16 classes; 2,000,000 states and work units; 500 ms |
| Timing CPU | CPU 2 (solver/benchmark), observers on other CPUs; no privileged settings |

## 11. Optional F-01 feature

The P0–P8 commands above describe historical acceptance. The subsequently approved
inspection-budget extension has its own [contract, caller example and reproduction
instructions](POLL_BUDGET.md), [pre-change baseline](../../results/f01/baseline.json),
and [final compiled-source freeze](../../results/f01/source-freeze-final.json).
New evidence stays under `results/f01/`; earlier acceptance files are preserved.

```bash
cmake --preset release
cmake --build --preset release --parallel 4
ctest --preset release --output-on-failure
.venv/bin/python scripts/run_f01_differentials.py --preset release --reuse-compatible
.venv/bin/python scripts/check_f01_contract_mutations.py --build-root build/release \
  --output-dir results/f01/my-contract-mutations
```

The recorded differential runner refuses to overwrite a completed campaign index;
reuse verifies exact commands, frozen input identities and output-log hashes.
The initial source freeze differs from the final freeze only in the test allocator
hook and Tail exception test; the engine and differential implementations match.
Interrupted and failed attempts remain visible and do not count as accepted runs.
Sanitizer campaigns and fuzz checks require the same leak-detection environment
as the core tests; in this workspace they run outside tracing.
