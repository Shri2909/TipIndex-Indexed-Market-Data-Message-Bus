# P7 storage-layout results — tiplog v1.1 / Tier B

Cost, exact-coverage, global-budget and controlled-runtime observations are
complete and audited. The full analysis reports **214,668 cases, 1,073,340
method rows and no audit failures**; the controlled DP runtime campaign passed
all 11 process rounds and the predeclared host-quiescence rule. This document
reports results; P7 acceptance is recorded separately in
[the P7 gate](../../results/p7/phase-gate.json). All byte and cost numbers below
describe the approved full-window M-store model: they are **modeled**, not
measured physical disk I/O.

## Inputs, model and comparison population

The P1 source contains **268,744,780 observed messages** and **8,251,407,909
decompressed bytes**. It lacks the BinaryFILE session terminator and remains
`incomplete=true`. P7 uses the complete *observed source* volume tables, with
**13,201,746,784 modeled record bytes** in **8,907 partitions**, including
`itch/_market`. A record contributes `align8(16 + ITCH payload)` bytes; ring PAD
is excluded. These are modeled storage bytes, not measured store-pack I/O.
P6 used the separate 09:30–10:00 trace window; its 32,817,244 records are not
P7's volume population. [Source identity](../../data/manifest.json),
[input manifest](../../results/p7/input-manifest.json),
[P1 characterization](../../results/data/itch_20191230_full_day_summary.json).

There are 213,768 real cases: two hierarchies × four workloads × three beta
values × 8,907 partitions. The other 900 cases are fixed Zipf synthetic trees
of 5–1,000 nodes, three shapes, one/four effective classes, five input seeds
and capped budgets from {1,4,16,64}. W0 reads each positive topic exactly;
W1 combines BOOK/TAPE/AUCT/STAT; W2 changes those weights by activity rank;
W3 adds replay baskets to W1 at weight 1/10. Zero-weight/inactive classes are
removed and identical positive-topic incidence is merged with exact summed
rational weights. The input manifest records the source/generator hashes,
class memberships and population. Whole-window requests remain the scope.

For real cases, alpha=1, gamma=0 and beta is 0, 65,536 or 1,048,576. Beta is a
per-store-read sensitivity cost equivalent to that many byte-cost units;
it is not a measured disk-open cost. J is weighted read bytes plus beta times
weighted stores touched. Each method receives the same **at-most materialized
store budget** as H-BASE for that partition. Actual store counts may differ.
H-spec's full baseline totals 44,504 stores; H-flat's totals 111,997.

Every exact comparison below uses `exact_cohort_quality`: the identical cases
solved by at least one exact method, on which all requested heuristics are
feasible. `best-exact` selects solved DP, then solved ENUM. Counts and objective
values are exact; W3's fractions retain the rational weight scale. Partial
solver populations are never compared with whole-population totals as if they
had the same denominator. [Audited summary](../../results/derived/layout-summary.json),
[case metrics CSV](../../results/raw/P7/layout-claim-metrics.csv),
[raw input/output mapping](../../results/p7/analysis-inputs.json),
[compact report facts](../../results/p7/report-facts.json).

## L2: modeled cost at matched per-partition budgets

The table sums J over each explicitly counted common cohort. The exact column
is optimal for these per-partition budgets, not a general global allocation.
For H-spec W0 the cohort is only 3,873 of 8,907 partitions; for H-flat W0 it is
8,906. W1–W3 include all 8,907. H-flat uses its own, larger baseline budget;
these cross-hierarchy rows are sensitivity observations, not optimality gaps
between different trees or budgets.

