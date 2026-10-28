# P6 retained-log experiments — tiplog v1.1 / Tier B

Completed artifacts, 2026-10-25 (Asia/Kolkata). All timing campaigns, the final
saved-output audit, statistical analysis and one-command figure regeneration
have passed. Numerical summaries are byte-identical across the presentation
corrections. Final acceptance is recorded in `results/p6/phase-gate.json` and
PROGRESS. The instruction is to finish P6 and stop; P7/P8 have not started.
Tier C and roadmap implementation remain outside this phase.

## Scope and questions

This report evaluates a deterministic, single-threaded C++20 retained-log
engine. Exact/subtree subscriptions read a byte-bounded ring either by scanning
the retained stream or by merging partition-index cursors. Auto uses thresholds
selected on separate training data. Publishing is paused during T1–T3 recovery.

The questions are conditional: when does index-assisted recovery save CPU work;
which merge kernel suits a particular interleaving; what does index maintenance
cost publishers; and how do block size, stale entries, slack and allocator
accounting affect memory? No minimum speedup or universal kernel winner was a
success criterion. T2 readers are served sequentially on one core.

Jane Street's article motivates partition indexes and shared blocks. Its
published observations, private Aria implementation and server-level CPU
results are not reproduced or transferred to this project. The C++ kernels,
Auto policy, replay contracts and experimental outcomes are independent project
work. Original-material reading depth and limitations are retained in the
[research ledger](../plan/RESEARCH.md), [merge-source ledger](../../results/p5/merge-sources.md)
and [P6 method review](../../results/p6/method-review.md). Abstract-only sources
are not represented as full-paper studies or implemented algorithms.

## Inputs, source identity and environment

The sole real source is the 2019-12-30 Nasdaq ITCH sample. Independent parsers
counted **268,744,780 messages and 8,251,407,909 decompressed bytes**. The
09:30–10:00 window used here contains **32,817,244 records**, 947,677,397 payload
bytes and 62,964 topic IDs. The accepted spec-hierarchy trace is
`data/traces/itch_20191230_0930_1000_spec.mdt`, SHA-256
`6062bdb96ec8354ecf650cdfb979574530b2120aa06047fa48d14a78e5936f70`.
Input identities, conversion metadata and independent reconciliation are in
[the manifest](../../data/manifest.json) and [P1 evidence](../../results/p1/).

**Input caveat:** gzip integrity and complete framed parsing do not establish a
complete exchange session. The source lacks the BinaryFILE zero-length
terminator and remains `incomplete=true`. No order-book consistency, complete
session, cross-day generalization or trading-performance claim is made.

Timing used the GCC 15.2 release build with `-O2 -g -march=x86-64-v3 -DNDEBUG`
and C++20 on an Intel Core i5-1235U laptop. The benchmark was pinned to CPU2,
a P-core; runtime records check CPU at both ends of replay. The recorded Git
base is `aa13c1824ba5a7a3593a0f63c6f455cac851e822` with `dirty=true`; the source,
binary, compile-command and input hashes in each campaign provenance are the
actual experiment identities, rather than a claim that HEAD alone describes
the build. Managed `.git` metadata was preserved.

AC power, actual per-process ASLR disablement, frequency observations and at
least 60 seconds of settling per workload/block were required and recorded.
No privileged governor, turbo, SMT or kernel configuration change was made by
this project. Hardware event access remained unavailable with
`perf_event_paranoid=4`, so counters are null. Historical reduced Cachegrind
diagnostics are simulated and are not hardware measurements of these runs.

The host was **not exclusive**. The resume record documents existing
`predcup-recorder.service` and `predcup-stops.service` background services from
another project, present during the preceding boot as well. Existing kernel
isolation parameters concerned CPUs4–5, not benchmark CPU2. Project builds,
tests, fuzzing, conversion and optimizer campaigns were not run alongside the
timing campaign. Desktop/system activity and laptop thermal/frequency effects
remain threats to validity. Full environment and resume observations are kept
in [evaluation state](../../results/raw/P6/campaign-20261024/evaluation/state.json)
and [resume quiescence](../../results/p6/measurement-quiescence-resume.json).

## Measurement and statistics

M1/M1-touch time the merge work on the same deterministic lists and common
output sink; M1-touch additionally loads eight bytes per output from a fully
initialized 1 GiB array. M2 times batched publishing with the same input
schedule and index enabled/disabled after prefill/initial eviction. M3 uses the
accepted real-window partition sizes for index seeks and chronological scans.

