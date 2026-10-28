# P5 benchmark preparation review — 2026-10-18

Preparation only while the P4 indexed F3 gate runs. No P5 implementation,
benchmark execution or scope change is authorized by this note. The joint
authorization starts P5 automatically only after the P4 gate passes.

## Requirements and source inspection

Reused approved VALIDATION §§5–8, IMPLEMENTATION P5, the benchmark brief and
joint execution prompt. P5 supplies M1/M1-touch/M2 harnesses and a limited pilot;
the full matrix and P6.2's 30-repetition M1/T1 noise study remain deferred.

Inspected the pinned Google Benchmark **v1.9.5** source at revision
`192ef10025eb2c4cdd392bc502f0c852196baa48`: user guide runtime/reporting
§§240–270 and setup/teardown §§280–310; public header `benchmark.h`
lines1230–1251 (`MinTime`, `MinWarmUpTime`, `Iterations`); and
`src/benchmark_runner.cc` constructor lines280–320, significant-result and
warm-up logic lines390–455, and `DoOneRepetition` lines485–535. Reuse the
additional source/hash record in [p5-method-reading.json](p5-method-reading.json).
No library code was copied.

For the touch-array recommendation, inspected Linux **v6.18**
[`mm/memory.c`, `do_anonymous_page`](https://github.com/torvalds/linux/blob/v6.18/mm/memory.c#L4818)
lines4818–4868: eligible read faults can map a zero page; writes take the private
allocation path. This is a tagged upstream reference, not inspection of this
host's kernel source or a measured page-residency guarantee. The GitHub commit
API lookup was unavailable; the revision actually inspected is the v6.18 tag.
No kernel code was copied.

The runner calls setup/teardown for calibration attempts, warm-up and recorded
repetitions. It calibrates the first measured repetition, then reuses that
iteration count. Explicit `Iterations(n)` overrides the min-time flag; the
public header specifically discourages using it just to limit runtime. Keep
the approved adaptive **0.5s minimum / 0.2s warm-up / 15 repetitions / random
interleaving** protocol. Do not silently replace it with a fixed short run.

## M2: simple bounded setup and honest work accounting

Prefer **one fresh Engine per benchmark invocation**, with one M2 profile
(payload/P/B/distribution) per process and **both index-on/off registrations**
in that process. Random interleaving then interleaves the two actual arms;
destroy each Engine before the next invocation instead of retaining either.
Precompute the seeded publication schedule, intern all
topics and construct payload buffers outside timing. Prefill outside timing
until the ring has wrapped and at least one real capacity eviction occurred,
then begin a stable publication sequence at the same declared schedule phase
for index-on and index-off. Merely allocating a 1 GiB ring does not establish
steady state. Record prefill count, start/end seq/head/tail and capacity/pressure
eviction counters so this property is observable.

Repeated prefill during calibration/repetitions costs memory bandwidth but is
bounded for a limited pilot and keeps starting states reproducible. A moderate
fixed **batch of publications per Google Benchmark iteration** reduces tiny
calibration invocations while retaining adaptive min-time. Record batch size,
actual successful publication count and the schedule period/seed. If the two
arms execute different iteration counts, identify them as different-length
prefixes of the same deterministic workload, validate each against its own
expected count/hash, and do not claim identical complete output digests.
Whole schedule periods per iteration are useful for matching workload mix.

Avoid an all-profile Engine cache: each profile retains about 1 GiB plus index
storage, and persistent state changes block phases and retention histories.
A persistent single-profile steady-state variant would need an explicit
different measurement interpretation; it is unnecessary for the P5 pilot.
Fresh setup must not use invariant/recount/allocator observation inside timing.

Read cumulative counters before/after the measured publication batch outside
timing and report deltas divided by **successful publications**: evicted DATA
and PAD bytes/items separately, block allocations/frees, and pressure loss.
High-water is a gauge/history, not a subtractable event counter: report its
start/end level and stated lifetime. Retain any rejection/failure count. The
same schedule/payload hash and output sink work must apply to both arms; do
not add a per-payload checksum only to one arm. Pool sizing must use generic16
unless the workload explicitly enforces the approved32-byte minimum.

The full harness should expose C=1 GiB; payloads 12/32/64/256 plus empirical mix;
P=1/100/10,000; uniform/Zipf; B=256/1024; index on/off. A single representative
on/off pair suffices for a **limited M2 pilot** if its narrow coverage is stated;
this note does not turn the full matrix into an additional P5 run requirement.

## M1 and M1-touch: representative pilot boundaries

Use the same generated sorted lists and expected output hash for StdPQ,
early-exit BinHeap, Quad and Loser; construct/reset kernels outside timing.
The proposed k=64 uniform and geometric-mean-64 M1 cases, plus k=64 uniform touch,
cover the required four-kernel pilot without implying full-matrix conclusions.
Keep the approved **2^22 outputs** and the M1-touch **1 GiB array / 8-byte read**.

An allocated 1 GiB array is not automatically a 1 GiB touched working set. If
positions are `8*i`, 2^22 outputs address only 32 MiB. Either use recorded,
aligned positions spanning the array (for example 256-byte strides), or report
the actual touched address span and cache-line footprint. A 256-byte stride
spans 1 GiB but reads 8 B in each of 2^22 lines, so it still does not touch every
byte. Initialize the array with deterministic nonconstant data outside timing;
an untouched anonymous/calloc mapping can otherwise read shared zero pages and
does not establish the intended record-fetch footprint. Include the read value
in the common output hash to prevent dead loads.

For geometric owner runs, choosing the same owner at two adjacent run draws
merges the observed runs. Either choose a different next owner for k>1 or
report nominal and observed run means distinctly; k=1 is degenerate. Keep
empirical payload-mix input checksums and synthetic seeds in metadata.

## Pilot provenance and result limits

Run timing only after fuzzing/conversion stop, release build, CPU 2 pinning with
start/end CPU verification, approved no-privilege settings, AC/frequency samples,
and the prescribed idle gap between blocks. Preserve individual repetition JSON,
wall/getrusage CPU times, build flags, actual Git SHA/dirty status and source/input
checksums. Missing counters stay unavailable; Cachegrind data, if collected on
a reduced case, is simulated. Save failed/flagged outcomes. Pilot observations
support only their selected profiles, with no throughput-to-latency or measured
Auto-calibration claim.
