# P5 limited pilot orchestration

Initial preparation status (superseded by the terminal record below): **runner implemented; timed pilot unrun**. Root must finish all fuzzing,
checks, cross-compiler verification and builds, review the source, record an actual
local Git commit and save the quiescence declaration before using `--run`.
The default invocation only prints the plan and launches no benchmark.

`scripts/run_p5_pilot.py` runs three processes sequentially: M1/M1-touch at k64
(uniform and geometric mean64 merge, uniform touch, four kernels and a second
Quad padding geometry), then M2 payload64/P100/uniform with B256 and B1024.
Each M2 process registers index off/on together. Each process receives fifteen
repetitions, true random interleaving, 0.2s minimum warm-up and adaptive 0.5s
minimum measurement. Neither the runner nor harness uses an explicit iteration
cap. This is the limited P5 pilot; the full matrix, P6.2's thirty-repetition noise
study, T1 and measured Auto calibration remain outside these runs.

The required declaration is a JSON document whose `status` is `passed` and whose
`fuzz_finished`, `conversion_finished`, `tests_finished`, `builds_finished` and
`other_agents_quiescent` fields are all true. Save the actual checks supporting
that assertion in the declaration. The runner independently observes visible
processes before each block and afterwards, preserves enumeration errors and PID
namespace identity, and rejects visible competing fuzz/test/build/conversion
work. Parent processes launching this runner are excluded. These snapshots and
an operator declaration do not establish exclusive host access. Root must keep
all other agents and project workloads idle throughout timing.

Before the first settling interval, the runner obtains a fresh environment
capture using `scripts/env_capture.sh --cpu 2 --preset release`, verifies actual
Git HEAD, hashes both binaries and their source/build files, and rehashes the
source gzip, both traces, both metadata files, manifest and empirical mix inputs.
It checks accepted manifest/meta hashes and mix/spec provenance. These input
reads precede settling. The selected workloads are synthetic; retaining Nasdaq
identities does not turn the pilot into a trace replay experiment.

Every block follows at least sixty **monotonic** seconds of idle settling, with
ten-second heartbeats. Fresh AC power and CPU2 P-core/child affinity verification
are mandatory. The child is invoked using `taskset -c 2`; each harness invocation
logs its actual starting/ending CPU. AC is sampled during settling and execution,
and loss of AC terminates and invalidates the block. No system settings change.
If the fresh per-process ASLR probe succeeds, the measured child also uses
`setarch -R`; otherwise the denied probe and retained host ASLR regime are saved.
Inherited `BENCHMARK_*` settings are recorded and removed, so they cannot silently
filter profiles or alter the explicit protocol.

Raw stdout, stderr, exit status, exact argv, seed, environment overrides, full
Google Benchmark individual JSON, input metadata and actual function invocation
order are retained under `results/raw/P5/<run_id>/`. The run ID contains actual
UTC timestamp, commit, initial dirty flag and host. A shared provenance and fresh
environment document accompanies all three blocks; every block points to them.
Actual dirty status is also saved after the session. Source/binary hashes are
rechecked after timing. Exceptions and failed/interrupted attempts remain saved;
they do not disappear from the run history. `results/p5/pilot-latest.json` points
to the latest complete session record, including a failed session.

The primary hot-loop measurements are Google Benchmark's per-repetition CPU and
wall time. Whole-child wall time and `getrusage(RUSAGE_CHILDREN)` deltas include
process startup, input construction, allocation, prefill, warm-up, adaptive
calibration, repetitions, reporting and teardown. There is only one child during
that interval. The harness's invocation-level time/getrusage likewise includes
function setup. These diagnostic CPU values must not be substituted for hot-loop
time. ns/output or ns/publish is computed from reported time per iteration divided
by the matching outputs/publishes-per-iteration counter.

CPU2 frequency samples bracket each process and every harness invocation. All
nonmissing invocation and block endpoints define the session median. Samples
deviating by more than ten percent are flagged in a separate JSON document;
every original invocation and repetition is retained. `/proc/stat` observations
for sibling CPU3 are saved, while scheduling isolation or perfect sibling idle
is not claimed. The protocol places no project work on CPU3. Recorded frequency
endpoints also do not establish a fixed clock during hot loops.