| Hierarchy | Workload | beta | Cases | H-BASE J | KM-min J | KM-max J | Exact J | Exact stores |
|---|---|---|---|---|---|---|---|---|
| H-spec | W0 | 0 | 3,873 | 1,951,897,840 | 1,019,492,408 | 1,020,693,952 | 994,767,992 | 19,334 |
| H-spec | W0 | 65,536 | 3,873 | 4,776,106,224 | 3,843,700,792 | 3,844,902,336 | 3,818,976,376 | 19,334 |
| H-spec | W0 | 1,048,576 | 3,873 | 47,139,231,984 | 46,206,826,552 | 46,208,028,096 | 46,182,102,136 | 19,334 |
| H-spec | W1 | 0 | 8,907 | 19,367,265,136 | 14,312,697,608 | 14,312,486,728 | 13,964,962,856 | 43,302 |
| H-spec | W1 | 65,536 | 8,907 | 25,104,089,968 | 20,364,226,312 | 20,463,433,544 | 18,797,797,288 | 35,435 |
| H-spec | W1 | 1,048,576 | 8,907 | 111,156,462,448 | 111,137,156,872 | 112,727,635,784 | 72,959,763,536 | 15,583 |
| H-spec | W2 | 0 | 8,907 | 53,063,664,304 | 37,453,911,320 | 37,583,405,920 | 37,046,713,312 | 20,812 |
| H-spec | W2 | 65,536 | 8,907 | 54,649,766,576 | 39,195,006,232 | 39,350,518,624 | 38,641,731,200 | 20,805 |
| H-spec | W2 | 1,048,576 | 8,907 | 78,441,300,656 | 65,311,429,912 | 65,857,209,184 | 59,925,497,376 | 19,492 |
| H-spec | W3 | 0 | 8,907 | 25368009808/5 | 22840726044/5 | 22840620604/5 | 22666858668/5 | 43,302 |
| H-spec | W3 | 65,536 | 8,907 | 28564102224/5 | 26194170396/5 | 26243774012/5 | 25318390688/5 | 35,192 |
| H-spec | W3 | 1,048,576 | 8,907 | 76505488464/5 | 76495835676/5 | 77291075132/5 | 54601596952/5 | 15,407 |
| H-flat | W0 | 0 | 8,906 | 13,199,778,816 | 13,199,778,816 | 13,199,778,816 | 13,199,778,816 | 111,981 |
| H-flat | W0 | 65,536 | 8,906 | 20,538,565,632 | 20,538,565,632 | 20,538,565,632 | 20,538,565,632 | 111,981 |
| H-flat | W0 | 1,048,576 | 8,906 | 130,620,367,872 | 130,620,367,872 | 130,620,367,872 | 130,620,367,872 | 111,981 |
| H-flat | W1 | 0 | 8,907 | 13,496,864,344 | 13,496,864,344 | 13,496,864,344 | 13,496,864,344 | 80,624 |
| H-flat | W1 | 65,536 | 8,907 | 25,672,273,496 | 25,672,273,496 | 25,672,273,496 | 18,942,349,696 | 38,414 |
| H-flat | W1 | 1,048,576 | 8,907 | 208,303,410,776 | 208,303,410,776 | 208,303,410,776 | 73,094,409,600 | 15,504 |
| H-flat | W2 | 0 | 8,907 | 36,705,017,872 | 36,705,017,872 | 36,705,017,872 | 36,705,017,872 | 49,461 |
| H-flat | W2 | 65,536 | 8,907 | 41,276,809,232 | 41,276,809,232 | 41,276,809,232 | 38,570,257,784 | 81,086 |
| H-flat | W2 | 1,048,576 | 8,907 | 109,853,679,632 | 109,853,679,632 | 109,853,679,632 | 60,025,989,584 | 78,036 |
| H-flat | W3 | 0 | 8,907 | 22432809412/5 | 22432809412/5 | 22432809412/5 | 22432809412/5 | 80,624 |
| H-flat | W3 | 65,536 | 8,907 | 29393453508/5 | 29393453508/5 | 29393453508/5 | 25413040524/5 | 37,873 |
| H-flat | W3 | 1,048,576 | 8,907 | 133803114948/5 | 133803114948/5 | 133803114948/5 | 54677875904/5 | 15,325 |

H-spec W1 at beta=0 falls from J=19,367,265,136 to 13,964,962,856 with exact
optimization over all partitions. The threshold endpoints are not universally
ordered by J: KM-max has lower whole-population W0 read cost than KM-min,
whereas KM-min has lower W2 cost. At W1 beta=1,048,576, KM-max costs
112,727,635,784, above the baseline's 111,156,462,448; the exact cost is
72,959,763,536. Threshold feasibility/minimum-count behavior does not make
these heuristics exact for J.

For W0/H-spec, the following **whole-population** heuristic results are valid
even where neither exact solver finishes. They are not full-population exact
gaps. The common-cohort W0 exact result above must not be extrapolated to
these totals.

