# Methodology: how the benchmarks were run and what they show

Detail: [technical report](report/REPORT.md), [results_tip.md](report/results_tip.md). See also the [README](../README.md) and [ARCHITECTURE](ARCHITECTURE.md).

## Summary

We measured the CPU time to replay a retained backlog (a consumer catching up from a sequence number) with **Scan** (filter every record), **Indexed** (read per-partition position lists, then merge) and **Auto** (picks one). We also measured publisher cost, polling responsiveness and modeled layout bytes. Each timing is a paired comparison from fresh-process rounds on a pinned core, with 95% bootstrap intervals, and counts only if output matched an independent oracle. The result is a trade-off: indexing wins for one symbol and loses for a broad subscription.

> One laptop (Intel Core i5-1235U), one trading day (2019-12-30), one 09:30-10:00 window of 32,817,244 records. Timings come from the 24-25 October 2026 study and describe the pre-remediation source; no fresh campaign is claimed. CPU frequency was not fixed. Intervals describe run-to-run variation on this machine, not variation across trading days. Consumer workloads and the layout cost model are assumptions.

## What was measured

| Name | One-line meaning |
|---|---|
| M1 | Merge cost per output for four merge kernels on synthetic lists |
| M2 | Publisher cost per message, index on versus off |
| M3 | How index block size changes seek and scan cost |
| T1 | Replay CPU time, Scan vs Indexed vs Auto, on the real window |
| T2 | Total CPU for cohorts of sequential readers, plus publisher index cost |
| T3 | Held-out synthetic grid: where each mode wins; frozen Auto policy |
| Polling study | Per-call time of an optional inspection budget (F-01) |
| Layout model | Modeled read bytes of storage layouts; no disk I/O |

No minimum speedup was required; a loss is a valid result.

## Data and workload

- **Real data:** Nasdaq TotalView-ITCH 5.0, 2019-12-30. Timing window: 32,817,244 records, 947,677,397 payload bytes, 62,964 topic ids. The sample lacks its session terminator (`incomplete=true`).
- **Headline setup:** 10:00 anchor, 10 s backlog, 1 GiB ring, 1,024-entry index blocks, repeat-warm cache (second identical replay).
- **Synthetic data:** seeded; Auto thresholds trained on seed 20191230, frozen, tested on seed 20191231.
- Raw ITCH and traces are not in Git ([packaging](report/PUBLIC_PACKAGING.md)).

## Environment and controls

- Core i5-1235U (2 P-cores, 8 E-cores), Linux, GCC 15.2 `-O2 -g -march=x86-64-v3 -DNDEBUG`, Google Benchmark 1.9.5.
- Single-threaded. Timed work pinned to CPU 2 (a P-core); SMT sibling CPU 3 idle; E-cores never timed; observers on other CPUs.
- AC power; saved quiescence record (no concurrent builds or benchmarks); ASLR off per process (`setarch -R`).
- Frequency sampled at run boundaries; runs over 10% off the session median are flagged and kept. 60 s settle per block.
- Governor, turbo and SMT recorded, never changed: `powersave` with turbo, about 4.1-4.36 GHz observed.

## Method and statistics

- **Timed:** `open_replay` through completion (seek, filter, merge, output sink), not trace load or prefill. Every mode gets the same inputs and sink.
- **Repetition:** fresh process per round, one warm-up excluded, random interleaving. Microbenchmarks: 15 repetitions. Replay and memory: 20 paired rounds.
- **Pilots:** CV limits 3% (M1) and 5% (T1). M1 measured 1.85%; T1 9.87%, so replay rounds rose to 20.
- **Statistics:** median, IQR, min/max, n; seeded 10,000-resample percentile bootstrap 95% interval. Ratios resample whole matched rounds together (paired).
- **Nothing dropped:** flagged runs and non-ok outcomes are kept: 125,700 ok, 4,320 `invalid_config` (indexed cursor limit), 1 externally interrupted micro attempt, 0 oracle mismatches.

