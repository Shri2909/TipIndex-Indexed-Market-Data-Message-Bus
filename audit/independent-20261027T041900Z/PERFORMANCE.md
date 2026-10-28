# Actual before/after diagnostics and tradeoffs

No performance improvement or universal nonregression is claimed. The primary experiment compares two separately built implementations: the preserved initial source and the final C++ source, both GCC15.2, `-O2 -g -march=x86-64-v3 -DNDEBUG`. It is not a comparison of two API paths on one changed binary. All32 workloads and non-winning observations are retained below. [Protocol](evidence/performance-protocol.json), [raw/normalization/process evidence](evidence/performance.json) and initial archive/binary identities make the comparison reproducible.

## Method

4096 DATA records, no-match/dense, small/wrapped-variable payloads, K64/K256, Indexed/StdPQ, budgets legacy/unlimited/1/32, output allowance128, seed20261027. Every arm uses immediate redrain and exactly one victim-reader and separate-engine publisher service after completion. Inputs, outputs, work counters, checkpoints, call counts and service policy are equal between source builds. Three fresh processes/source run in alternating initial/final pairs. The fixed seed/arm order and warm OS caches are retained. No process affinity, cache flushing or host-setting change was used in the primary run. Project-owned builds/tests/campaigns had finished before timing; the host remained shared, with observed load around1.2–3.2 in the saved host snapshots.

The experiment contains192 timing rows (32arms ×3processes ×2sources). Original tool repetition0 rows stay intact; derived files change only the process repetition label. Per-process nearest-rank percentiles are summarized by their median, with actual sample counts retained. The paired poll ratio is the median of three per-pair final/initial ratios; it need not equal a ratio of separately calculated medians.

Opening is measured separately. Public-poll latency includes internal preparation. Cumulative poll time excludes output hashing/caller service; drain CPU/wall include those operations. JSON evidence retains every opening, p50/p95/p99/max/sample count, cumulative work, CPU/wall and process peak RSS. Those RSS values are process-wide high-water observations across fixtures/arms, not an exact live fixture allocation or leak measure. Maximum reported primary peaks were35,463,168B initial and35,434,496B final; this small difference establishes no memory improvement.

## All primary workloads

Times are microseconds; initial/final columns are medians of three fresh-process observations. The ratio uses paired observations.

| Case | Shape | K | Budget | Initial poll total µs | Final poll total µs | Paired final/initial | Initial drain µs | Final drain µs |
|---|---|---:|---|---:|---:|---:|---:|---:|
| dense | small | 64 | 1 | 5727.795 | 5847.568 | 1.026 | 5999.110 | 6127.812 |
| dense | small | 64 | 32 | 469.663 | 479.260 | 1.011 | 610.092 | 622.642 |
| dense | small | 64 | legacy | 222.657 | 231.365 | 1.024 | 358.747 | 371.076 |
| dense | small | 64 | unlimited | 233.261 | 242.114 | 0.999 | 368.488 | 382.138 |
| dense | small | 256 | 1 | 20692.277 | 20762.322 | 1.003 | 20966.177 | 21044.387 |
| dense | small | 256 | 32 | 1230.586 | 1275.555 | 1.035 | 1372.212 | 1425.682 |
| dense | small | 256 | legacy | 495.032 | 513.135 | 1.037 | 631.315 | 651.693 |
| dense | small | 256 | unlimited | 506.909 | 510.268 | 1.027 | 643.166 | 646.411 |
| dense | wrapped-variable | 64 | 1 | 5524.913 | 6361.939 | 1.007 | 6118.615 | 6969.229 |
| dense | wrapped-variable | 64 | 32 | 475.257 | 476.184 | 1.015 | 953.905 | 959.174 |
| dense | wrapped-variable | 64 | legacy | 223.772 | 226.271 | 0.992 | 690.904 | 692.318 |
| dense | wrapped-variable | 64 | unlimited | 228.298 | 228.067 | 0.991 | 689.243 | 688.112 |
| dense | wrapped-variable | 256 | 1 | 20538.239 | 20716.851 | 1.009 | 21146.407 | 21327.915 |
| dense | wrapped-variable | 256 | 32 | 1242.176 | 1220.375 | 0.994 | 1710.697 | 1679.905 |
| dense | wrapped-variable | 256 | legacy | 497.971 | 487.915 | 0.996 | 958.896 | 945.487 |
| dense | wrapped-variable | 256 | unlimited | 497.666 | 498.121 | 1.006 | 950.926 | 953.940 |
| no-match | small | 64 | 1 | 5702.418 | 9735.718 | 1.738 | 5848.978 | 9953.888 |
| no-match | small | 64 | 32 | 450.394 | 702.450 | 1.483 | 455.327 | 710.677 |
| no-match | small | 64 | legacy | 112.722 | 198.488 | 1.775 | 113.089 | 199.469 |
| no-match | small | 64 | unlimited | 115.045 | 197.123 | 1.688 | 115.328 | 197.834 |
| no-match | small | 256 | 1 | 20897.863 | 19739.586 | 0.963 | 21066.119 | 19920.375 |
| no-match | small | 256 | 32 | 1274.010 | 1221.485 | 0.977 | 1279.481 | 1227.926 |
| no-match | small | 256 | legacy | 142.443 | 133.738 | 0.943 | 142.806 | 134.008 |
| no-match | small | 256 | unlimited | 158.212 | 141.923 | 0.958 | 158.502 | 142.186 |
| no-match | wrapped-variable | 64 | 1 | 5680.324 | 5525.979 | 0.976 | 5821.165 | 5660.929 |
| no-match | wrapped-variable | 64 | 32 | 451.301 | 447.518 | 0.991 | 456.150 | 452.415 |
| no-match | wrapped-variable | 64 | legacy | 112.128 | 106.446 | 0.961 | 112.399 | 106.723 |
| no-match | wrapped-variable | 64 | unlimited | 116.269 | 109.298 | 0.975 | 116.580 | 109.559 |
| no-match | wrapped-variable | 256 | 1 | 20937.634 | 20623.815 | 0.992 | 21097.225 | 20802.270 |
| no-match | wrapped-variable | 256 | 32 | 1271.928 | 1241.999 | 0.991 | 1277.492 | 1247.340 |
| no-match | wrapped-variable | 256 | legacy | 147.852 | 137.844 | 0.939 | 148.244 | 138.112 |
| no-match | wrapped-variable | 256 | unlimited | 147.993 | 143.801 | 0.972 | 148.280 | 144.098 |