| Method | Partitions | Weighted read bytes | Weighted waste bytes | Stores |
|---|---|---|---|---|
| base | 8,907 | 43,409,459,048 | 30,207,712,264 | 44,504 |
| km-min | 8,907 | 15,671,123,776 | 2,469,376,992 | 44,495 |
| km-max | 8,907 | 15,657,312,880 | 2,455,566,096 | 44,495 |

## Exact coverage and capped outcomes

For each workload/hierarchy/method, all three beta values independently have
exactly the same coverage and cap counts, so one row represents each of
**beta={0,65,536,1,048,576}**. Every row's partition denominator is 8,907;
fractions below are exact and reduced. Byte denominators use the same modeled
record bytes as J. Weight denominators sum active **per-partition** class
weights; a multi-partition basket participates repeatedly and is not counted
as one distinct global request. A fraction of 1 means complete coverage.

| Hierarchy | Workload | Method | Solved partitions | Byte fraction | Active-weight fraction | Non-solved per beta |
|---|---|---|---|---|---|---|
| H-spec | W0 | enum | 3,873/8,907 | 109584929/1650218348 | 43094/111997 | state_limit=5,034 |
| H-spec | W0 | dp | 2,034/8,907 | 46995097/1650218348 | 21026/111997 | state_limit=6,873 |
| H-spec | W1 | enum | 2,034/8,907 | 46995097/1650218348 | 8519/22265 | state_limit=6,873 |
| H-spec | W1 | dp | 8,907/8,907 | 1 | 1 | 0 |
| H-spec | W2 | enum | 3,859/8,907 | 97220069/1650218348 | 5767/15606 | state_limit=5,048 |
| H-spec | W2 | dp | 8,907/8,907 | 1 | 1 | 0 |
| H-spec | W3 | enum | 2,034/8,907 | 46995097/1650218348 | 2873/7755 | state_limit=6,873 |
| H-spec | W3 | dp | 8,907/8,907 | 1 | 1 | 0 |
| H-flat | W0 | enum | 8,906/8,907 | 412493088/412554587 | 111981/111997 | state_limit=1 |
| H-flat | W0 | dp | 3,873/8,907 | 109584929/1650218348 | 43094/111997 | state_limit=5,034 |
| H-flat | W1 | enum | 8,906/8,907 | 412493088/412554587 | 22263/22265 | state_limit=1 |
| H-flat | W1 | dp | 8,907/8,907 | 1 | 1 | 0 |
| H-flat | W2 | enum | 8,907/8,907 | 1 | 1 | 0 |
| H-flat | W2 | dp | 8,907/8,907 | 1 | 1 | 0 |
| H-flat | W3 | enum | 8,906/8,907 | 412493088/412554587 | 23263/23265 | state_limit=1 |
| H-flat | W3 | dp | 8,907/8,907 | 1 | 1 | 0 |

No real-case timeout, representation failure, missing row or error was reported.
The `state_limit` status covers either the stored-state guard or deterministic
work guard; it is not a claim that every capped process exhausted memory.
The declared guards were ENUM edges≤22, DP classes≤16, 2,000,000 states,
2,000,000 work units and 500 ms per exact invocation. They were frozen before
studies. A capped incumbent is not OPT and supplies no exact gap or global
lower bound. All non-solved rows remain in the case CSV and coverage table.

For example, H-spec W0 DP solves only 2,034 partitions; ENUM solves 3,873.
H-flat W0 DP solves 3,873 while ENUM solves 8,906. The global complete-curve
union is consequently 3,873 for H-spec and 8,906 for H-flat, rather than an
assertion that DP covers either entire W0 population.

## L3: exact gaps and synthetic coverage

The gap is `(J_heuristic - J_exact)/J_exact` on the identical case and budget.
The following beta=0 H-spec distributions give **each partition one
observation**, whereas the L2 sums weight bytes by workload frequency.
Synthetic rows use their declared beta=65,536 and the same definition.
Fractions are ratios, not percentages; medians use the documented nearest-rank
rule. No unsolved case receives an exact gap.

