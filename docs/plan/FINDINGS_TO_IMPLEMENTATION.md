# Research findings and concepts mapped to implementation

Inventory of the existing **v1.1** plan, 2026-10-17. This document consolidates decisions already saved in the planning package; it adds no feature, phase authorization, or performance claim. Tier B is approved; P0 tooling is complete and P1–P5 are jointly authorized in dependency order, with finding-to-code/evidence traceability in [PROGRESS](PROGRESS.md). P6–P8, Tier C and roadmap work remain outside this authorization.

Source IDs S01–S61 refer to [RESEARCH.md](RESEARCH.md). They identify inspected specifications, papers, articles, metadata or probes, with reading depth recorded there. They do not mean 61 papers were read in full. Some entries are background or analogies. Review counterexamples are analytical findings from our design audit, not results of executed project tests.

Task/phase IDs refer to [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md); V/M/T/L IDs refer to [VALIDATION_PLAN.md](VALIDATION_PLAN.md). Actual correctness and phase evidence is recorded in PROGRESS; optimizer and full experiment campaigns remain outside the current execution scope.

## 1. Recommended Tier B: data and subscriptions

| # | Saved finding or concept | Planned implementation/use | Phase; evidence |
|---|---|---|---|
| 1 | ITCH is a binary protocol with type-specific lengths, big-endian integers and fixed-point prices | Bounds-checked field decoding; preserve raw payloads; validate supported message lengths | P1; S05, V01 |
| 2 | Historical BinaryFILE framing is separate from the ITCH payload format | Read two-byte lengths, detect zero-length session termination and report truncation/incomplete streams | P1; S06/S07, V02 |
| 3 | Many messages carry locate codes rather than symbol strings; directory state is day-specific | Build locate→symbol mapping; route K by symbol, market-wide messages separately, and count unknown/mismatched mappings | P1; S05, V03 |
| 4 | Sample sizes/counts/skew cannot be inferred reliably from a gzip trailer or assumed traffic pattern | Stream decompression with error propagation; count full bytes/events; measure activity and bursts | P1; S08/S54, L1 |
| 5 | Input identity and conversion determinism matter | SHA-256 manifest, source metadata, normalized trace format and repeatable window conversion | P1; S08/S09, RC-2 |
| 6 | A flat three-segment tree makes the depth-three baseline exact-topic storage | Use the spec-derived family/type hierarchy; retain the flat tree only as a sensitivity case | P1/P2/P7; S01/S05, L5 |
| 7 | Different consumers need different event subsets | Define BOOK/TAPE/AUCT/STAT/REPLAY subscriptions; honor relevant execution/cross/printable semantics | P1/P2/P7; S05, W0–W3. A validated book builder is Tier C, not implied here |
| 8 | Subtree matching must respect segment boundaries and later descendants | Topic registry, ancestor creation, checked local IDs and topic-creation hooks | P2; V06/V08/V38 |
| 9 | Overlapping subscription terms must not duplicate a record | Normalize union terms, compile filters and use one merge cursor per partition | P2/P5; S03, V07/V24 |
| 10 | Wide subscriptions can span partitions not known when compiled | Serve wide terms through the scan path rather than an incomplete static partition set | P2/P5; V07/V23/V25 |

## 2. Recommended Tier B: retained log and replay semantics

| # | Saved finding or concept | Planned implementation/use | Phase; evidence |
|---|---|---|---|
| 11 | Physical ring slots are reused; logical message order must remain distinct | Dense global sequences plus monotonic logical byte positions; checked bounds before physical-slot access | P3; S03/S11, INV-R*, V10–V14 |
| 12 | Variable-length records need explicit end-of-ring handling | Eight-byte alignment, DATA/PAD framing and whole-record capacity eviction | P3; S11/S12, V10/V36 |
| 13 | One record fitting the ring does not guarantee PAD+record fits | Enforce max_record≤C/2 and checked alignment/size arithmetic before mutation | P3; analytical review, V36 |
| 14 | Generic empty-payload DATA is smaller than the ITCH minimum | Use 16-B generic sizing, or enforce the workload-specific minimum before using 32-B sizing assumptions | P3/P4; review, V36/V37 |
| 15 | Sequence lookup should avoid scanning from the oldest record | Sparse sequence→position checkpoints, counting DATA and intervening PAD correctly | P3; S13 analogy, V10/V36 |
| 16 | Recovery needs a stable endpoint while later messages arrive | Capture upper sequence/position on open; exclude later events | P3/P5; V14/V35 |
| 17 | Expired history must produce an explicit outcome | HistoryExpired/FellBehind; a correct delivered prefix on error, never silent skipping | P3/P5; S04/S13, V13/V35 |
| 18 | Scan and index originally disagreed after irrelevant messages expired | Shared conservative unread checkpoint and identical output-budget/status rules across modes | P3/P5; analytical review, V25/V35 |
| 19 | Last delivered record is not the same as a completed replay range | Separate resume checkpoint; advance zero-output completion; handle exact-final-batch completion and future-start inputs explicitly | P3/P5; review, V14/V35 |
| 20 | Equal values do not make two events identical | Preserve every distinct matching sequence-numbered event; no value coalescing | P3/P5; S61, V12/V23/V24 |
| 21 | Allocation/representation failure after eviction could partially mutate the log | Preflight resources and arithmetic before commit; reject without changing observable log/index state | P3/P4; review, V19/V38 |