T1–T3 time `open_replay` through completion, including seek, filtering,
merging and the common output sink, excluding trace load, ring prefill and
subscription compilation. A separate stronger-digest replay must agree with
the timed execution. Python expectations are independent of production replay
helpers and compare delivered sequences/payloads, explicit outcome and resume
checkpoint; invalid/expired cases are not successful timing observations.

Two cache treatments are separate strata: **repeat-warm** measures the second
identical replay; **scratch-thrashed** accesses a 64 MiB scratch buffer before
timing. The latter does not prove that every target cache line is cold.

The two prescribed 30-repetition pilots yielded M1 CV **1.8481%** and T1 CPU CV
**9.8730%**. The declared noise response retained 15 micro repetitions and
increased recovery to **20 fresh-process measured rounds per configuration**,
plus one saved, excluded warm-up. Micro repetitions use Google Benchmark1.9.5
with random interleaving, 0.2-second minimum warm-up and 0.5-second minimum
measurement target. Its adaptive invocations and actual order are preserved;
micro repetitions are not invented paired process rounds.

Training used seed20191230 and eight synthetic workloads, yielding 14,400
measured query rows. It selected `max_partitions=64`, `max_fraction=1.0` from
the finite declared grid. The [Auto policy](../../results/p6/auto-thresholds.json)
and [protocol](../../results/p6/protocol-freeze.json) were frozen before
evaluation. Held-out synthetic data use seed20191231. This finite-grid training
does not establish an optimal policy.

Per-configuration statistics are median, IQR, min/max, sample count and seeded
10,000-resample 95% percentile-bootstrap CIs. Recovery ratios resample complete
matched process rounds together. These intervals describe observed run
variation; they do not correct setup/host bias or establish a population of
independent market days. Frequency deviations over10% of the session median are
flagged and retained. Missing frequency evidence is unknown, never zero.

T2 reports both reader-only CPU rate and a rate including index maintenance.
For an indexed/Auto cohort the adjusted rate is

`reader_cpu_ns / reader_market_seconds / 1e9 + (publisher_on_ns - publisher_off_ns) / publisher_market_seconds / 1e9`.

The actual 1,800-second publishing window and 10-second reader backlog retain
their own denominators. The signed publisher delta is charged once to the
whole cohort, not once per reader; Scan excludes that extra index charge.
[Report-only paired T2 analysis](../../results/derived/t2-adjusted-paired.json)
uses that formula and the same whole-round bootstrap. Its
[source](../../scripts/summarize_p6_t2_adjusted.py) reads persisted results only.

## Executed coverage

| Family | Declared coverage | Measured repetitions |
|---|---|---:|
| M1 + M1-touch | 10 k values ×9 owner patterns ×5 arms, including both Quad padding layouts ×2 fetch regimes =900 configurations | 15/configuration |
| M2 | 5 payload profiles ×3 partition counts ×2 owner distributions ×2 block sizes ×2 index states =120 configurations | 15/configuration |
| M3 | 4 block sizes ×seek/scan =8 configurations | 15/configuration |
| T1/T2 real data | 1 GiB and2 GiB workload groups, declared backlogs/subscriptions and reader cohorts | 20/configuration +saved warm-up |
| T3 | 3 partition counts ×3 skew values ×3 owner-run lengths =27 workloads;162 query/mode/cache comparisons each | 20/configuration +saved warm-up |
| T5 | 4 block sizes ×3 exclusive snapshot anchors =12 workloads; two cache treatments | 20/configuration +saved warm-up |

All41 evaluation workloads finished: **820 measured process rounds plus41
saved warm-ups**. The pre-consolidation saved-output audit records538,776 raw
request outcomes including warm-ups; T2 reader outputs are additionally retained
individually while normalized cohort rows aggregate costs and link those readers.
The campaign and exact commands are in
[campaign.json](../../results/raw/P6/campaign-20261024/campaign.json).

## Numerical results

All tables below use accepted actual observations. Median95% bootstrap intervals
are in brackets; micro tables have15 measured repetitions per configuration,
and recovery/memory tables have20 fresh-process rounds. Complete IQR, min/max,
sample count, noise labels and raw references accompany every configuration in
[tip-summary.json](../../results/derived/tip-summary.json) and
[tip-statistics.csv](../../results/derived/tip-statistics.csv).
The consolidated source SHA-256 is
`f2b440dbc5a285152821fa886c7644741ea89ebc4f812407640b6d2de62d264f`.