| Population | Heuristic | Compared cases | Median relative gap | Maximum relative gap |
|---|---|---|---|---|
| real/W0 | km-max | 3,873 | 141/6082 | 5255/9761 |
| real/W0 | km-min | 3,873 | 61/2960 | 1635/3041 |
| real/W1 | km-max | 8,907 | 1176/16637 | 4784/7019 |
| real/W1 | km-min | 8,907 | 188/2715 | 764/1191 |
| real/W2 | km-max | 8,907 | 217/45 | 27399/139 |
| real/W2 | km-min | 8,907 | 333/64 | 27399/139 |
| real/W3 | km-max | 8,907 | 179/2578 | 4784/7019 |
| real/W3 | km-min | 8,907 | 4778/70523 | 764/1191 |
| synthetic/b1 | km-max | 450 | 12288/154236181 | 4128768/3603098633 |
| synthetic/b1 | km-min | 450 | 12288/154236181 | 4128768/3603098633 |
| synthetic/b4 | km-max | 435 | 983040/35466449797 | 2181276835/2885664666 |
| synthetic/b4 | km-min | 435 | 327680/13866326023 | 2181276835/2885664666 |

W2 illustrates why a favorable aggregate cost cannot stand in for every
partition: KM-min's aggregate J is 37,453,911,320 versus exact
37,046,713,312, yet its median partition gap is 333/64 and its maximum is
27,399/139. Many low-activity partitions have only STAT weight, while the
threshold rule uses volumes rather than workload price. The measured
aggregate and per-case distribution answer different questions.

All 900 synthetic cases were attempted. The table counts full requested
count-domain solves under the original guards; costs remain exact where
solved. The 15 DP caps occur at n=1,000 with four classes and K=64. ENUM
solves the 180 n≤10 cases; the 10,000-instance CC-5 validation is a separate,
more generous correctness campaign, not evidence that these resource-limited
studies solved every tree.

| Nodes | Cases | ENUM solved | DP solved | Other outcomes |
|---|---|---|---|---|
| 5 | 90 | 90 | 90 | ;  |
| 10 | 90 | 90 | 90 | ;  |
| 20 | 120 | 0 | 120 | ENUM state_limit=120;  |
| 50 | 120 | 0 | 120 | ENUM representation_limit=120;  |
| 100 | 120 | 0 | 120 | ENUM representation_limit=120;  |
| 250 | 120 | 0 | 120 | ENUM representation_limit=120;  |
| 500 | 120 | 0 | 120 | ENUM representation_limit=120;  |
| 1,000 | 120 | 0 | 105 | ENUM representation_limit=120; DP state_limit=15 |

## Consumer costs, amplification and beta trade-offs

For W1/H-spec all rows below cover the same 8,907 partitions. Each role's
weighted useful-byte totals are unchanged by layout: AUCT=290,749,496,
BOOK=12,835,215,200, STAT=11,619,400 and TAPE=359,280,248. Amplification here
is the ratio of weighted read to weighted useful bytes for that role; the
worst individual-class ratios are reported separately below.

| beta | Method | Role | Weighted read bytes | Weighted waste bytes | Weighted stores touched | Role amplification |
|---|---|---|---|---|---|---|
| 0 | base | AUCT | 368,740,024 | 77,990,528 | 17,812 | 46092503/36343687 |
| 0 | base | BOOK | 12,835,215,200 | 0 | 44,502 | 1 |
| 0 | base | STAT | 11,619,400 | 0 | 8,906 | 1 |
| 0 | base | TAPE | 6,151,690,512 | 5,792,410,264 | 16,317 | 768961314/44910031 |
| 0 | best-exact | AUCT | 398,737,088 | 107,987,592 | 15,946 | 49842136/36343687 |
| 0 | best-exact | BOOK | 12,948,776,744 | 113,561,544 | 39,696 | 1618597093/1604401900 |
| 0 | best-exact | STAT | 148,657,848 | 137,038,448 | 8,906 | 18582231/1452425 |
| 0 | best-exact | TAPE | 468,791,176 | 109,510,928 | 16,654 | 58598897/44910031 |
| 0 | km-min | AUCT | 500,869,576 | 210,120,080 | 15,509 | 62608697/36343687 |
| 0 | km-min | BOOK | 12,987,031,976 | 151,816,776 | 55,673 | 1623378997/1604401900 |
| 0 | km-min | STAT | 285,023,200 | 273,403,800 | 8,940 | 1425116/58097 |
| 0 | km-min | TAPE | 539,772,856 | 180,492,608 | 12,217 | 67471607/44910031 |
| 1,048,576 | best-exact | AUCT | 2,041,360,392 | 1,750,610,896 | 9,037 | 255170049/36343687 |
| 1,048,576 | best-exact | BOOK | 13,195,653,872 | 360,438,672 | 24,207 | 824728367/802200950 |
| 1,048,576 | best-exact | STAT | 2,110,890,728 | 2,099,271,328 | 8,906 | 263861341/1452425 |
| 1,048,576 | best-exact | TAPE | 2,058,985,072 | 1,699,704,824 | 8,922 | 257373134/44910031 |

