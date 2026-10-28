# P5 M2 publisher harness and measurement traceability

Access date: 2026-10-18. Approved P5.5 implements the harness and limited pilot;
the full experiment matrix and P6.2 noise/calibration studies remain deferred.
This is independent project code. No external code was copied.

The inspected pinned Google Benchmark v1.9.5 original source, revision
192ef10025eb2c4cdd392bc502f0c852196baa48, sections and hashes are retained in
[method reading](../p4/p5-method-reading.json), [merge sources](merge-sources.md)
and [pilot method](pilot-method.md). Setup before the state loop and
post-loop observations are outside its hot-loop timer. Adaptive iterations
remain enabled. Internal interleaving entropy is not exposed, so the actual
function invocation order is saved separately rather than inventing a seed.

| Source/finding → decision/invariant | Task → code/symbol | Validation → executed evidence |
|---|---|---|
| VALIDATION §6.1 M2 and §7 identical work | P5.5 `bench/micro/publish_bench.cpp`, `inputs`, `run`: same precomputed seeded owner/length schedule and rotating returned-sequence sink for index off/on; fresh Engine and actual first-eviction prefill per invocation | [60-profile functional matrix](M2-full-matrix-functional-20261018T160504.287611Z.json), 65,536 publishes/profile, index off/on seq/retention/payload equality plus invariants, passed. Reduced capacity65,536 is explicitly functional, not timed1GiB evidence |
| v1.1 generic-vs-ITCH sizing and registered unused roots | `config`: enforced minimum32-B DATA, `Index::sizing_blocks(C,32,B,P+1)`; ring1GiB for timed runs, max DATA272 | Functional matrix includes payload12/32/64/256/empirical, P1/100/10000, uniform/Zipf1.1, B256/1024; zero pressure required. Registered partitions include the unused root |
| S03 ITCH lengths; P1 full-day measured frequencies | `configs/m2_payload_mix.csv` and `.meta.json`, `read_mix`, rejection-sampled `bounded` | Mix has the18 actually observed types, aggregate counts and approved gzip/count/spec identities. Empirical workload is synthetic, with nonconstant bytes; no message-level source data is copied |
| VALIDATION §7 measured publish boundary | `run`: Engine.publish plus common schedule lookup/returned-sequence sink, batches4096; construction/registry/prefill/stats/logging excluded | Exact boundary appears in raw Google Benchmark context. Fresh prefill and measured start/end states, capacity/pressure/PAD losses and high-water values appear in invocation details |
| VALIDATION §§5.3/5.5, outcome-aware correctness | `bench_log.hpp::Invocation`, post-run independent pilot checker | Each adaptive prefix has its own head-sequence count and independently calculated rotate7/XOR expected sequence digest; different adaptive lengths are not compared as identical outputs. Actual timing/prefix audit pending |
| P4 resource-accounting contracts | `run` reports allocation/free/heap/sweep rates, live/stale/open/sealed slack, high-water and requested index bytes | Counters are deltas over measured publishes; zero sufficient-pool pressure checked. This run labels allocator-overhead measurement false; separate supported P4 allocator observations are not silently transferred |
| S42 repetitions and local nonprivileged fallback | `scripts/run_p5_pilot.py`: fifteen repetitions/case, adaptive0.5s, warmup0.2s, random interleaving, verified CPU2/AC/frequency, no concurrent project work | Runner/guards validated; final isolated M2 B256/B1024 indexoff/on timing and exact evidence audit pending |

The full `--matrix` exposes120 timed configurations. The limited pilot selects
payload64/P100/uniform and both block sizes, with both index arms. No full
campaign, Auto calibration, throughput-to-latency inference or minimum speedup
is claimed. Every failed/non-ok result and flagged frequency observation is
retained. Exact command results are in `commands.jsonl`; terminal evidence is
appended after the isolated pilot completes.


## Accepted terminal execution — 2026-10-19

The [limited M2 pilot](pilot-results.md) passed both B256/B1024 blocks, each
15 repetitions per index-off/on case:60 measured rows,94 total logged
invocations including warm-up/calibration. The [independent audit](pilot-audit.json)
checks every adaptive prefix against its own expected count and closed-form
sequence digest, exact prefill state, zero pressure and functional schedule
identity. All raw/provenance identities pass; no source/binary changed.
Full-matrix timings and P6 calibration remain unrun. Earlier pending entries
describe preparation and are superseded by these actual results.