### M1/M1-touch: conditional merge costs

At64 requested streams and2²² outputs, median CPU ns/output:

| Kernel | Uniform owners (`zipf0`) | Geometric owner bursts, mean256 |
|---|---:|---:|
| StdPQ |32.757 [31.927,34.765]|19.881 [19.357,21.276]|
| BinHeap |19.926 [19.545,20.460]|4.540 [4.485,5.318]|
| Quad, three prefix words |29.052 [28.441,30.970]|4.850 [4.729,5.211]|
| Loser tree |11.281 [10.940,12.172]|9.500 [9.389,9.922]|

Loser-tree replay is advantageous in this interleaved case, whereas the
early-exit binary heap benefits from long same-owner runs. These are selected
declared strata illustrating the crossover, not proof of a universal ordering.
Both Quad padding layouts and every k/pattern appear in the complete tables;
k=1 is explicitly degenerate rather than an interleaving experiment.

Adding the record touch changes the corresponding cost: Loser/`zipf0` becomes
**14.074 [14.028,14.166] ns/output**, and BinHeap/`geometric256` becomes
**9.812 [9.808,9.820] ns/output**. Merge-only costs cannot substitute for full
recovery. No branch/cache causal attribution is made without hardware counters.
[F06](../../results/figures/F06_merge_cost_vs_k.png) and
[F07](../../results/figures/F07_merge_run_length.png) retain all declared strata.
Raw examples: [M1 k64](../../results/raw/P6/M1/20261024T044043.895991Z_aa13c1824ba5-dirty_abc-HP-Laptop-15s-fq5xxx/M1-k64-attempt001/gbench.json),
[M1-touch k64](../../results/raw/P6/M1/20261024T044043.895991Z_aa13c1824ba5-dirty_abc-HP-Laptop-15s-fq5xxx/M1-touch-k64-attempt001/gbench.json).

### M2: publisher index-maintenance cost

For the empirical Nasdaq payload-size mix, uniform partition selection and
B=256, CPU ns/publish:

| Partitions | Index disabled | Index enabled |
|---|---:|---:|
|1|57.187 [57.119,57.219]|70.720 [70.170,70.930]|
|100|57.196 [57.127,57.268]|71.188 [71.148,71.238]|
|10,000|62.316 [59.018,63.308]|124.428 [123.378,129.413]|

Index maintenance is an observable publishing cost and grows substantially in
the high-partition uniform case. All120 configurations, including fixed payloads,
skew, B=1024, evictions and allocation/reclamation counters are in the complete
summary and [F08](../../results/figures/F08_publish_index_cost.png). These
microbenchmarks do not replace T2's actual same-window index-on/off publisher
measurements. [Raw M2 campaign](../../results/raw/P6/M2/20261024T104904.812764Z_aa13c1824ba5-dirty_abc-HP-Laptop-15s-fq5xxx/session.json).

### M3: block-size seek and scan costs

This fixture uses all32,817,244 real-window postings, not a bounded T5 snapshot.

| Entries/block | CPU ns/seek | CPU ns/scanned entry |
|---|---:|---:|
|64|145.327 [132.593,146.098]|5.596 [5.576,5.634]|
|256|114.596 [102.117,116.488]|4.235 [3.780,4.261]|
|1,024|114.273 [111.854,115.417]|3.729 [3.432,3.803]|
|4,096|133.398 [133.009,135.802]|3.642 [3.621,3.683]|

Larger blocks reduce the measured sequential scan cost here, while seeking is
not monotone in B. This does not make4096 a universal choice; its reserved-memory
cost is exposed below. [Raw M3](../../results/raw/P6/M3/20261024T121915.466248Z_aa13c1824ba5-dirty_abc-HP-Laptop-15s-fq5xxx/M3-real-partition-sizes-attempt001/gbench.json).

### T1: real-data selective and broad recovery

At the10:00 anchor,1 GiB ring, B=1024,10-second backlog and repeat-warm treatment,
median CPU milliseconds:

