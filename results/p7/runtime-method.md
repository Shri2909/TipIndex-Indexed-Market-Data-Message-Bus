# Controlled P7 DP runtime supplement — runner preparation

This note describes the prepared runner. It does not record an executed runtime
campaign or claim that a gate passed. Execution waits for the root task's
instruction after the original cost matrix, analysis/global work, dedicated
frontend build and required checks finish. The scope is the user's authorized
[P7 → P8 instruction](authorization.txt), the frozen [original P7 protocol](protocol.json),
the [runtime supplement](runtime-supplement.json), and VALIDATION_PLAN §5.

The dedicated `tiplog_layout_runtime` frontend adds read-only Linux observations
around the unchanged layout solver. The original cost frontend, accepted engine
and optimizer library remain the reference implementation. The runtime runner
is new project code; it uses only Python's standard library, existing project
input/output formats, Linux `/proc`/sysfs, GNU time, taskset and an unprivileged
setarch capability probe. No external algorithm or unpublished Aria detail is
introduced.

The intended command, to execute only after the root confirms readiness, is:

```sh
.venv/bin/python scripts/run_p7_runtime.py \
  --protocol results/p7/runtime-supplement.json \
  --manifest results/p7/input-manifest.json \
  --campaign results/raw/P7/studies/campaign.json \
  --output-dir results/raw/P7/runtime \
  --summary results/p7/runtime-campaign.json
```

All flags have the defaults shown. The runner refuses to begin if the original
cost campaign is not `passed`, the manifest does not retain all 32 source files
and all eight synthetic batches / 900 cases, or the explicit runtime protocol
does not specify one warm-up plus ten measured rounds, seed 20191230, 60 seconds
of settling, solver CPU 2 and requested observer CPU 6. Its five solver caps must
equal the original P7 caps exactly. It verifies the metadata, original synthetic
input hashes and original DP output hashes before measuring. The current solver
library must still match the original cost campaign's library identities.

## Population and timing boundary

Every round is a fresh process containing all 900 original synthetic cases once.
Original `CASE` through `END` byte chunks are preserved, with no new synthetic
generation. A single `random.Random(20191230)` shuffles the sorted global case-ID
list once per round, producing 11 reproducible orders. Each order, plaintext
SHA-256 and deterministic lossless gzip input is saved under the ignored runtime
directory. Serialization/compression finishes before the full settling block.
Only the runner-owned plaintext scratch copy is removed after that attempt; the
gzip, order, hashes, output, logs, resources and failed attempts remain available.
An interrupted input-preparation attempt retains its partial artifacts.

The child command uses `/usr/bin/time -v`, `taskset -c 2`, the dedicated runtime
frontend, `--methods dp`, and the unchanged cap flags. If env_capture's actual
unprivileged setarch probe succeeds, it uses `setarch <machine> -R` for each child.
If the probe is denied, it records the explicit `ASLR_on_fallback`, its probe
failure and the observed system ASLR setting. No privileged setting is changed.
The exact argv, PID, cwd, controlled `LC_ALL=C`, command start/finish timestamps,
observer monotonic bracket, GNU time resource log and identities are saved.

The primary solver time is the frontend's actual internal `steady_clock` solver
duration. It includes solver reconstruction and internal formula checks, and
excludes preparation, control observations and independent CLI materialization.
The runner's `observer_process_wall_seconds` is a separate observer bracket;
GNU time's resource file supplies the process wall/resource observation. Neither
is substituted for the solver boundary. Warm-up output is saved and excluded
from the measured statistics.

## Controls and honest limits

The Python observer requests CPU 6; if unavailable, it chooses an allowed CPU
outside CPU 2 and sibling 3 when possible. Initial/actual observer affinity and
fallback errors remain explicit. Before measurement starts, it runs the existing
`scripts/env_capture.py` once for that invocation, saving its output, stderr,
command record and hashes. This captures hardware, topology, compiler versions,
release flags, build caches, read-only controls, source gzip/trace metadata and
Git SHA/dirty state. Runtime source/binary/build/protocol/input/reference hashes
are recorded separately; source gzip and trace identities are retained from the
accepted P1 evidence without rehashing multi-gigabyte local data. An interrupted
campaign may record a fresh environment addendum when resumed; it never replaces
the earlier environment record.