The summary requires the expected fifteen M1 cases and two cases per M2 block,
fifteen individual repetitions with unique indices per case, successful hash/count
checks in the harness, nonempty invocation logs, and actual CPU2 at every logged
boundary. It reports profile medians and non-ok counts without pilot confidence
intervals, a kernel winner or an Auto-calibration claim. Hardware counters remain
unavailable under the approved nonprivileged fallback. Root separately collects
a reduced **simulated Cachegrind** diagnostic; it is not a fourth timed block.

## Source/finding to evidence

Original Google Benchmark material was inspected locally from the pinned v1.9.5
source, revision `192ef10025eb2c4cdd392bc502f0c852196baa48`. Actually inspected:
`docs/user_guide.md` Output Formats lines71–108 and Runtime and Reporting
Considerations lines240–270; `docs/random_interleaving.md` complete;
`include/benchmark/benchmark.h` MinTime/MinWarmUpTime/Iterations lines1230–1255;
`src/benchmark.cc` execution shuffle and bulk reporting lines446–500. Reuse the
file hashes in [the pinned source record](../p4/p5-method-reading.json). No code
from the library was copied. The original [user guide](https://github.com/google/benchmark/blob/192ef10025eb2c4cdd392bc502f0c852196baa48/docs/user_guide.md)
and [shuffle implementation](https://github.com/google/benchmark/blob/192ef10025eb2c4cdd392bc502f0c852196baa48/src/benchmark.cc#L476)
support these API/behavior decisions. The library's internal entropy seed is not
exposed; actual function invocation order is saved, without inventing a replayable
interleaving seed. No library variance percentage is transferred to this project.

| Finding/requirement | Decision and task | Code/symbol | Validation and executed evidence |
|---|---|---|---|
| S42 adaptive timing, repetitions and individual JSON | Preserve approved micro protocol, P5.5 | `FLAGS`, `plan`, `summarize` | Required flags and count/index/units audit; runner validation record below. Timed artifacts pending. |
| S42 random-device shuffle and bulk reporting | Preserve invocation order separately; entropy limit explicit | `TIPLOG_BENCH_INVOCATIONS`, `run_block` | Raw harness log required, CPU boundary audit; timed artifacts pending. |
| VALIDATION §§5.1–5.2 environment/provenance | Fresh no-privilege capture, real commit, fresh hashes, AC/affinity and settling | `provenance`, `git_info`, `require_quiet`, `settle` | Plan and synthetic guard checks only so far; actual environment/session pending. |
| VALIDATION §5.5 failure accounting | Keep failed/interrupted attempts and every flagged sample | `run_block`, `main`, `frequency_flags` | Synthetic failed-record and frequency-flag checks; actual timed outcomes pending. |
| VALIDATION §5.6 fallback and §7 boundaries | Separate setup-inclusive diagnostics from hot-loop time; root-owned reduced simulated Cachegrind | `usage_delta`, `summarize` | Units/denominator checks; actual fallback run pending. |

See [pilot-runner-validation.json](pilot-runner-validation.json) for the actual
runner-only validation command, input fixtures, outcomes and source hash. Its
synthetic files live under ignored `build/p5/runner-validation/`; they contain no
benchmark measurements and are not evidence of performance or a passed P5 gate.


## Terminal execution — 2026-10-19

All three isolated blocks passed. [Actual results](pilot-results.md) and
[summary](pilot-summary.json) link the complete raw directory, per-repetition
build/run provenance and independent3821-check audit. There are285 measured
rows over19 cases and369 logged invocations, with zero non-ok outcomes.
All128/744 frequency endpoints flagged by the10% rule remain retained.
Source/binary/input identities match; no concurrent project workload or
setting change occurred. The fresh allowed per-process ASLR probe succeeded,
so measured children used setarch-R while the system setting remained2.
The whole-program [simulated Cachegrind](cachegrind-summary.json) diagnostic
was collected separately after fuzzing and before settling. No full P6
campaign, confidence-interval/kernel-winner or calibrated-Auto claim follows.