| Subscription | Scan | Indexed BinHeap | Auto/BinHeap |
|---|---:|---:|---:|
| BOOK top1 |3.916 [3.812,4.009]|0.0964 [0.0960,0.0975]|0.0971 [0.0961,0.0982]|
| BOOK top1000 |14.239 [14.135,14.471]|24.342 [24.271,24.449]|14.487 [14.348,14.568]|
| Full stream |17.658 [17.614,17.729]|17.705 [17.588,17.867]|18.044 [17.693,18.116]|

For BOOK-top1, Scan/Indexed-BinHeap is **40.619 [39.452,41.693]** over20 paired
rounds. Indexed replay fetches1,573 candidates versus184,550 scanned records,
and both deliver1,571 events. The selected partitions' traffic fraction, not
merely the final matching fraction, explains the avoided traversal work.

BOOK-top1000 gives the opposite result: Scan/Indexed-BinHeap is
**0.585 [0.581,0.593]**. Auto chooses Scan there; its ratio to Scan is close to
one but not free of planning/noise effects: Scan/Auto is
**0.983 [0.976,0.999]**. Full-stream requested Indexed/Auto modes use the defined
Scan fallback; their timing is not evidence of a fast full-stream index path.
The full-stream Scan/Indexed ratio is **0.997 [0.987,1.006]**.

The complete14-subscription,1/10/60/300-second matrix and2 GiB longest-backlog
group are retained in [F09](../../results/figures/F09_catchup_breadth.png),
[F10](../../results/figures/F10_replay_work.png) and the complete tables. These
examples establish neither a universal speedup nor a latency distribution.
[Raw recovery observations](../../results/raw/P6/campaign-20261024/evaluation/runs.jsonl)
and [paired ratios](../../results/derived/tip-paired-ratios.csv) retain exact IDs
and process references.

### T2: sequential reader cohorts with the actual publisher delta

All entries below have20 measured matched process rounds. CPU is the median
total cost allocated to recovering10 seconds of market data, in milliseconds;
the indexed column includes the publisher's amortized index-maintenance delta.
The ratio is Scan/Indexed-BinHeap, with whole-round95% paired bootstrap CI.

| Cache treatment | Readers | Total delivered events across cohort | Scan CPU ms | Indexed CPU ms including maintenance | Scan/Indexed ratio [95% CI] |
|---|---:|---:|---:|---:|---:|
| repeat-warm |1|0|3.935|6.385|0.616 [0.582,0.654]|
| repeat-warm |10|1,020|40.800|6.472|6.304 [6.041,6.573]|
| repeat-warm |100|3,922|410.366|6.870|59.731 [57.528,62.317]|
| repeat-warm |1,000|40,145|4,109.102|11.130|369.198 [346.754,380.160]|
| scratch-thrashed |1|0|4.675|6.387|0.732 [0.694,0.786]|
| scratch-thrashed |10|1,020|47.651|6.556|7.269 [6.958,7.568]|
| scratch-thrashed |100|3,922|479.062|7.437|64.418 [61.965,66.821]|
| scratch-thrashed |1,000|40,145|4,798.137|17.143|279.883 [276.455,284.422]|

Maintenance outweighs the replay saving for the single seeded reader, whose
subscription happens to match no events in this10-second range. At larger
cohorts the many unrelated scan traversals dominate for this sparse assumed W2
mix. These gains describe these sequential cohorts and their overlap/match
patterns, not arbitrary production readers or concurrent scaling. All group
outputs match their per-reader independently checked results. Complete StdPQ,
Quad, Loser and Auto adjusted comparisons, per-arm uncertainty and raw paths are
in [t2-adjusted-paired.json](../../results/derived/t2-adjusted-paired.json).

### T3: held-out crossover and frozen Auto

The declared held-out grid has486 subscription/cache/generator comparison
cells. Each successful pairing has20 complete matched process rounds. The
following counts classify their95% intervals for Scan/requested-arm CPU ratios:

| Requested arm | Complete successful pairs | CI entirely above1 | CI entirely below1 | CI includes1 | Unavailable pairs |
|---|---:|---:|---:|---:|---:|
| Indexed/BinHeap |432|368|50|14|54|
| Auto/BinHeap |486|305|10|171|0|
| Indexed/Loser |432|380|42|10|54|
| Auto/Loser |486|321|2|163|0|