At beta=0 KM-min reduces TAPE reads but raises BOOK touches from 44,502 to
55,673 and introduces BOOK waste. The exact layout also accepts BOOK, AUCT
and STAT waste while sharply reducing TAPE waste; it minimizes the combined
workload, not each consumer separately.

Increasing beta changes that trade-off. Exact W1 weighted store touches fall
from 81,202 at beta=0 to 51,072 at beta=1,048,576, while weighted read bytes
rise from 13,964,962,856 to 19,406,890,064 and waste rises from 468,098,512 to
5,910,025,720. The larger J values across beta are different objectives, not
optimality gaps or a measured slowdown.

The maximum waste and worst amplification below are individual-class maxima
on that same W1 population. The 4 KiB version considers only classes with
**useful bytes U≥4,096**; it does not replace U with `max(U,4096)`. `null`
means no eligible class for that role, not zero amplification. Useful-zero
classes are excluded from ratios.

| beta | Method | Role | Max class waste B | Worst R/U | Worst R/U with U≥4,096 |
|---|---|---|---|---|---|
| 0 | base | AUCT | 1,108,608 | 8915/254 | 8915/254 |
| 0 | base | BOOK | 0 | 1 | 1 |
| 0 | base | STAT | 0 | 1 | null |
| 0 | base | TAPE | 51,349,544 | 1047545/38 | 4865651/582 |
| 0 | best-exact | AUCT | 854,256 | 55423/2032 | 55423/2032 |
| 0 | best-exact | BOOK | 885,184 | 306939/282448 | 306939/282448 |
| 0 | best-exact | STAT | 885,184 | 55423/99 | null |
| 0 | best-exact | TAPE | 3,313,528 | 7380/227 | 11420/613 |
| 1,048,576 | best-exact | AUCT | 1,830,288 | 116425/2032 | 116425/2032 |
| 1,048,576 | best-exact | BOOK | 885,184 | 2065/24 | 2295/263 |
| 1,048,576 | best-exact | STAT | 1,860,448 | 58801/48 | null |
| 1,048,576 | best-exact | TAPE | 1,736,360 | 46453/10 | 13299/94 |

## L4: article-label worked example

The two trees L and R are separate partitions with a **joint total budget of
four**. This differs from L2's fixed per-partition baseline budgets. The
example preserves the article's decimal byte labels; those labels are not
replaced with ITCH record framing.

| Layout | Waste bytes | Read bytes | (L stores,R stores) |
|---|---|---|---|
| base | 5,517,460,497 | 8,276,568,994 | (2, 2) |
| figure | 39,881,491 | 2,798,989,988 | (3, 1) |
| km-min | 30,029,491 | 2,789,137,988 | (3, 1) |
| km-max | 39,881,491 | 2,798,989,988 | (3, 1) |
| enum | 30,029,491 | 2,789,137,988 | (3, 1) |
| dp | 30,029,491 | 2,789,137,988 | (3, 1) |

The finite four-store threshold plateau has integer endpoints
T_min=28,648,000 and T_max=38,647,999. The optimum uses counts (3,1);
fixing counts to baseline (2,2) would exclude it. The example's three required
waste totals are reproduced by executable evaluation and regression checks.
[Raw computed example](../../results/p7/worked-example.json),
[validation/source map](../../results/p7/p7-source-map.md).

## L5: hierarchy sensitivity

H-flat puts each exact W0 topic in its own baseline store. Its full-population
baseline waste is **exactly zero for every tested beta**, verified on 26,721
partition observations. There is no positive W0 waste-reduction claim for
that hierarchy.

| beta | Partitions | Baseline stores | Baseline J | Weighted waste B |
|---|---|---|---|---|
| 0 | 8,907 | 111,997 | 13,201,746,784 | 0 |
| 65,536 | 8,907 | 111,997 | 20,541,582,176 | 0 |
| 1,048,576 | 8,907 | 111,997 | 130,639,113,056 | 0 |