Before **every** round, including warm-up, the runner performs a full 60-second
monotonic settling block. Sleep steps are at most 10 seconds and progress prints
are at most 20 seconds apart. Start/finish UTC, monotonic times, actual elapsed
duration and `complete` are saved. An interrupted block is not credited; the
next attempt restarts all 60 seconds. Input compression and source hashing are
outside the settling interval. SIGINT/SIGTERM preserve an interrupted attempt
and terminate any child process group.

Quiescence snapshots read only process `comm`, state, PID/parent PID, CPU/ticks and
affinity. They never read command lines or environments. Known project
benchmarks, engine/optimizer processes, fuzzers, compilers, build tools and CTest
are treated as overlap threats, except the current runtime child's process tree.
A threat during settling prevents that attempt from measuring; a threat during
the child invalidates its controls. Generic unrelated Python processes are
recorded without inventing their purpose. The root task must also ensure that
its Python analysis/conversion work has stopped before execution. Snapshot
sampling can miss short-lived activity and does not establish an exclusive host.

CPU 3 `/proc/stat` counters bracket both settling and the runtime process. Idle
ratio is the actual idle+iowait tick delta divided by total tick delta, excluding
guest double-counting. These ratios are descriptive; there is no fabricated
sibling-offline or isolation claim. AC power and CPU-2 frequency are sampled at
each process boundary. Every child row must additionally report actual
`cpu_before=cpu_after=2`, `ac_before=ac_after=true`, and positive nonnull
`freq_before_khz`/`freq_after_khz`. Missing/failed controls classify the whole
round as `control_failed`, preserve its observations, and prevent acceptance.

After all ten measured rounds are complete, the runner computes the session
median over all 18,000 accepted measured frequency samples. A case row is flagged
if either bracket sample differs from that median by more than 10%. Every flag
and every otherwise valid row/round is retained. There is no noisy-run filtering,
replacement, or post-hoc exclusion. This sampling does not prove steady CPU
frequency and cannot eliminate shared package-power, cache or thermal effects.

## Independent output checks and preservation

Each round must contain exactly the 900 unique expected DP rows, in its saved
order, with case IDs, budgets, coefficients, node/class/positive-node counts and
total bytes matching the saved metadata and original chunks. For every case
solved both in the original cost matrix and this runtime round, the exact scaled
objective, entire curve, store count, read/useful/waste/touched vectors,
deterministic cuts and complete-domain flag must agree. A digest binds those
cost/read/useful/curve observations. Timings and work/state counters are not
misrepresented as cost equality checks.

Timeout, state-limit and representation-limit rows remain non-solved observations
under the unchanged caps. They are retained, counted by status and never relabeled
as exact solutions or used as solved runtime. Cost comparisons are performed only
when both observations solved the same objective/budget/feasible set. Root-owned
statistics/figures will separately report solved coverage, outcome counts,
median/IQR/min/max and seeded bootstrap uncertainty under the runtime protocol.

The runtime directory contains an append-only journal, unique timestamped attempt
files, atomic current status/summary files, immutable accepted-round records,
input gzip/order identities, complete logs and GNU time resources. Resume accepts
only previously passed rounds whose source/protocol/binary/build/input/original
evidence identities, accepted/status records, gzip reconstruction, order,
outputs/logs/resources/process audit hashes and complete validation still agree.
Changed identities reject resume without overwriting the earlier session/result;
the rejection is preserved separately. Failed or interrupted rounds are never
silently accepted. A new attempt repeats input preparation and the full settling
block; all previous attempts remain recorded.

`results/p7/runtime-campaign.json` is compact and reaches `status=passed` only
after 11 complete, exit-zero, output-validated and control-validated rounds, plus
unchanged final dependencies. It contains all accepted round kinds, output
identities, actual PIDs/control records, environment references, outcome counts,
frequency-flag summary and links to raw records. The runner computes no runtime
bootstrap/scaling figure and does not create a P7/P8 gate. No run, measurement or
performance result was produced while preparing this runner/note.