Direct indexed queries with k=100,000 exceed the approved packed cursor limit;
those54 cells per direct kernel remain invalid, while Auto falls back to Scan.
Auto has fewer cells whose intervals favour Scan for the two shown kernels,
but residual losses remain. Thus this frozen
finite-grid policy is useful in parts of this evaluation, not globally optimal.
The table is a descriptive count over an equally enumerated synthetic grid,
not production-weighted success probability or a multiple-testing-adjusted
significance claim. StdPQ/Quad and every cell's ratio/CI are retained in
[F12](../../results/figures/F12_scan_index_crossover.png) and the complete paired
table. [Prepared cases](../../results/raw/P6/prepared-evaluation/plan.json)
bind each synthetic workload to its independent expected output.

### T5: requested index storage, slack and allocator boundary

At the10:00 exclusive anchor,1 GiB ring and repeat-warm treatment, all block
sizes have21,979,412 live index postings. Requested/reserved bytes include the
whole fixed pool, including free slots; they are not current resident bytes.

| B | Requested/reserved index MiB | Reserved bytes/live posting | Expired allocated postings | Open slack slots | Free block slots | Observed allocator overhead B [95% CI] |
|---|---:|---:|---:|---:|---:|---:|
|64|160.786|7.671|264,022|264,214|12,187,072|123,047 [123,047,123,319]|
|256|153.380|7.317|1,009,366|1,105,942|14,020,864|116,455 [116,103,116,455]|
|1,024|200.489|9.565|2,856,406|5,250,326|21,712,896|124,855 [124,743,124,855]|
|4,096|408.032|19.466|5,923,286|24,976,662|53,653,504|139,975 [139,975,140,263]|

Structural counters/requested memory are deterministic in these repeated
snapshots, so their bootstrap intervals degenerate to the reported value.
Sealed-partial slack is zero in these snapshots. The slot-conservation recount
includes live, expired-allocated, open/sealed slack and free slots exactly.
The glibc allocator delta is measured in its separate index-only replay
boundary and is kept signed; it is neither process RSS nor a portable extension
of `Engine::memory()`.

The raw memory records also expose historical allocation high-water, which is
not recoverable merely from a final live-block recount:

| B | Allocated blocks at10:00 | Peak allocated blocks during publication |
|---|---:|---:|
|64|351,682|351,700|
|256|94,120|94,153|
|1,024|29,381|29,392|
|4,096|12,910|12,913|

Each peak was identical across all20 accepted process rounds. The source is
`kind=memory/allocated_high_water` in the accepted raw process files named by
evaluation state; the interrupted B=256 attempt is excluded. These block peaks
are distinct from the fixed pool's total reserved capacity.
The [reproducible high-water extraction](../../results/derived/t5-high-water.json)
retains min/median/max over all20 accepted rounds for each of the12 workloads,
plus raw/command/state/source identities. Its
[postprocessor](../../scripts/summarize_p6_t5_highwater.py) requires exact
repetition coverage, one memory record per process and current≤peak≤pool blocks.

For B=1024 at10:00 the210,227,945 requested/reserved bytes break down into:

| Component | Bytes |
|---|---:|
| Entry arrays |207,196,160|
| Block metadata |1,618,720|
| Sealed flags |50,585|
| Expiry-heap reserved storage |809,360|
| Partition state |285,056|
| Partition lists |267,728|
| Index control |336|

This is why four-byte postings are not four total allocated bytes per retained
record. B=256 has the smallest requested reserve among these tested block sizes
at this snapshot; B=4096's somewhat cheaper M3 scan comes with a substantially
larger pool/slack reserve. The result is conditional on the sizing policy,
partition count and workload, not a universal optimal B.

The three B=1024 snapshots also demonstrate time dependence:

| Exclusive anchor | Live postings | Expired allocated postings | Open slack slots | Requested/reserved bytes |
|---|---:|---:|---:|---:|
|09:35|6,135,737|0|6,609,991|210,111,945|
|09:45|16,895,972|0|6,010,908|210,153,113|
|10:00|21,979,412|2,856,406|5,250,326|210,227,945|

All12 block-size/snapshot workloads and both cache treatments are in
[F13](../../results/figures/F13_index_memory_slack.png) and the complete table.
Snapshots use a checkpoint at the captured head: the T5 work is memory/recount
measurement, not an expired `after_seq=0` recovery posing as a successful replay.

## Failure, interruption and noise accounting

