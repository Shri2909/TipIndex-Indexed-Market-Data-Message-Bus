# P5 limited pilot results — 2026-10-19

All three isolated blocks passed; the independent auditor passed 3821 checks over285 measured rows and369 logged invocations. Every selected case has15 repetitions and zero non-ok outcomes.

The table gives descriptive medians for these selected cases. M1 units are ns/output; M2 units are ns/publish. P6 full experiments, confidence intervals and calibration remain unrun.

| Profile | n | CPU ns/item | Wall ns/item | Non-ok |
|---|---:|---:|---:|---:|
| M1-touch/k64/uniform/N4194304/BinHeap | 15 | 20.238 | 20.238 | 0 |
| M1-touch/k64/uniform/N4194304/Loser | 15 | 14.604 | 14.604 | 0 |
| M1-touch/k64/uniform/N4194304/Quad-pad0 | 15 | 29.154 | 29.154 | 0 |
| M1-touch/k64/uniform/N4194304/Quad-pad3 | 15 | 28.224 | 28.224 | 0 |
| M1-touch/k64/uniform/N4194304/StdPQ | 15 | 34.655 | 34.750 | 0 |
| M1/k64/geometric64/N4194304/BinHeap | 15 | 5.254 | 5.254 | 0 |
| M1/k64/geometric64/N4194304/Loser | 15 | 9.155 | 9.272 | 0 |
| M1/k64/geometric64/N4194304/Quad-pad0 | 15 | 5.500 | 5.582 | 0 |
| M1/k64/geometric64/N4194304/Quad-pad3 | 15 | 4.999 | 4.999 | 0 |
| M1/k64/geometric64/N4194304/StdPQ | 15 | 19.524 | 19.523 | 0 |
| M1/k64/uniform/N4194304/BinHeap | 15 | 17.459 | 17.459 | 0 |
| M1/k64/uniform/N4194304/Loser | 15 | 10.911 | 10.922 | 0 |
| M1/k64/uniform/N4194304/Quad-pad0 | 15 | 28.386 | 28.386 | 0 |
| M1/k64/uniform/N4194304/Quad-pad3 | 15 | 26.766 | 27.214 | 0 |
| M1/k64/uniform/N4194304/StdPQ | 15 | 31.407 | 31.407 | 0 |
| M2/payload_64/P100/uniform/B1024/index_off | 15 | 47.445 | 47.442 | 0 |
| M2/payload_64/P100/uniform/B1024/index_on | 15 | 58.707 | 58.705 | 0 |
| M2/payload_64/P100/uniform/B256/index_off | 15 | 46.657 | 46.655 | 0 |
| M2/payload_64/P100/uniform/B256/index_on | 15 | 59.679 | 59.677 | 0 |

Frequency: 128 of744 sampled endpoints exceed10% of the session median. All associated data remain retained. These endpoints include setup and do not identify constant hot-loop clocks or exact affected measured rows.

Fresh AC/P-core/CPU2 checks passed, each block settled for at least60 monotonic seconds, and no project fuzzing/tests/builds/conversion ran concurrently. The observer excluded CPUs2–3. Visible-process snapshots and sibling CPU observations do not prove exclusive host access. The fresh per-process ASLR probe succeeded and measured children used setarch-R; system settings remained unchanged.

[Session and raw directory](../../results/raw/P5/20261019T005945.758576Z_aa13c1824ba5-dirty_abc-HP-Laptop-15s-fq5xxx/session.json), [independent audit](pilot-audit.json), [summary](pilot-summary.json), [per-repetition build/run provenance](pilot-repetitions.jsonl), [method](pilot-method.md), [whole-process simulated Cachegrind](cachegrind-summary.json).

All source/binary/input/raw-file identities match. M1 output/input hashes match independently sorted functional references. Every M2 adaptive prefix matches an independent closed-form sequence digest and count, including actual prefill/zero-pressure state. Whole-child/user/system diagnostics include setup and cannot substitute for hot-loop CPU time.
