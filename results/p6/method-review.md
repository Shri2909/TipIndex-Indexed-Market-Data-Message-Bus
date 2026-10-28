# P6 statistical and benchmark-method review — 2026-10-19

Scope: ST-12, P6.1–P6.5, Tier B. This ledger records primary material actually
inspected for implementation. It is not an execution/gate claim. Actual campaign
commands, status counts and raw inputs must be attached after collection.

| Source/finding | Actually inspected and limits | Project decision/task | Code and check |
|---|---|---|---|
| S41 [LLVM Benchmarking tips](https://llvm.org/docs/Benchmarking.html) | Introduction, General, Linux and Linux Intel sections, read 2026-10-19; page displays LLVM24.0.0git and last update2026-10-18. No source-code reuse. | Reuse approved nonprivileged environment controls; CPU2/P-core and AC checks, process repetitions, settled measurement blocks. Record unavailable controls and frequency flags. Quiet runs cannot exclude setup bias. | Runner environment/protocol artifacts; `analysis.summarize.summarize_rows` retains flagged observations. |
| S44 [Mytkowicz et al., Producing Wrong Data Without Doing Anything Obviously Wrong!](https://sape.inf.usi.ch/publications/asplos09) | Author-maintained publication page, title/authors/DOI and abstract only. Full paper remains unread. | Preserve build/environment identity and actual interleaving. No claim that low CV proves unbiased results; optional link-order/padding study stays Tier C. | Runner provenance plus report limitations; no paper algorithm implemented. |
| S44 [Kalibera & Jones, Rigorous Benchmarking in Reasonable Time](https://kar.kent.ac.uk/33611/) | Institutional repository bibliographic record and abstract only. The page notes a corrected accepted manuscript; that manuscript was not inspected. | Distinguish within-process micro repetitions from process-level recovery repetitions. Explain uncertainty/repetition levels. The project's prescribed bootstrap is not represented as the paper's implemented algorithm. | `analysis.stats.median_summary`, `paired_ratio`; meaningful shared-round-noise and ragged-block tests. |
| S42 pinned Google Benchmark1.9.5 | Reused exact prior inspected sections/revision/hashes in [P5 reading ledger](../p4/p5-method-reading.json) and [method](../p5/pilot-method.md). Revision192ef10025eb2c4cdd392bc502f0c852196baa48. No new library code copied. | Preserve15 adaptive repetitions, random interleaving, .2s warm-up/.5s minimum time and individual JSON. Library internal entropy is not a replayable project seed; keep actual invocation order. | Existing original M1/M1-touch/M2 harnesses and campaign runner. |
| VALIDATION §§5.3–5.5 and §7; FINDINGS row49 | Approved project contract, not an external empirical claim. | Seeded10,000-resample95% percentile-bootstrap median CIs; whole paired rounds for ratios; retain every non-ok outcome and warm-up. Withhold ratios if a pairing is missing or failed. | `analysis.stats`, `analysis.summarize`; `py/tests/test_analysis_stats.py`. |
| VALIDATION T2 and fairness rule | Approved requirement to expose index maintenance. | Add signed actual index-on/off publisher CPU **per publisher market second** once per R-reader cohort, not once per reader. The1800s publishing window and10s recovery backlog each use their own denominator. Keep noisy negative deltas. Report recovery-only and adjusted totals. | `analysis.summarize.t2_amortized`; exact one-cohort, unequal-window-duration and negative-noise tests. |
| VALIDATION F06–F13, RC-1 | Approved figures and regeneration gate. | Figures derive only from saved actual normalized rows. Missing required experiment inputs are errors; no placeholder figures, invented work counters or zero-filled absent allocator observations. | `figures.tip.build`, figure-input manifest and regeneration checks. |

The bootstrap estimates variability under this observed experimental design. It
does not establish a fixed clock, exclusive host access, session completeness,
hardware-counter availability or a latency distribution. Throughput and recovery
CPU time remain distinct from T4 request latency, which is deferred with Tier C.

Jane Street's published message-bus statements remain the article's observations.
The engine, merge kernels, Auto rule, model and experiments are independent project
work. No unavailable Aria implementation or external speedup is inferred.

ST-12 exercise: CPU2 affinity and CPU/sibling observations require no privileged
system changes. System governor/turbo/SMT shielding changes would need privileges
and remain outside the approved default. A permitted per-process ASLR attempt is
recorded at execution time. Repeating and shuffling complete process runs makes
process variation observable and balances ordering effects; it cannot guarantee
absence of bias. Reciprocal throughput is a rate per delivered output, not a
distribution of response times for independently scheduled requests.

Development verification: [saved command and result](analysis-unit-checks-cc4-final-20261019T012900.069572Z.json)
executed15 tests successfully (3.67s pytest time), including shared-round noise
cancellation, ragged whole-block resampling, missing/failed pair withholding,
CC-4-invalid observations, unequal publisher/recovery durations, incompatible
build identities, and all eight figures from explicitly synthetic pytest-temp
fixtures. These fixtures are format tests, not measured project results. The
full actual experiment/figure gate remains pending.

For constant observations every possible bootstrap resample has the same median;
the implementation returns that exact degenerate interval without redundant
random draws. All nonconstant inputs use the prescribed10,000 seeded resamples.
Failed CC-4 measurements have an explicit reporting status `oracle_mismatch`;
the original engine status remains in raw rows and `raw_status_counts`. Such
observations contribute to failure accounting and never to performance CIs.