The consolidated dataset contains135,751 rows:130,021 measured outcomes plus
5,730 saved recovery/memory warm-up rows. It contains6,759 configuration entries,
including the explicit failed-attempt entry. Pilot/training rows are excluded.

| Measured reporting status | Count |
|---|---:|
| `ok` |125,700|
| `invalid_config` |4,320|
| `crash` |1|
| `history_expired` |0|
| `fell_behind` |0|
| `oracle_mismatch` |0|

The4,320 rejected rows are216 direct-indexed configurations with k=100,000,
each repeated20 times. They exceed the packed cursor limit and remain explicit
outcomes; Auto/Scan alternatives are retained. Including warm-ups, the saved
raw evaluation audit counts534,240 `ok` and4,536 `invalid_config` request
outcomes. T2 normalization aggregates its per-reader records into cohorts, so
these raw-request counts differ from normalized configuration counts. The
summary's `validation_failed_count=1` identifies the retained crash row with no
validated output, not an unresolved discrepancy in a completed replay.

No comparison with failed/incomplete pairs receives a numeric speedup. Fast
error returns are never substituted for completed replay. The actual bounded
morning workloads did not produce history-expiry or FellBehind outcomes;
their semantics remain covered by the separate unit/differential/fuzz checks.

| Experiment | Measured rows | Non-ok | Frequency flagged | Frequency observed | Frequency unknown |
|---|---:|---:|---:|---:|---:|
| M1 |6,751|1|6,750|6,750|1|
| M1-touch |6,750|0|6,750|6,750|0|
| M2 |1,800|0|1,800|1,800|0|
| M3 |120|0|120|120|0|
| T1 |25,200|0|651|25,200|0|
| T2 |1,440|0|1,440|1,440|0|
| T3 |87,480|4,320|57,141|83,160|4,320|
| T5 |480|0|283|480|0|

All flagged observations remain in statistics. Micro repetitions cannot be
mapped exactly to adaptive Google Benchmark invocation endpoints; the declared
conservative rule flags every repetition in a block/attempt when any matching
endpoint deviates over10%. Consequently all accepted micro rows are flagged;
this does not mean every hot-loop repetition was observed at a deviating
frequency. T2 combines constituent-reader/publisher frequency endpoints. The
rejected T3 configurations and interrupted M1 row have unknown frequency
observations and are not silently labelled clean. All source sidecars and exact
join identities remain available in
[tip-outcomes.csv](../../results/derived/tip-outcomes.csv).

One M1-k256 attempt was externally terminated and its Google Benchmark JSON was
truncated; its replacement attempt passed. The user-requested overnight pause
interrupted one memory attempt, whose unconfirmed raw files remain preserved;
accepted completed rounds were resumed without repetition. The postprocessing
auditor also had documented path-canonicalization and T5 derived-work comparison
repairs. Failed audits and original source/provenance snapshots remain evidence;
these are distinguished from a production replay or memory-accounting failure.
See [the pause record](../../results/p6/pause-20261025.json) and
[first auditor compatibility review](../../results/p6/auditor-path-fix/independent-review.json).

The final evaluation audit passed **10,295,181 checks with zero failures**.
Its T5 repair independently constructs expected enriched work from the raw
allocator record, rather than ignoring differences: all original replay
counters must still match. The
[T5 compatibility record](../../results/p6/auditor-t5-compatibility/compatibility.json)
preserves original source/audit/provenance and verifies unchanged measurement
artifacts. Only postprocessing was corrected; no timed source or input was
relabeled. [Accepted saved-output audit](../../results/raw/P6/campaign-20261024/evaluation/independent-audit.json).

## Claims and raw evidence

Every numeric claim is conditional on the named stratum. Configuration IDs are
keys in `tip-summary.json`; that entry links all constituent raw files and
retains sample counts, intervals, outcome/noise accounting and exact config.