Primary paired ratios range0.939–1.775. The largest losses occur in the first K64/small/no-match fixture; they are not discarded or labeled proven noise. Static Replay's functional path was unchanged by the Tail diagnostic fix, but binary/layout, allocator, startup, CPU scheduling/frequency and host effects are not causally separated by these short observations. No stable throughput-regression conclusion follows either.

## Predeclared follow-up for the observed loss

The retained loss justified a bounded follow-up, not a replacement of the primary result. The [follow-up protocol](evidence/performance-followup-protocol.json) specifies ten fresh process pairs, counterbalanced source order and child CPU affinity to the first allowed CPU (CPU0), with the same4096-record no-match workload and K64/K256 budgets. All160 rows, every pair ratio and host observation remain in [follow-up evidence](evidence/performance-followup.json). No privileged host setting changed. This run occurred on28October after the primary27October observations.

| K | Budget | Initial poll total µs | Final poll total µs | Median of10 paired ratios |
|---:|---|---:|---:|---:|
| 64 | 1 | 6407.873 | 7527.721 | 1.027 |
| 64 | 32 | 445.524 | 515.460 | 1.006 |
| 64 | legacy | 128.917 | 144.327 | 1.097 |
| 64 | unlimited | 136.887 | 157.559 | 1.195 |
| 256 | 1 | 21979.677 | 23642.642 | 0.971 |
| 256 | 32 | 1491.631 | 1381.085 | 0.989 |
| 256 | legacy | 181.552 | 149.688 | 0.958 |
| 256 | unlimited | 188.822 | 171.024 | 1.096 |

The follow-up ratios range0.958–1.195. It does not reproduce the original1.48–1.78 K64 loss magnitude, while retaining slower outcomes. Affinity/order/date changed together, so this does not prove which cause mattered, prove the first result was noise, or establish deployment nonregression. Further host-controlled inference remains a limitation, not a confirmed unfixed implementation bug.

## Cost mechanism retained by design

On the final primary K256/small/no-match fixture, legacy uses one poll and256 index seeks; budget32 uses128 polls/32,768 seeks; budget1 uses4096 polls/1,048,576 seeks. Cumulative poll medians are133.738µs,1,221.485µs and19,739.586µs respectively. Budget1's per-process p99 median is6.413µs versus legacy's single133.738µs call. These API-path comparisons on the same final binary explain the traversal/preparation tradeoff; they are separate from the actual source before/after table. A budget is not a complete-call deadline, and immediate redrain supplies no interleaved service benefit. No cursor/filter lifetime checks or approved semantics were removed to improve this timing.

The malformed-trace allocation correction also has direct structural before/after evidence: a68-byte invalid input formerly created a260,192-byte cache; the corrected parser rejects before count-sized allocation. Cleanup removes owned staging on handled failures. These are measured/verified resource effects, not a claimed engine throughput speedup. Analysis staging temporarily retains old/new output bundles to protect data; crash atomicity across several renames remains outside the contract.