## 3. Recommended Tier B: indexes and merging

| # | Saved finding or concept | Planned implementation/use | Phase; evidence |
|---|---|---|---|
| 22 | Scanning unrelated messages is avoidable for selective subscriptions | Dense per-partition posting lists referencing retained ring records | P4; S01/S02/S40, V16/V20 |
| 23 | Per-partition worst-case rings waste memory | Shared fixed-size index-block pool, free list and per-partition ordered chains | P4; S01, V15–V20 |
| 24 | Compact offsets require span limits and safe narrowing | Wide delta calculation/check, then u32 storage; full or span-overflow block sealing | P4; design/review, V37 |
| 25 | Late partial seals break sealing-order FIFO expiry | Reclaim through a last-position min-heap; count O(log N_sealed) maintenance | P4; analytical review, DD-07, V17/V37, M2 |
| 26 | Cold open blocks can retain expired entries; references can become stale | Lazy expiry, bounded sweeps, generations and checkpoint-before-dereference rules | P4/P5; review, V17/V18/V37 |
| 27 | Pool exhaustion needs defined behavior | ForceEvict versus RejectPublish, pressure accounting and sizing checks; do not hide shortened retention | P4; V19/V37 |
| 28 | Four-byte entries are not the total index cost | Account for live/stale entries, open/sealed slack, metadata, expiry heap, partition lists and allocator overhead | P4/P6; V17, T5 |
| 29 | Several selected partitions must reconstruct one total order | K-way merge of their ordered cursors, with exact filtering and no duplicate record delivery | P5; S01/S18, V21/V23/V24 |
| 30 | A baseline heap should be a fair implementation | std::priority_queue baseline plus inlined binary heap with early-exit replace-top | P5; S22/S23/S49, M1 |
| 31 | Heap fanout changes comparison and cache costs | Four-ary heap; explicit sibling/front-padding layout, without assuming base alignment solves every crossing | P5; S20, M1/M1-touch |
| 32 | Loser trees have a different tournament replay path | Loser-tree kernel including empty/singleton/exhausted input handling; inspect emitted code before branch claims | P5; S18/S21, V21/V38, M1 |
| 33 | Packed keys can truncate positions or collide with exhaustion sentinels | Checked position/cursor-ID lifetime, reserved sentinel and rejection of invalid limits | P5; review, V38 |
| 34 | Indexing can lose when many messages are relevant | Scan/Indexed/Auto modes; configurable density/partition thresholds calibrated separately from evaluation | P5/P6; S01, H1, T1/T3 |
| 35 | Merge-only speed may disappear when records are fetched | Compare key-only and record-touch kernels, then complete replay; measure publisher/index-maintenance cost too | P5/P6; H2, M1/M1-touch/M2, T1/T2 |

## 4. Recommended Tier B: offline storage-layout optimization

This is a modeled optimizer. Actual WAL files, compaction and disk recovery are later roadmap work.