| ID | Supported statement | Exact selection / validation | Raw evidence |
|---|---|---|---|
| C01 | Merge-kernel performance ranking depends on input shape | `M1/k64/{zipf0,geometric256}/N4194304/{StdPQ,BinHeap,Quad-pad3,Loser}`,15 repeats each; independent sorted-union output/hash checks | [M1 raw block](../../results/raw/P6/M1/20261024T044043.895991Z_aa13c1824ba5-dirty_abc-HP-Laptop-15s-fq5xxx/M1-k64-attempt001/gbench.json) |
| C02 | Record-touch costs differ from key-only costs | `M1-touch/k64/zipf0/N4194304/Loser` and `M1-touch/k64/geometric256/N4194304/BinHeap`; initialized1GiB footprint and exact output/hash checked | [M1-touch raw block](../../results/raw/P6/M1/20261024T044043.895991Z_aa13c1824ba5-dirty_abc-HP-Laptop-15s-fq5xxx/M1-touch-k64-attempt001/gbench.json) |
| C03 | Index maintenance costs publisher CPU | `M2/payload_empirical/P{1,100,10000}/uniform/B256/index_{off,on}`,15 repeats each; independent sequence/count checks | [M2 actual sessions](../../results/raw/P6/M2/20261024T104904.812764Z_aa13c1824ba5-dirty_abc-HP-Laptop-15s-fq5xxx/session.json) |
| C04 | Block size affects seek and scan differently | `M3-{seek,scan}/B{64,256,1024,4096}`,15 repeats each; independent position vectors and lower-bound queries | [M3 raw output](../../results/raw/P6/M3/20261024T121915.466248Z_aa13c1824ba5-dirty_abc-HP-Laptop-15s-fq5xxx/M3-real-partition-sizes-attempt001/gbench.json) |
| C05 | Selective BOOK-top1 recovery avoids unrelated traffic | Scan `4cb05427907b9c338fdd`, Indexed-BinHeap `ab66e9b109c2a33524bf`, comparison `5179c7e3e8879aa3bdaf`;20 complete matched rounds | [Raw T observations](../../results/raw/P6/campaign-20261024/evaluation/runs.jsonl), [paired ratios](../../results/derived/tip-paired-ratios.csv) |
| C06 | Broad BOOK-top1000 indexed BinHeap loses to Scan here | Scan `f6bd6947519e9b1b1cf3`, Indexed `e12ced352f93a7d526fd`, Auto `f1314c568dcc75099368`, comparison `d321fa550ff05fbb5b04`;20 matched rounds | [Raw T observations](../../results/raw/P6/campaign-20261024/evaluation/runs.jsonl) |
| C07 | Full-stream requested Indexed uses Scan fallback | Scan `e208ce1e19195cb93579`, requested Indexed `1b83c59cdcc830207895`; raw `effective_mode=scan`, common engine contract/unit checks | [Raw T observations](../../results/raw/P6/campaign-20261024/evaluation/runs.jsonl), [engine contract](../../src/tiplog/engine/engine.cpp) |
| C08 | Maintenance changes T2's tradeoff, with sparse-cohort scope | Every `cache/R/indexed-binheap` row in the T2 table; actual window1800s/backlog10s,20 paired rounds; one-cohort formula checks and final independent review | [Per-reader outcomes](../../results/raw/P6/campaign-20261024/evaluation/reader-runs.jsonl), [adjusted paired analysis](../../results/derived/t2-adjusted-paired.json) |
| C09 | Frozen Auto is conditional, with residual losses | `exp=T3`, denominators `auto/binheap` and `auto/loser`,486 complete paired cells each; declared seed20191231 separate from training | [Prepared matrix](../../results/raw/P6/prepared-evaluation/plan.json), [raw T observations](../../results/raw/P6/campaign-20261024/evaluation/runs.jsonl), [paired ratios](../../results/derived/tip-paired-ratios.csv) |
| C10 | Total reserve is larger than four bytes/live posting |10:00 repeat-warm T5 IDs `3451e729afa1173bc301`, `7d0e93775cbbe5e8407b`, `7a9440b090ec31717404`, `df4ea90d10b64fdbcbd3`;20 rounds each; independent recount/allocator arithmetic | [Raw T observations](../../results/raw/P6/campaign-20261024/evaluation/runs.jsonl), [audit](../../results/raw/P6/campaign-20261024/evaluation/independent-audit.json) |
| C11 | Invalids, crash, warm-ups and noise are retained | Global status/noise tables above; all135751 consolidated rows and exact source concatenation | [Analysis inputs](../../results/p6/analysis-inputs.json), [complete outcomes](../../results/derived/tip-outcomes.csv), [consolidated raw rows](../../results/raw/P6/campaign-20261024/evaluation-observations.jsonl) |

## Implementation verification and reproducibility

