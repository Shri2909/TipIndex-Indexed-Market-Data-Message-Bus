# Legacy polling diagnostic

This is an **exploratory diagnostic on a noisy host with concurrent builds**.
It is not a controlled deployment benchmark and does not establish guaranteed
nonregression, speedup, or a latency bound. Each comparison used seven paired
rounds with alternating invocation order and `CLOCK_PROCESS_CPUTIME_ID`.
The benchmark study in the parent F-01 directory is separate evidence.

The first implementation routed existing `size_t` calls through `PollResult`
telemetry. `legacy_diagnostic.json` showed consistent short-call overhead.
`legacy_diagnostic_optimized.json` retained a first optimization that removed
telemetry but still copied `PollLimits` through the legacy call ABI.
`legacy_diagnostic_final.json` measures the final shared implementation, whose
legacy specialization takes `size_t`, returns `Status`, and compiles out new
inspection/delta accounting. Assembly inspection confirmed restoration of the
original vector-clear plus tail-jump wrapper, without stack copies of limits.

| Scenario | Final/baseline median CPU-time ratio |
| --- | ---: |
| Scan, one output per call | 0.982 |
| Indexed, one output per call | 0.973 |
| Already complete Replay | 1.049 |
| Scan, 500,000 rejecting records | 1.035 |
| Indexed, 500,000 rejecting candidates | 1.053 |

All paired output digests agreed. The wide per-round variation prevents a
precise throughput conclusion; the earlier consistent short-path penalties
were removed. `manifest.json` records source/binary identities, compiler flags,
and the 23 shared source/header files verified identical to the original
feature baseline. Focused final tests passed 77/77; these overlap the main suite
and must not be added to its count.

Retained Engine sources and the harness permit a fresh diagnostic without
overwriting these measurements. Existing scratch executables remain under
`build/f01/core-review`; they are not required by the reproducer.

```bash
cmake --preset release
cmake --build --preset release --parallel 2 --target \
  tiplog_ring tiplog_topics_subs tiplog_index tiplog_merge
python3 results/f01/legacy-diagnostic/reproduce.py \
  --output build/f01/my-legacy-diagnostic --libraries build/release
```

The output directory must not already exist. `--compile-only` validates the
retained harness/sources and builds both arms without taking new measurements.
The reproducer rejects changed shared sources rather than silently comparing
an old Engine against different Ring/Index/Registry/Merge implementations.
