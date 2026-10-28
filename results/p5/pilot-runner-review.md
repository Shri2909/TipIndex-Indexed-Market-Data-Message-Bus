# P5 pilot runner final source review — 2026-10-18

Status: **ready for root's final commit/quiescence review; actual pilot and its
post-run audit remain unrun**. This review changed no benchmark or engine source
and launched no timed benchmark. The only executed new work is the small,
CPU0-pinned digest algebra self-check described below.

Re-read `scripts/run_p5_pilot.py`, `bench/micro/{merge_bench,publish_bench}.cpp`,
`bench_log.hpp`, the M2 mix CSV/metadata, approved VALIDATION §§5–8, the joint
prompt's P5 boundary and the saved benchmark handoff/review. Supported reporter
flags and JSON fields were checked in the original pinned Benchmark1.9.5 source
revision `192ef10025eb2c4cdd392bc502f0c852196baa48`: `benchmark.cc` flag
definitions/parsing and default time unit; `benchmark_register.cc` default unit;
`json_reporter.cc` lines248–294 for `run_name`, individual repetition indices,
iteration counts and non-ok fields. Earlier inspected adaptive timing/shuffle
sections remain recorded in [the method note](pilot-method.md). No library code
was copied and no external performance result is transferred.

No flag/case-count blocker was found. The runner registers fifteen M1 cases
(three profiles, four kernels plus second Quad geometry) and two cases in each
M2 process. Fifteen repetitions require **285 individual rows** overall. Both
index arms share the same schedule object within each M2 process. Full1GiB ring
prefill passes a real capacity eviction outside timing; counters and setup are
outside the hot loop. Min warm-up0.2s, adaptive min time0.5s, random interleaving
and individual JSON are preserved. Exact iteration caps are absent.

The runner separately saves whole-child/setup-inclusive time/getrusage, fresh
environment, real Git/dirty/source/binary/input identities, actual CPU2 invocation
boundaries, AC/frequency observations, failed probes/outcomes and sixty-second
monotonic settling. Its observer excludes CPUs2–3. Frequency flags retain raw
rows. Visible-process snapshots plus the root declaration cannot establish host
isolation or perfect SMT-sibling idle; `/proc/stat` observations and that limit
must remain in reporting. No P6 confidence interval, full matrix or measured
Auto calibration is implied. The earlier runner-validation JSON contains
**12 checks**; the prior message saying13 was a counting error.

One acceptance gap was found: M2's timed function checks publication count and
zero pressure, but records its rotating sequence sink without independently
checking that digest. Root requested and this review supplied
`scripts/check_p5_pilot.py` to close it after timing, without changing frozen
benchmark sources. For each adaptive invocation it checks start/end sequence,
`iterations*4096`, prefill/zero-pressure state and the expected sequence digest.
The independent closed form groups output indices by residue modulo64: each
group has one rotation, a constant low6-bit value and consecutive high58-bit
values whose XOR is computed from the four-case prefix identity. This costs
O(64) per invocation, including very large adaptive counts.

Executed command:
` .venv/bin/python scripts/run_check.py p5 pilot-digest-self-test -- taskset -c 0 .venv/bin/python scripts/check_p5_pilot.py --self-test `.
It passed **747 cases**: literal recurrence against the closed form on seeded
small/random/carry/rotation/uint64 boundaries, large-count concatenation checks
and invalid-range rejection. Exact command/context/exit/log are in
[the command record](pilot-digest-self-test-20261018T160835.089527Z.json) and
[self-test result](pilot-digest-self-test.json). This is algebra verification,
not a performance result.

The auditor itself was also exercised on a synthetic saved-artifact tree:
285 individual rows and285 invocations across all three blocks passed; a
same-count M2 invocation with a corrupted digest was rejected; a nonfinite
measured value was rejected. These three checks passed in the CPU0-pinned
command record [pilot-auditor-validation](pilot-auditor-validation-20261018T161017.889297Z.json)
and [result](pilot-auditor-validation.json). The fixture contains no benchmark
measurements and is not a passed actual pilot.

After the pilot, root must run
`.venv/bin/python scripts/check_p5_pilot.py results/p5/pilot-latest.json` and retain
`results/p5/pilot-audit.json`. In addition to M2 prefixes, it verifies current
source/binary/input hashes, raw-log hashes, expected profile/repetition counts,
invocation order/CPU/seed/status, and M1 input/output hashes against the saved
independently sorted functional verification. GBench bulk reporting does not
identify an exact warm-up/calibration-to-measured-row mapping; the audit checks
every invocation and requires measured iteration-count coverage instead of
inventing that mapping. A passed orchestrator session alone does not close this
digest-audit requirement.

Remaining actual-run prerequisites: final source commit, completed F3/checks,
root quiescence declaration, fresh mandatory AC/P-core pin verification, all
three isolated pilot blocks and the independent terminal audit. Root separately
owns the reduced explicitly **simulated Cachegrind** diagnostic. These are
pending execution requirements, not requests for renewed user permission.