| # | Saved finding or concept | Planned implementation/use | Phase; evidence |
|---|---|---|---|
| 36 | Complete-subtree cuts exclude useful parent-plus-cold-sibling residual stores | Connected-component partitions within each symbol; include internal-topic messages; no replication/cross-symbol bundling in this model | P7; S01 figure inference and independent model, INV-L1 |
| 37 | A layout depends on which consumers read it | Explicit class weights and exact/subtree/basket match sets; union masks charge each store once per request | P7; S37–S39 analogy, W0–W3, V28 |
| 38 | Read bytes alone omit fixed store costs | Full-window objective with byte cost, fixed read cost, per-store cost and store budget; sensitivity before physical calibration | P7; model choice, L2/L3 |
| 39 | The article's algorithm is underspecified | Fixed-depth baseline and independently specified threshold/hot-singleton greedy; smallest/largest finite threshold endpoints | P7; S01/S33/S34, V30/V31/V39 |
| 40 | An exact reference is needed for small layouts | Cut-set enumeration, independent evaluators, all-store-budget comparison and reconstruction | P7; independent algorithm, V28/V32 |
| 41 | A count-only DP loses information needed by residual stores | Class-mask DP pricing open components, with store-count/materialization state and reconstruction | P7; independently reasoned recurrence, V29/CC-5 |
| 42 | Exactness includes arithmetic, not only recurrence structure | Normalize rational inputs, check integer intermediates/sentinels and reject overflow | P7; review, V39 |
| 43 | The DP's exponential dimension and ENUM's search space limit coverage | Explicit state/time limits; record solved fractions and heuristic-only/timeout rows; exact gaps only for solved identical problems | P7; review, L1/L3/V39 |
| 44 | Global penalties do not solve every integer budget | Nonnegative γ sweep, supported-point scope and certified lower-bound preconditions; no optimum claim from incomplete curves | P7; S36 plus independent argument, V39 |

## 5. Recommended Tier B: correctness, experiments and saved evidence

| # | Saved finding or concept | Planned implementation/use | Phase; evidence |
|---|---|---|---|
| 45 | Two implementations can share the same bug | Independent path/retention oracle, independent C++ framing counter, Python output digests and two layout evaluators | P1–P7; CC-4/CC-6, V09/V28 |
| 46 | Wrap/reclamation/progress errors need adversarial inputs | Golden tests, randomized differential operations and invariants after mutations, including V35–V39 cases | P1–P7; CC-1/CC-2 |
| 47 | Byte parsers and optimized structures need memory/UB checks | libFuzzer targets, minimized regression cases, ASan/UBSan and cross-compiler deterministic checks | P1/P3–P5; S45, CC-3/RC-3 |
| 48 | Throughput, queueing latency and CPU time answer different questions | Explicit metric/timing boundaries; core throughput/recovery costs; no reciprocal-throughput latency claim | P5/P6; VALIDATION §§5–8 |
| 49 | Timing depends on machine state and workload shape | P-core pinning, recorded toolchain/power/thermal context, warm-up, interleaved process repetitions, paired uncertainty estimates | P0/P6; S41/S42/S44/S47 |
| 50 | Hardware counters are conditional and cache labels need evidence | Successful PMU/event probes or time/Cachegrind fallback; distinguish scratch-thrashed from repeat-warm, keep failures | P0/P6; S31/S32/S56 |
| 51 | Real skew, interleaving, breadth and writer cost may change conclusions | Measured dataset distributions, synthetic stress, M1–M3/T1–T3/T5, block-size/crossover/publisher/memory studies | P1/P5/P6; H1–H7 are hypotheses, not findings already confirmed |
| 52 | Results must be traceable and regenerable | Freeze configs/seeds, hashes, build metadata and commands; append-only raw runs, scripted summaries/plots and claims linked to raw evidence | P0–P8; RC-1–RC-3 |
| 53 | Missing/failed cases can bias conclusions | Retain expiry/error/crash/unsupported rows and report model/coverage limits; fill resume numbers only from saved measurements | P6/P8; VALIDATION §§5.5/12 |
| 54 | Historical environment/release notes do not guarantee current compatibility | Explicit validated interpreter, dependency pins, compiler presets and versioned environment records | P0; S48/S57 and read-only refresh. Histogram dependency is optional Tier C |

## 6. Tier C additions — only if selected and authorized

| Concept/findings | Planned addition | Mapping |
|---|---|---|
| Long winning runs can permit safe bulk advancement | Galloping under the smallest competing cursor boundary, with adaptive threshold | P5.2c; S24, V22 |
| Closed-loop load can hide time spent waiting | Open-loop reboot-storm experiment, scheduled-arrival latency, publisher lag and failure counts | T4; S43; optional histogram release reviewed through S57 |
| Complete book state needs the full relevant event history | Session-start book-consistency validator for references/share counts | V34; S05. This is not a matching/execution simulator |
| Static layouts/thresholds can degrade under changing traffic or demand | Separate data-skew and subscription-popularity drift with frozen pre-change choices and declared seeds/time shape | L6; S39/S50 |
| Local changes can improve heuristic layouts without proving optimality | First-improvement edge-toggle local search | H-LS; explicitly heuristic |
| Trade-only data is a distinct workload with different timestamps/order | Binance conversion/checksums, spot µs handling, constructed cross-symbol order and declared limitations | R7; S09/S10 |
| Topic tags may reduce irrelevant record fetches | Tagged index entries; preserve the existing shared expiry contract | R9; T1 delta and extended V checks |