For H-flat W1–W3 at beta=0, the exact cost equals H-BASE on the common full
population. With positive beta, merging may reduce fixed read charges and
lower J despite raising filtering waste. H-spec and H-flat have different
connected trees and baseline budgets; the cost table presents their separate
results without treating the difference as an exact optimality gap.

## Global nonnegative-penalty sweep and requested budgets

The independent Fraction audit passed **3,652,966 checks** over **24 strata**.
Each stratum includes all 8,907 partitions. All W1/W2/W3 strata in both
hierarchies and all three beta values have complete exact curves: **18 strata**.
All six W0 strata are incomplete and supply **no global lower bound**, including
H-flat's 8,906/8,907 near-complete case.

The seven additional penalties are lambda={0,1,65,536,1,048,576,16,777,216,
268,435,456,4,294,967,296}. They produce **126 certified supported points**
and **42 uncertified feasible penalty candidates**. A certified point minimizes
`sum(c_p(k)+lambda*k)` and is optimal for its own at-most total count because
lambda≥0. This finite sweep does not enumerate every budget or the full hull;
there is no general global knapsack solver.

Across 205 requested stratum/budget pairs, 139 have matching feasible upper
and certified lower bounds, 12 retain a nonzero upper/lower gap, 45 have a
feasible candidate without a global bound, and nine have no evaluated feasible
point. A requested count absent from this finite sweep is not automatically
proved mathematically unsupported at every possible lambda. For budgets not
attained by the evaluated points, the reported lower bound is
`sum_p min_k(c_p(k)+lambda*k) - lambda*B`, only when every partition term is
certified.

For H-spec W1, beta=0, lambda=0 selects 54,053 stores at J=13,496,864,344;
lambda=65,536 selects 37,088 at J=13,804,628,800; lambda=268,435,456 selects
8,907 at J=52,809,194,832. Each is certified for its own at-most count. At
baseline forest budget B=44,504, the best evaluated upper bound is
13,804,628,800 and lower bound is 13,496,873,893: the exact remaining gap is
307,754,907, so that requested-budget result is not declared exact. H-spec
W3 at the same beta/budget has bounds 24,430,777,968/5 and 22,432,857,157/5.
[Audited global summary](../../results/derived/layout-global.json),
[global raw rows and curves](../../results/raw/P7/global/),
[certificate implementation](../../src/tiplog/layout/global.cpp).

## Validation, provenance and failed-attempt accounting

The release and ASan/UBSan layout suites each passed 20 tests. Each separate
CC-5 campaign completed 10,000 random instances with zero mismatches,
57,461 exact-count and 57,461 at-most comparisons, 96,322 reconstructed
layouts and 20,000 unrelated random layouts. Both builds retain identical
input/result hashes. Threshold checks independently exhaust small connected
partitions; evaluator checks include baskets, internal messages, zero nodes,
above-root terms, rational scaling, overflow and cap boundaries.
[CC-5 release](../../results/p7/cc5-release.json),
[CC-5 sanitizer](../../results/p7/cc5-asan-ubsan.json),
[independent design review](../../results/p7/independent-design-review.md).

The first full analyzer attempt failed only while serializing an optional
arithmetic mean of relative-gap fractions: their accumulated denominator LCM
exceeded Python's decimal-conversion digit limit. The saved per-case costs,
individual exact gaps and coverage were unchanged. That optional statistic
was removed; the successful rerun retains exact count/median/quartile/min/max
distributions. The failed CSV/log remain preserved, and the compatibility
check confirms failed and successful case CSVs are byte-identical, SHA-256
`2d222dfa8361f052d13d63a9956bb1cdc7d7750de49763cd6d1bfd2ebc4678b0`.
This is preserved postprocessing failure accounting, not an unresolved
optimizer mismatch. [Compatibility check](../../results/p7/analysis-mean-compatibility.json),
[accepted analyzer execution](../../results/p7/analyze-full-matrix-no-ratio-mean-20261025T142754.019962Z.json).

The algorithms are independent project implementations of the approved
connected residual-store model. They do not reproduce private Aria code or
an unspecified article greedy algorithm. S33's full original remains unread;
S34's inspected original material is its abstract and section 1.1/PDF pages
1–3 through Table 1; S35/S36 retain the recorded limited readings. No broader
paper-reading, borrowed exactness theorem for M-store or general hardness
claim is made. [Recorded study/reading limits](../../results/p6/p7-study.md),
[implementation/source ledger](../../results/p7/p7-source-map.md).