The final timed engine source had passed166 release and166 ASan/UBSan unit
tests,142 Python tests,90,000,000 release plus18,000,000 sanitizer differential
operations,180 cross-compiler/repeat child checks with170 output equalities,
and1,802.644941 confirmed monotonic seconds of final F3 fuzzing
(39,231 executions). These are correctness evidence, not benchmark repetitions.
Postprocessing-only auditor, rendering and report additions do not modify the
timed engine or substitute short smoke checks for those accepted gates.

- [CC-2 final campaigns](../../results/p6/CC2-all-configurations.json).
- [Cross-compiler verification](../../results/p6/rc3-final-verified.json).
- [Confirmed final fuzz verification](../../results/p6/fuzz-prefix-final-verified.json).
- [Source/method and focused postprocessing checks](../../results/p6/p6-report-source-map.md).

Accepted derived artifacts are `results/derived/tip-summary.json`,
`tip-statistics.csv`, `tip-outcomes.csv`, `tip-paired-ratios.csv`,
`t2-adjusted-paired.json` and `t5-high-water.json`. Raw inputs, configurations, exact command/exit logs,
environment observations and source/binary/input identities remain local under
the linked campaign. No message-level Nasdaq data is intended for Git packaging.

The required regeneration command is:

```sh
PYTHONPATH=py .venv/bin/python -m tiplog_py.figures.build --all
PYTHONPATH=py .venv/bin/python scripts/summarize_p6_t2_adjusted.py results/raw/P6/campaign-20261024/evaluation/runs.jsonl
PYTHONPATH=py .venv/bin/python scripts/summarize_p6_t5_highwater.py results/raw/P6/campaign-20261024/evaluation
```

The first command regenerates P1 F01–F05 and actual P6 F06–F13 from saved
results with one command; the other two regenerate the report's supplementary
T2 adjusted-cost and T5 peak-allocation tables. The final
[regeneration command](../../results/p6/figures-final-title-regeneration-20261025T075429.868488Z.json)
passed, as did [143 final Python tests](../../results/p6/python-final-title-check-20261025T075429.867981Z.json).
[Regeneration/identity verification](../../results/p6/figure-regeneration-verification.json)
checks every figure artifact and confirms the complete summary, statistics CSV,
paired-ratio CSV and analysis-input manifest are byte-identical to their first
accepted versions. Actual final F09/F12/F13 PNGs were visually inspected.

Presentation corrections separate all eight F12 arms within each categorical
cell, explicitly show unavailable ratios, factor the F09/F10/F11 legends and
wrap titles/footers. A fixed physical top inset keeps the tall F12 title out of
the data panels. These changes alter no measured value or confidence interval;
[original figure source/outputs](../../results/p6/f12-layout-compatibility/before.json)
and [the final title-only amendment](../../results/p6/f12-title-position-compatibility/compatibility.json)
are retained. [266 current core/tool/child integrity checks](../../results/p6/final-core-integrity.json)
confirm that accepted engine correctness campaigns remain applicable.

## Limits of the conclusions

- One laptop, one historical source and one morning window; constructed
  synthetic traffic and assumed subscriber mixes are sensitivity studies.
- CPU2 affinity and observed quiet project processes do not isolate shared
  memory bandwidth, cache, package power or background host activity.
- Auto was trained on a finite grid and a different seed, not validated against
  every possible production workload; invalid packed-limit configurations remain
  part of coverage.
- The publisher is paused during measured recovery, and reader cohorts are
  sequential. Results are not concurrent-reader scaling or overloaded-service
  latency. No p99/p99.9 is reported; Tier C T4 is deferred.
- Logical inspected bytes and requested/reserved index storage are not physical
  I/O or process RSS. The glibc allocator contribution has a separate measured
  process boundary. M3's full-window index fixture is not T5's retained-ring
  snapshot.
- No durability, crash recovery, networking, book-validity or profit claim is
  established. P7 storage costs and P8 packaging are not completed by P6.

## Evidence and completion boundary

P6 completion requires the amended saved-output audit, all required actual
figures, reproducible regeneration and raw-linked claims to pass. This report
does not itself substitute for the gate. The final
`results/p6/phase-gate.json`, [closeout evidence manifest](../../results/p6/closeout-evidence.json)
and PROGRESS entry are authoritative. No P6 correctness requirement is deferred
to P7/P8; those phases remain unstarted at this boundary.
The implementation/research-to-evidence chain is summarized in
[the report source map](../../results/p6/p6-report-source-map.md).
