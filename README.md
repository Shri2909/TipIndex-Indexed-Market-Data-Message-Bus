# tiplog

C++ Market-Data Message Bus with Indexed Replay. The approved design is
[plan v1.1, Tier B](docs/plan/INDEX.md). Phase 0 supplies build, test and environment
plumbing. P1–P5 are jointly authorized and execute in dependency order; current
gate results are in [PROGRESS](docs/plan/PROGRESS.md). P6–P8, Tier C and roadmap
extensions remain outside that authorization.

## Repository layout

The workspace's empty, managed `.git/` is read-only. Git metadata lives in the
writable `.tiplog-git/`, with this directory as its worktree. Use:

```bash
scripts/git.sh status --short
scripts/git.sh diff
```

The wrapper passes explicit `--git-dir` and `--work-tree` paths and works from
any current directory. Plain `git status` cannot discover this repository in
this managed workspace. Local source snapshots are recorded in PROGRESS. Build files, `.venv`,
local metadata, raw inputs, message-level traces and large raw results are ignored.

## Python setup

Phase 0 validated `/usr/bin/python3` (CPython 3.14.4) and an isolated `.venv`.
Recreate with a compatible explicit interpreter, then install the frozen package
versions (network access required on a fresh checkout):

```bash
/usr/bin/python3 -m venv .venv
PIP_CACHE_DIR="$PWD/build/pip-cache" .venv/bin/python -m pip install --only-binary=:all: -r py/requirements.txt
.venv/bin/python -m pip check
```

[requirements.txt](py/requirements.txt) is the complete installed project package
snapshot; pip itself is recorded in [the interpreter manifest](results/env/p0-python.json).
Hypothesis and optional extensions are deferred. Set `MPLCONFIGDIR` to a writable
directory for standalone plotting; `check_all.sh` does this automatically.

## Build and check

Requires CMake ≥3.30, GNU Make, GCC and Clang with sanitizer runtimes. The
validated versions are saved in `results/env/`. All presets use Unix Makefiles:

```bash
scripts/check_all.sh
scripts/env_capture.sh > results/env/local.json
```

`check_all.sh` configures, builds and runs CTest for `debug`, `release`,
`asan-ubsan` and `fuzz`, then checks Python dependencies and runs pytest. It saves
exact arguments, exit codes and logs under a fresh `results/p0/<UTC timestamp>/`.
Set `CMAKE_BUILD_PARALLEL_LEVEL` to adjust parallel jobs (default 4).

```bash
cmake --preset release
cmake --build --preset release --parallel 4
ctest --preset release
```

The fuzz preset builds `fuzz_trace_reader`, `fuzz_itch_walker` and the
structure-aware `fuzz_engine_ops`. They link `tiplog::fuzzer_options`; normal tests retain
GoogleTest's main with `fuzzer-no-link`. Accepted P1 timed checks and exact
restart commands are recorded in [the fuzz execution notes](results/p1/fuzz-segmented-notes.md).
Sanitizer execution in this managed environment requires running outside sandbox
tracing while retaining leak detection; see the saved P0/P1 results.