## L3: controlled MASK-DP runtime scaling

Original full-matrix solver wall times remain **diagnostic**, not controlled
L3 scaling measurements. They include solver-internal reconstruction and
formula checks, exclude preparation and independent CLI materialization, and
were collected on a nonexclusive laptop. Work/state counts are algorithmic
proxies, not allocated bytes or physical I/O; process RSS is recorded
separately in campaign resource logs.

The controlled supplement times MASK-DP alone on all 900 original synthetic
inputs, budgets and caps. It ran 2026-10-25 15:34–15:46 UTC: one saved warm-up
plus **ten measured rounds, each a fresh process** solving all 900 cases in a
globally shuffled order after a 60-second settling block. The solver was pinned
to CPU 2 with per-process ASLR disabled (no privileged setting changed); the
observer ran on CPU 6. Every row records the child's actual CPU, AC state and
CPU-2 frequency before and after the solve, and every solved cost, layout and
reconstruction was compared with the original cost campaign. Timing is the
solver's internal `steady_clock` interval, including reconstruction and its
internal formula checks. [Protocol](../../results/p7/runtime-supplement.json),
[method and controls](../../results/p7/runtime-method.md),
[campaign](../../results/p7/runtime-campaign.json),
[timing interpretation](../../results/p7/timing-clarification.md).

**Host quiescence.** A rule declared before this campaign
([rule](../../results/p7/runtime-quiescence-rule.json)) rejects the whole
campaign if any round, warm-up included, has CPU 2 below 90% idle during
settling, more than 3.0 s of CPU time from processes outside the campaign
sampled on CPU 2/3, or a CPU-3 idle ratio below 0.90. All 11 rounds passed:
CPU-2 settling idle 0.956–0.980, foreign CPU 2/3 time 0.32–1.77 s per round,
and CPU-3 idle 0.987–1.000. [Quiescence result](../../results/p7/runtime-quiescence.json).
Two earlier attempts were discarded and their readings deleted at the user's
instruction. In the first, CPU-bound processes from another project shared
solver CPU 2 in 9 of 10 measured rounds. The second was rejected by the rule
above because its warm-up had 3.52 s of foreign CPU 2/3 time, from the editor
and the agent session. Neither attempt contributes to any number here.

**Outcomes.** The 9,000 measured attempts produced 8,850 solves and 150
`state_limit` outcomes, identical in every round: the 15 four-class n=1,000,
K=64 inputs (all three shapes) exceed the frozen 2,000,000 state/work guard,
as in the original campaign. Thus 885/900 inputs were solved in all ten
rounds and no input was solved in only some rounds. Capped inputs receive no
runtime, and no cap was relaxed.

**Scaling.** Each cell is the median, across the available fixed inputs (three
shapes × five tree seeds), of each input's ten-process median, in
microseconds. `b` is the effective class count and `K` the requested store
budget, capped at n. Every cell outside the last column covers 15/15 inputs;
the coverage column counts inputs solved in all ten rounds for b=4, K=64.

| Nodes | b=1, K=4 | b=4, K=4 | b=4, K=16 (K=n if n<16) | b=4, K=64 (K=n if n<64) | b=4, K=64 coverage |
|---|---:|---:|---:|---:|---|
| 5 | 6.88 | 12.2 | 12.9 | 12.9 | 15/15 |
| 10 | 9.00 | 21.1 | 31.5 | 31.5 | 15/15 |
| 20 | 15.0 | 38.7 | 77.0 | 85.0 | 15/15 |
| 50 | 29.5 | 88.5 | 193 | 402 | 15/15 |
| 100 | 54.7 | 167 | 381 | 1,170 | 15/15 |
| 250 | 118 | 403 | 927 | 3,350 | 15/15 |
| 500 | 203 | 787 | 1,850 | 9,650 | 15/15 |
| 1,000 | 390 | 1,630 | 3,990 | capped | 0/15 |

For fixed b and K, time grows roughly in proportion to node count: b=4, K=4
rises 9.8× from 100 to 1,000 nodes. Larger budgets and more classes cost more,
and the slowest solved input (n=500, b=4, K=64, chain) has median 12.59 ms
(95% CI 12.36–12.77 ms). These are observations on the declared synthetic Zipf
trees, not a fitted complexity law or a guarantee for other inputs.