## Correctness gate

An invalid fast run is not a result. Every timed output was checked against an independent oracle (tests-only `ScanOracle`; Python oracle from the trace): 10,295,181 checks, 0 failures. The [independent audit](../audit/independent-20261027T041900Z/REPORT.md) (accepted 28 October 2026) reports 230 CTests per preset in 4 builds, 499 Python tests, 108,000,000 differential operations and 14 findings fixed; it is bounded, not proof of no defects.

## The polling study differs

It ran on 27 October 2026 on a shared, unpinned host, 3 fresh processes per arm (758 arms, 2,274 rows), with no confidence intervals ([results](report/POLL_BUDGET_RESULTS.md)). The 1.775 ratio is not from it: it is the worst paired ratio (range 0.939-1.775) in the audit's initial-vs-final source comparison on small fixtures; no regression or improvement is claimed ([PERFORMANCE.md](../audit/independent-20261027T041900Z/PERFORMANCE.md)).

## Threats to validity

- One laptop, one trading day, one window.
- Shared host (another project's services); frequency not fixed; CPU 2 not interrupt-isolated.
- No hardware counters (`perf_event_paranoid=4`): no cache or branch explanations.
- P6 timings describe the pre-remediation source; the polling study is unpinned.
- Replay is CPU time, publisher paused, readers sequential: not latency or concurrent scaling.
- Consumer mixes and layout costs are assumptions. "Exact" means optimal for the model, only where the solver finished (one workload: 2,034 of 8,907 partitions).
- Auto was trained on a finite grid; held-out losses remain.

## Claim ladder

| Claim | Status | Evidence and limit | Detail |
|---|---|---|---|
| One symbol: Scan 3.92 ms vs Indexed 0.096 ms, 40.6x | Measured | 20 paired rounds | [results](report/results_tip.md) |
| Broad (top 1,000): 14.2 vs 24.3 ms, 0.585x; Auto picks Scan | Measured | Same setup; index loses | [results](report/results_tip.md) |
| Publisher: 124.4 vs 62.3 ns/message, 10,000 partitions | Measured | 15 repetitions | [REPORT](report/REPORT.md) |
| Polling: one 17.348 ms poll vs 1,000 polls, p99 29.957 us | Measured, shared host | Unpinned, 3 processes; total work grows | [polling](report/POLL_BUDGET_RESULTS.md) |
| Layout: 27.9% fewer weighted read bytes | Modeled | Uniform consumers; no disk I/O | [layout](report/results_layout.md) |
| Output correctness | Checked | 10,295,181 oracle checks; bounded audit | [audit](../audit/independent-20261027T041900Z/REPORT.md) |
| Parity with Jane Street's Aria or production; latency; other days or hardware; durability | Not claimed | No Aria code; different data and workload | [REPORT](report/REPORT.md) |

## Reproducing and tuning

Saved results are historical. The official runners (`scripts/run_p5_pilot.py`, `scripts/run_p6_campaigns.py`) are hash-locked to a frozen source tree and refuse to run after source edits (failure text: `empirical payload mix identity mismatch: spec_table_source_sha256`); a fresh run needs a recorded re-freeze decision. The full campaign takes about 25 h and 7 GB+ of disk. For the current source use `scripts/check_all.sh`. Commands: [REPRODUCE.md](report/REPRODUCE.md); setup: [REMEDIATION.md](report/REMEDIATION.md).

**Optional CPU tuning** (needs sudo; the study used none of it). `no_turbo=1` caps P-cores near the 1.3 GHz base clock, so results are **not comparable** to the published study.

```bash
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference
echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo
```

Revert afterwards (`cat` the old values first; defaults vary):

```bash
echo powersave | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
echo balance_power | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference
echo 0 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo
```

Thermal-throttle check: [REPRODUCE.md section 12](report/REPRODUCE.md#12-benchmark-environment-and-cpu-tuning).