Google Benchmark **v1.9.5** and the GoogleTest **v1.17.0** fallback use fixed commit
archives with SHA-256 verification. An exact system GoogleTest 1.17.0 takes
precedence. On this workspace the verified archives are cached in ignored
`build/downloads/`; a fresh checkout fetches them from upstream. The fallback
can be selected with `-DTIPLOG_FORCE_FETCH_GTEST=ON`. Upstream licenses are
retained in dependency source trees; inspected revisions and primary references
are recorded in [the Phase 0 source ledger](docs/plan/RESEARCH.md#7-phase-0-just-in-time-source-inspection--2026-10-17).

Environment capture probes CPU affinity, topology, frequency and counter access;
it makes no privileged setting changes. The approved default uses wall/user/system
CPU time and, in later experiments, explicitly simulated Cachegrind results on
reduced cases. Phase 0 diagnostics establish no performance claim.

## P1 data tools

The approved source is the 2019-12-30 Nasdaq sample. Its identity, acquisition
metadata and gzip validation are in [data/manifest.json](data/manifest.json).
Raw input, real fuzz seeds and message-level traces stay in ignored local
directories. The intact gzip lacks a BinaryFILE terminator; metadata explicitly
retains `incomplete=true`. Protocol references and actual reading depth are in
[the Python ledger](results/p1/python-sources.md) and
[the independent C++ ledger](results/p1/cpp-sources.md).

The following commands reproduce the conversion and independent count paths
from an already acquired input. Complete production gate results, including
repeat conversion, are recorded separately in PROGRESS; these examples do not
assert an unexecuted check passed.

```bash
PYTHONPATH=py .venv/bin/python -m tiplog_py.itch convert data/raw/12302019.NASDAQ_ITCH50.gz \
  --output data/traces/itch_20191230_0930_1000_spec.mdt \
  --also-flat data/traces/itch_20191230_0930_1000_flat.mdt \
  --counts-output results/data/itch_20191230_counts.json --volumes-dir results/data \
  --start 09:30:00 --end 10:00:00
bash -o pipefail -c 'gzip -dc data/raw/12302019.NASDAQ_ITCH50.gz | build/release/tiplog_walk - --out results/data/itch_20191230_counts_cpp.json'
build/release/tiplog_trace_check data/traces/itch_20191230_0930_1000_spec.mdt
PYTHONPATH=py MPLCONFIGDIR="$PWD/build/matplotlib" .venv/bin/python -m tiplog_py.figures.build --all
```

Normal conversion checks the complete decompressed stream even after the window
ends. `--limit-bytes` is a limited throughput diagnostic and cannot certify
full-day totals or source completeness. The bounded Python and C++ parsers are
independent implementations of the original Nasdaq specifications. Trace v1 is
the project's own checked little-endian format; original ITCH payloads and source
order are preserved in both H-spec and H-flat.


## Engine, replay and P5 harnesses

The deterministic single-threaded implementation now includes the topic registry,
compiled exact/subtree subscriptions, bounded DATA/PAD ring, shared partition
index, four merge kernels and captured-range replay/Tail chaining. Public types
and entry points are in [engine.hpp](src/tiplog/engine/engine.hpp).
`open_replay` captures an exclusive upper bound. Positive full-budget batches
return More immediately; a later positive poll establishes completion. A completed
checkpoint advances past filtered events as well as delivered events. Tail polls
chain those checkpoints and can capture a newer head after catching up. Retention
failures are explicit, with a valid delivered prefix.

Scan, Indexed and Auto share the same progress/expiry semantics. Auto's initial
partition/density thresholds are configurable and **uncalibrated**; wide terms use
Scan. Delivered byte spans are non-owning views subject to the documented Engine
lifetime/publication rules. The implementation has no concurrent-reader or durable
storage guarantee.

`tiplog_sim --help` lists the deterministic trace-driver options. The accepted
[RC3 evidence](results/p5/rc3-evidence.md) saves exact real-trace and synthetic
commands for all modes/kernels, including successful and expired consumers.
The independent raw-path/full-history references are under `tests/ref/`.

P5 exposes the full M1/M1-touch and M2 matrices, with limited pilot execution
tracked separately in PROGRESS:

```bash
build/release/merge_bench --profile=pilot --verify-only --quad-padding-both
build/release/publish_bench --matrix --verify-only
.venv/bin/python scripts/run_p5_pilot.py
```

The first two commands perform functional checks without benchmark timing.
M1 uses the full selected output count and1GiB touch allocation; M2 verification
uses an explicitly reduced capacity. The final command prints the timing plan
only. Actual pilot execution requires the runner's saved quiescence declaration
and reviewed environment checks; [method](results/p5/pilot-method.md) explains the
exact boundaries and retained artifacts. P6 campaigns, noise study and held-out
Auto calibration require a separate authorization.