An extra Nasdaq day and optional converter property-test tooling are separately selectable data/tool choices, not required Tier B work.

## 7. Later full-system roadmap — separate approval and start required

| Roadmap item | Concepts that will inform implementation if authorized | Evidence and checks |
|---|---|---|
| R1 — durable log | WAL framing/versioning, CRC, group commit, durable sequence acknowledgments, tail recovery/truncation and declared error/crash model | S13/S26/S28/S29/S55; V40–V42/V47 |
| R2 — storage and handoff | Compaction into store packs, sparse per-store sequence lookup, manifests/CURRENT, file/directory sync, orphan GC and gap/duplicate-free repeated disk↔tip handoff | S27/S31/S59; V43–V46 |
| R3 — disk evaluation | Explicit pread recovery, page-aligned eviction attempts/residency snapshots, process vs device I/O accounting, cost/ranking calibration, rewrite cost and WAL/pack write amplification | S30/S31/S39/S51–S53/S56; D1–D3 |
| R4 — concurrency | Publication ordering, lifetime/alignment, synchronized reader and writer access, protected reclamation, false sharing and reader scaling | S14–S17/S58; full protocol justification, TSan/V48, optional perf c2c |
| R5 — networking | TCP framing, flow control, bounded retries/outstanding work, cancellation, slow-consumer policy and resource-release checks | S60; protocol/overload/failure cases |
| R6 — trading relevance | Book-feature staleness and time-to-correct-state; identical event-processing logic across reference/recovered streams | S61 and existing R6; no alpha/profit claim |
| R7 — secondary dataset | Binance workload described in §6 | Tier C or separately authorized roadmap |
| R8 — stronger crash model | Filesystem/power-loss testing and injected persistence states; distinguish this from process-crash tests | S28/S29; planned R8 fault campaign |
| R9 — tagged indexes | Tag-based filtering described in §6 | Tier C or separately authorized roadmap |
| R10 — different layout space | Cross-symbol cold bundling, with separate feasible set and separate comparisons | Explicit extension, never mixed into within-symbol exact gaps |

Epochs, hazard pointers, RCU and generation-validated copying are **investigated concurrency candidates**, not a promise to implement every scheme. R4 must select and justify its actual protocol; the current C++20 core has no concurrent-reader guarantee.

## 8. Explored but not adopted as project features

- **Offset-value coding:** studied as merge context; no demonstrated need for already scalar unique position keys. The newer linked ACM full text was inaccessible, not read (S49).
- **Learned layouts/SQL/lakehouse packages:** Qd-tree, OReO, LayoutPilot and WAIR supply analogies or evaluation lessons; their engines and theorem guarantees are not transplanted (S37–S39/S51/S53).
- **Flex-style feature DAG engine:** S61 informs event preservation and optional R6; no full feature framework is included.
- **Mirrored virtual-memory ring:** considered alternative; in-band PAD is selected for the core.
- **Per-partition worst-case index buffers:** shared blocks are selected instead.
- **ILP solver dependency:** considered alternative; ENUM/class-mask DP are selected for the defined model.
- **Mmap as the disk-recovery reader:** explicit pread is proposed. Immutable trace-file reading may still use mmap; that is a different use.
- **Distributed consensus/replication:** context from Aria/log literature, not a Raft or replicated-service implementation.
- **C++26/C++29 standard-library migration:** proposal status is background; C++20 remains the target.
- **Uninspected books/full papers:** optional references are not represented as completed study. Knuth §5.4.1 remains optional/uninspected in the ledger.

## 9. Unknown until implementation

No saved result yet establishes actual dataset skew, decompressed counts/size, best merge kernel, scan/index crossover, Auto thresholds, pool memory overhead, DP/ENUM agreement or practical coverage, available hardware counters, disk α/β, or any speedup. The plan specifies how these will be measured. Sources' published gains are not tiplog results.

This inventory maps findings to the entire proposed implementation. It does not authorize any phase. See [PROGRESS.md](PROGRESS.md) for current state.

## Execution traceability additions — 2026-10-18

Finding28 → P4.4 `index::Index::stats/recount` and `tiplog_index_memory` → V17 structural recount plus actual glibc allocator observations: [source/method/evidence](../../results/p4/memory-sources.md). Findings21/24–27 → prepared publication, wide-before-narrow deltas, expiry min-heap, generation/sweep and pressure contracts → [index ledger](../../results/p4/index-sources.md), [Engine ledger](../../results/p4/engine-sources.md), [independent pressure fixture](../../tests/fuzz/pressure_fixture.hpp). Passed versus running gate checks remain explicitly distinguished in PROGRESS. These implement existing v1.1 requirements; no optional system is added.