**Uncertainty and noise.** Each solved input has a median, IQR, min/max and a
95% percentile-bootstrap CI of the median from 10,000 seeded resamples over its
ten processes. The CI width is a median 5.2% of the input's median (90th
percentile 12.6%, maximum 52.4%). The measured session's median boundary
frequency was 3,796,017 kHz. 1,626 of 9,000 measured rows had a boundary sample
more than 10% from it; they are flagged and retained, not filtered. CPU
frequency was not fixed (no privileged settings), and the laptop was not
exclusive, so the CIs describe repeat variation on this host, not a
host-independent runtime. [Per-input summary](../../results/derived/layout-runtime.json),
[frequency flags](../../results/raw/P7/runtime/frequency-flags.json).

## Figures F14–F18

All figures regenerate from saved analysis inputs with the one-command builder
(`python -m tiplog_py.figures.build --all`), which also rebuilds F01–F13. The
P1/P6 figures were checked unchanged except for PDF creation timestamps.
[P7 figure manifest](../../results/figures/p7-figures.json),
[compatibility check](../../results/p7/figure-extension-compatibility.json).

| Figure | Content |
|---|---|
| [F14](../../results/figures/F14_layout_class_amplification.png) | Per-role weighted read amplification for base, KM-min, KM-max and best-exact on identical solved partitions, all workloads and beta values |
| [F15](../../results/figures/F15_layout_tradeoff.png) | Stores versus modeled read bytes: certified (W1–W3) and uncertified (W0) nonnegative-penalty sweeps, heuristic points, worked-example curve |
| [F16](../../results/figures/F16_layout_gaps_scaling.png) | Exact relative-gap distributions per beta, controlled DP runtime scaling (b=4, K=4) and H-spec exact coverage |
| [F17](../../results/figures/F17_layout_worked_example.png) | Computed article-example layouts: base, KM-max and DP with their waste |
| [F18](../../results/figures/F18_layout_hierarchy.png) | H-spec versus H-flat waste against store count; H-flat baseline waste is zero |

## Claims and artifact map

| ID | Scoped result | Evidence |
|---|---|---|
| L01 | The modeled volume population and all 1,073,340 method rows are accounted for; exact claims exclude capped results. | [Summary](../../results/derived/layout-summary.json), [inputs/raw mapping](../../results/p7/analysis-inputs.json), [case CSV](../../results/raw/P7/layout-claim-metrics.csv) |
| L02 | Matched-budget modeled costs and consumer trade-offs use identical feasible exact cohorts; neither KM endpoint is universally best. | `exact_cohort_quality` / `exact_cohort_consumer_quality` in [summary](../../results/derived/layout-summary.json), [report facts](../../results/p7/report-facts.json), [case CSV](../../results/raw/P7/layout-claim-metrics.csv) |
| L03 | Per-method exact coverage and gap distributions retain state/work/representation caps; DP solves 885/900 original synthetic cases. | `exact_coverage`, `comparisons`, `scaling` in [summary](../../results/derived/layout-summary.json), [raw campaign](../../results/raw/P7/studies/campaign.json) |
| L04 | The separate-partition worked example reproduces all three required waste values and finite threshold endpoints. | [Computed example](../../results/p7/worked-example.json), [test/source map](../../results/p7/p7-source-map.md) |
| L05 | H-flat W0 baseline waste is zero at all three beta values; cross-hierarchy results are sensitivity comparisons. | `quality` / `hierarchy_sensitivity` in [summary](../../results/derived/layout-summary.json), [case CSV](../../results/raw/P7/layout-claim-metrics.csv) |
| L06 | Global certification requires complete terms for every partition; the sweep has 126 certified points and preserves requested-budget bound gaps. | [Global summary](../../results/derived/layout-global.json), [raw global rows](../../results/raw/P7/global/), [global implementation](../../src/tiplog/layout/global.cpp) |
| L07 | Under the quiescence-checked controlled protocol, MASK-DP solved 885/900 synthetic inputs in all ten processes, with b=4/K=4 medians from 12.2 µs (n=5) to 1.63 ms (n=1,000); 15 inputs remain capped. | [Runtime campaign](../../results/p7/runtime-campaign.json), [quiescence](../../results/p7/runtime-quiescence.json), [per-input summary](../../results/derived/layout-runtime.json), [F16](../../results/figures/F16_layout_gaps_scaling.png) |
