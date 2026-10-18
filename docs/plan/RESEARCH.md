# RESEARCH — evidence ledger and source analyses

Plan version **v1.1** · 2026-10-17 · original planning research and dated refresh retained. §7 records authorized Phase 0 tooling/source inspection; engine, optimizer and benchmark results remain future work. Current phase status is in PROGRESS.

## 0. Method, scope, and labels

- **Browsing was available.** The original ledger records 2026-10-16 access. The §6 refresh records actual 2026-10-17 inspection separately; it does not imply every old source or probe was repeated.
- **How each source was inspected.** The ledger states one of:
  - **raw**: I read the extracted text myself (PDF → `pdftotext`, or the raw Markdown/HTML).
  - **fetch**: the page was retrieved through a web-fetch tool that returns a model-written digest. Treat quotes from these as paraphrase until re-checked against the page.
  - **biblio**: only the bibliographic record or abstract, usually from search results. The content was not read.
  - **probe**: direct metadata inspection, such as HTTP headers, the first bytes of a file, or local commands.
- **Labels used in all plan documents:**
  - **[A]**: the Jane Street article states this.
  - **[V]**: verified from a primary source or a probe.
  - **[I]**: my inference.
  - **[D]**: design choice (see ARCHITECTURE §11).
  - **[S]**: assumption.
  - **[H]**: hypothesis to be tested.
  - **[Q]**: open question.
- **Stop rule.** Collection stopped once every decision in ARCHITECTURE §11 rested on at least one primary source or on a planned measurement. Searches were bounded. Not finding prior work is not evidence of novelty.

---

## 1. The reference article: statements, inferences, gaps

Source: N. Yang, "Scaling and benchmarking a critical message bus using a new indexing strategy", Jane Street Blog, 2026-10-05 ([link](https://blog.janestreet.com/scaling-and-benchmarking-a-critical-message-bus/)). I read all 12 pages of your PDF. The seven embedded figures were extracted at native resolution, and the live page's link targets were checked.

### 1.1 What it states [A]

| # | Statement (paraphrased) | PDF page |
|---|---|---|
| A1 | Aria is Jane Street's internal messaging framework and hosted system, processing multiple TB/day. Clients subscribe to live streams. | 1 |
| A2 | Intro: the work led to "a 30% decrease in CPU usage when running on production workloads". | 2 |
| A3 | The recent stream (the **stream tip**) lives in an in-memory **ring buffer**. Clients that fall behind request recent messages from it (**tip recovery**). | 2 |
| A4 | Topics form a hierarchical namespace. Clients subscribe to a topic or a **topic subtree** (globstar-like). Aria filters the whole stream down to the subscribed topics. | 2 |
| A5 | Originally a linear filtering pass: algorithmically inefficient but cache-friendly. As tip-recovering clients grew, some servers hit 100% CPU and clients "fell off the tip". The temporary fix was more servers. | 3 |
| A6 | A per-topic index is untenable (instances can have almost a million topics). Instead there is one index per **topic partition**, meaning all topics sharing the same two-segment prefix. | 3 |
| A7 | Each partition index records its messages' locations in the stream. A request does an **n-way merge with a min-heap** to rebuild the in-order stream for the chosen partitions. | 3–4 |
| A8 | A profiling tool varied partition count, degree of interleaving, and reader count. | 4 |
| A9 | The min-heap was the main bottleneck. An agent built and profiled five heap implementations overnight. `fast_heap_unboxed` gave **2×** on indexed recovery. | 5 |
| A10 | Testing used expect tests, Antithesis, and agent review. | 5 |
| A11 | Per-index ring buffers were rejected (not dynamically resizable, so they need worst-case sizing). Index size is inversely proportional to message size. The minimum message is 32 bytes, so a tip store full of minimum messages would need a **2 GB** index, and per-partition worst-case sizing wastes memory. | 5 |
| A12 | A **shared pool of blocks with 1024 entries**. Indexes point to blocks. A block is popped and reused once all its messages have left the ring. | 6 |
| A13 | Initial recovery after a reboot often reads everything since the start of the week (millions to billions of messages). In one incident, a recovery that usually took under 2.5 s took over 13 min, because 10× more data was read and filtered than was needed. | 6–7 |
| A14 | On disk: chronological segments per topic partition. A separate process splits them into **subtree stores**, trading many files (efficient filtering, costly recombination) against few files. | 7 |
| A15 | Old heuristic: the store is the topic's first three segments, and topics with fewer than three segments get their own store. In effect, each direct child of a partition gets a store. | 7–8 |
| A16 | Failure mode: one topic much larger than its siblings forces readers of the small topic to filter the large one. Users should not need to know storage internals. | 8 |
| A17 | Per-topic volume is known because splitting runs after the stream is persisted. | 8 |
| A18 | Evaluation lenses: bytes ignored when reading a topic, the sum over topics, the worst topic, and the worst total/useful ratio. Also an LLM-built web UI. | 8–9 |
| A19 | Final algorithm: "a greedy clustering algorithm with a binary search". Large topics get their own store; small topics are folded together. | 9 |
| A20 | Splitting tests: expect tests on properties, an existing property-based test extended to randomize the split, and Antithesis runs. | 11 |
| A21 | Results: tip indexing is in production. "Preliminary results in our staging environment … 30% less CPU utilization in some real-world scenarios". Multi-second tail latencies appeared only on servers without indexing. Adaptive splitting is in staging. | 11–12 |

**Framing note.** A2 (intro) says "production workloads", while A21 (results) says "staging … some real-world scenarios". The 2026 intern round-up (S02) says "30% in real-world scenarios". I treat 30% as a scenario-specific staging result, and the plan never compares itself against it.

### 1.2 Inferences [I]

- **I-1** The index is **dense** (one entry per message). This is corroborated by S02's "dense index over each Aria topic partition's offsets in the ring buffer".
- **I-2** The 2 GB figure means (ring bytes / 32) × entry size ≈ 2 GB. That fits, for example, an 8 GiB ring with 8-byte entries or a 16 GiB ring with 4-byte entries. Neither the ring size nor the entry size is stated.
- **I-3** "Unboxed" most likely carries the OCaml/OxCaml meaning: values stored without a separate heap box per element (S46). The C++ analogue is keys stored inline in one contiguous array of plain words (ARCHITECTURE §5.7). The real implementation is unknown.
- **I-4** In the page-10 figure the store boxes nest (teal ⊂ blue ⊂ green), but the text says each store's contents are separate. Each store is therefore the subtree under its root **minus** the subtrees of nested stores. In other words, a layout is a partition of the topic tree into **connected components** (a *residual* layout).
- **I-5** Both illustrated layouts use **4 stores**, which fits a store budget. The article does not mention one.
- **I-6** No store in the figure spans the two depth-2 subtrees, and A14 says segments are per partition. Splitting therefore appears to be **confined to each partition**.
- **I-7** The objective and the binary-searched variable are **not identifiable** from the text (worked example below).

### 1.3 Worked example from the figure (my computation)

The node labels were read from the native-resolution figure images. Units are taken as decimal (MB = 10⁶ B). Binary units would change the ratios slightly but none of the conclusions.

```
root(0)
├── L(0)                         ← partition root (two-segment prefix)
│   ├── A(28.5 MB)               ← internal topic with its own messages
│   │   ├── a1(10 MB)
│   │   └── a2(2.72 GB)
│   └── b(148 KB)
└── R(0)                         ← partition root
    ├── R1(0) ── c1(197 B), c2(29.3 KB)
    └── R2(0) ── d1(10 KB), d2(421 KB)
```

- **Before (three-segment rule):** {A,a1,a2}, {L,b}, {R1,c1,c2}, {R2,d1,d2}.
- **After (figure):** {a2}, {A,a1}, {L,b}, {R,R1,R2,c1,c2,d1,d2}.

The workload is "read each non-empty topic once by exact topic" (lens A18). Waste = bytes read − bytes of that topic.

| Metric | Before | After (figure) | Exact optimum, 4 stores (ARCHITECTURE §6 model, workload W0) |
|---|---:|---:|---:|
| Stores | 4 | 4 | 4 |
| Total waste (B) | 5,517,460,497 | 39,881,491 | **30,029,491** |
| Largest single-topic waste (B) | 2,748,500,000 (a1) | 28,500,000 (a1) | 28,500,000 (b) |
| Worst read amplification | 275.9× (a1) | 2,337.6× (c1, 197 B) | 2,337.6× (c1) |
| Subtree read of A: bytes / waste / stores touched | 2,758,500,000 / 0 / 1 | 2,758,500,000 / 0 / 2 | 2,758,648,000 / 148,000 / 3 |

The optimum layout is {a2}, {a1}, {L,A,b}, {R…}.

What the example shows:

1. The "after" layout cuts total waste by about 138×. It also makes the **ratio** lens worse, because ratios are dominated by tiny topics (197 B). The choice of objective changes the answer.
2. The "after" layout is **not** the minimum-total-waste layout at 4 stores.
3. A Kundu–Misra threshold greedy with hot-topic isolation (ARCHITECTURE §6.6) reproduces "after" exactly for thresholds T ∈ [38.5 MB, 38.648 MB). It reproduces the optimum shown for T ∈ [28.648 MB, 38.5 MB). Both ranges yield 4 stores. So "binary search for a threshold that yields the budget" is ambiguous: the *smallest* such T gives one layout and the *largest* gives the other. The article does not say which, if either, it uses.

The plan therefore implements both bisection variants as **independently designed heuristics** and does not claim to reproduce Aria's algorithm.

### 1.4 What the article leaves unspecified [Q]

- The optimization objective and any store budget.
- The greedy rule and the variable being binary-searched.
- How messages on internal topics are handled, and the time window per split.
- Ring size, index entry format, and intra-partition filtering cost.
- How reclamation interacts with readers holding block references, and the concurrency model.
- Invariants beyond "never drop or reorder".
- Measurements beyond 2×, 30%, 10×, and 2.5 s → 13 min.

---

## 2. Evidence ledger

Columns: **ID · source · date · inspected (method) · key claim(s) · limitations · decision informed.**

| ID | Source | Date | Inspected | Key claim(s) | Limitations | Decision informed |
|---|---|---|---|---|---|---|
| S01 | Yang, Jane Street Blog article ([link](https://blog.janestreet.com/scaling-and-benchmarking-a-critical-message-bus/)) | 2026-10-05 | raw: all 12 PDF pages + 7 figures; fetch: live links | §1.1 | No algorithm or objective; the 30% framing is inconsistent | Project framing; DD-03/06/07/13/14 |
| S02 | Somers, "What the interns have wrought, special jumbo 2026 edition" ([link](https://blog.janestreet.com/wrought-2026/)) | 2026-09-30 | fetch | "dense index over each … partition's offsets in the ring buffer"; 30% in real-world scenarios | One paragraph | Dense index (DD-06) |
| S03 | Signals & Threads ep. 14, "State Machine Replication, and Why You Should Care" (D. Patti, R. Minsky) ([link](https://signalsandthreads.com/state-machine-replication-and-why-you-should-care/)) | 2022-04-20 | fetch (transcript digest) | Aria: hierarchical namespace, subtree subscriptions, one canonical total order, payloads opaque, proxy filtering, every byte persisted | 2022 state; nothing about the tip | Total order and subtree semantics; payload-opaque engine (§3) |
| S04 | Patti, "Getting from tested to battle-tested" ([link](https://blog.janestreet.com/getting-from-tested-to-battle-tested/)) | 2025-12-03 | fetch | Antithesis on Aria found a restarted server returning **zeroed bytes instead of an error** (tip-retransmitter flaw) | Digest | Explicit expiry errors; verify seq (and CRC on disk) of every delivered record (DD-10) |
| S05 | Nasdaq TotalView-ITCH 5.0 spec ([PDF](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf)) | PDF built 2024-02-28; latest revision entry 2023-04-28 | raw: Overview, Architecture, Data Types, §1.1–1.8, App. A, App. B | §3.1 below | Historical-file framing is not in this spec | Parser, lengths, topic map, consumers |
| S06 | Nasdaq BinaryFILE v1.0 ([PDF](https://www.nasdaqtrader.com/content/technicalSupport/specifications/dataproducts/binaryfile.pdf)) | 2008-12-31 (rev. note 2010-03-30) | raw: complete | 2-byte big-endian length + payload; a **zero-length message ends the session**; without it, the file is incomplete | — | Framing and completeness check |
| S07 | Nasdaq, "Accessing Historical TotalView-ITCH Data via SFTP" ([PDF](https://www.nasdaqtrader.com/content/technicalSupport/specifications/dataproducts/ITCHFTP.pdf)) | undated | raw | `SMMDDYY-v50.txt.gz` = BinaryFile ITCH 5.0; paid SFTP, rolling 3 months | — | How to read the `S…-v50.txt.gz` samples |
| S08 | `emi.nasdaq.com/ITCH/Nasdaq ITCH/` listing, HTTP HEAD, first 128 KiB of two files | accessed 2026-10-16 | probe | §3.2 (sizes, ranges, framing verified on 2019 and 2025 files, timestamps, gzip ISIZE) | No license text; listed `.md5sum`/`.done` files return 404; ISIZE is mod 2³² | Dataset choice; streaming conversion; own SHA-256; no redistribution |
| S09 | binance-public-data README ([link](https://github.com/binance/binance-public-data)) + HEAD probes | accessed 2026-10-16 | fetch + probe | Trade columns; **spot timestamps in µs from 2025-01-01**; `.CHECKSUM` is SHA-256; archived files may be updated; sizes in §3.2 | Header-row presence unverified | Secondary workload (§2.6 of ARCHITECTURE) |
| S10 | Binance Vision [dataset terms](https://raw.githubusercontent.com/binance/binance-public-data/master/TERMS_AND_CONDITIONS.md) v1.0 | updated 2026-08-26; rechecked 2026-10-17 | terms header and §§2–8 | Dataset CC BY-NC-SA 4.0 plus stated restrictions; distinct from repository-code licensing | Published terms, not blanket permission for every proposed use | Usage and redistribution policy |
| S11 | Aeron Transport Protocol Specification ([wiki](https://github.com/aeron-io/aeron/wiki/Transport-Protocol-Specification)) | accessed | fetch | Frames aligned to 32 B; 32-B data header; **padding frames** fill term ends; shared-memory publish writes a negative length, then the frame, then a positive length | Wiki, not code | In-band PAD records; logical positions; R4 publish protocol |
| S12 | Rostedt, "Lockless Ring Buffer Design" ([kernel docs](https://docs.kernel.org/trace/ring-buffer-design.html)) | 2009 (current doc) | fetch | Overwrite mode vs producer/consumer mode; reader-page swap; reserve/commit | Per-CPU kernel design | Overwrite-oldest semantics (analogy) |
| S13 | Apache Kafka, `docs/implementation/log.md` ([link](https://github.com/apache/kafka/blob/trunk/docs/implementation/log.md)) | trunk, last commit 2026-10-02 | raw | Segments named by first offset; deletion by whole segment; copy-on-write segment list for consistent reads; startup validates the newest segment (size bounds + CRC) and **truncates**; two corruption kinds (lost tail, added garbage); out-of-range offsets raise an exception | Text partly historical (byte offsets as IDs) | WAL recovery rule; HistoryExpired semantics |
| S14 | Fraser, *Practical lock-freedom*, UCAM-CL-TR-579 ([PDF](https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-579.pdf)) | 2004-02 | raw §5.2.3 | Epoch-based reclamation: limbo lists and a global epoch; free lists from two epochs back once every thread has seen the current epoch | — | R4 option |
| S15 | Hart, McKenney, Demke Brown, "Making Lockless Synchronization Fast: Performance Implications of Memory Reclamation", IPDPS 2006 ([PDF mirror](https://www.read.seas.harvard.edu/~kohler/class/aosref/hart06making.pdf)); JPDC 2007 extended version | 2006 | raw: abstract, intro | QSBR, EBR, and hazard pointers compared: "no globally optimal scheme" | Microbenchmark-based | R4 must measure; the core avoids concurrency |
| S16 | Boehm, "Can Seqlocks Get Along with Programming Language Memory Models?", MSPC 2012, DOI 10.1145/2247684.2247688 | 2012-06-16 | biblio/abstract | Seqlock readers make racing speculative loads, which conflict with data-race-free models; analyzes C++11 implementation options | Not read in full | R4 read protocol: atomics plus fences, no racy `memcpy` |
| S17 | WG21 P2530R3 (hazard pointers), P2545 (RCU); follow-ups P3427R7 / P3428R4 | 2023–2026 | original search; follow-ups rechecked in S58 | Distinguish C++26 draft baseline from proposed C++29 extensions | Local library support has not been feature-probed; no universal no-implementation claim | Stay on C++20; roadmap background only |
| S18 | Sanders, "Fast Priority Queues for Cached Memory", ACM JEA 5 (2000) ([PDF](https://ae.iti.kit.edu/documents/people/sanders/papers/spqjea.pdf)) | 2000 | raw: abstract, §2 loser-tree paragraph, App. A.5 | A loser tree replaces the winner with ⌈log k⌉ comparisons and has **predictable memory access**; a sentinel handles empty sequences; sequence heaps were ≥2× faster than binary/4-ary heaps (2000-era hardware) | Old hardware; priority-queue setting | Loser-tree layout; inline key + index |
| S19 | Knuth, *TAOCP* Vol. 3, §5.4.1 "Multiway Merging and Replacement Selection" | 1973/1998 | not inspected (cited by S18) | Tree of losers | — | Reference only |
| S20 | LaMarca & Ladner, "The Influence of Caches on the Performance of Heaps", ACM JEA 1 (1996), DOI 10.1145/235141.235145 | 1996 | biblio + secondary summary | Align siblings to cache lines; larger fan-out helps until it degenerates | Not read | 4-ary heap variant |
| S21 | Polyntsov et al., "Implementing the Comparison-Based External Sort", [arXiv 2207.12713](https://arxiv.org/abs/2207.12713) | 2022-07-26 | raw: abstract, conclusions | Loser tree beat naive and heap merges in their DBMS external sort (84 runs) | External, I/O-bound sort | Include a loser tree; presume no winner |
| S22 | Boreham, Prometheus PR #12878 "postings: use Loser Tree for merge" ([link](https://github.com/prometheus/prometheus/pull/12878)) | opened 2023-09-20, merged 2023-12-12 | fetch | −70% to −88% time at 10–10,000 series vs a heap called through interfaces; about 4× memory; no change at 1 series | Go; the baseline paid dynamic dispatch | The heap baseline must be inlined and optimized; report memory |
| S23 | pgsql-hackers, "Support loser tree for k-way merge" ([Linnakangas 2025-12-03](https://www.postgresql.org/message-id/28f47336-84e2-445e-8216-d1ce7d3ddc3e%40iki.fi), [Naylor 2025-12-08](https://www.postgresql.org/message-id/CANWCAZZ6KpsL%2BoEJFyQxqMMNv7FHRxPqUGafn9sqJzg_BmH5Qg%40mail.gmail.com), later messages to 2026-05) | 2025-12 to 2026-05 | fetch (2 messages) | WIP patch 3–13% faster in one test; reviewers asked for worst cases; low-cardinality regressions reported; comparison counts disputed | Ongoing; numbers unverified | Heap replace-top with early exit; bursty inputs in M1; no presumed winner |
| S24 | CPython `Objects/listsort.txt` ([link](https://github.com/python/cpython/blob/main/Objects/listsort.txt)) | main (accessed) | fetch | `MIN_GALLOP` = 7 with adaptive adjustment; exponential then binary search; 2⌊lg i⌋+2 vs i+1 comparisons; `gallop_left`/`gallop_right` tie rules | Sorting context | Galloping wrapper (§5.7) |
| S25 | Demaine, López-Ortiz, Munro, "Adaptive Set Intersections, Unions, and Differences", SODA 2000 ([page](https://erikdemaine.org/papers/SODA2000/)) | 2000 | biblio/abstract | Instance-adaptive algorithms within a constant factor of a proof-size measure | Not read | Frame merge cost by interleaving (optional) |
| S26 | LevelDB `doc/log_format.md` ([link](https://github.com/google/leveldb/blob/main/doc/log_format.md)) | main (accessed) | fetch | 32 KiB blocks; 7-byte header with CRC32C over type + data; FIRST/MIDDLE/LAST fragments; trailer; resync at block boundaries | — | WAL framing alternative; CRC32C |
| S27 | RocksDB wiki "MANIFEST" ([link](https://github.com/facebook/rocksdb/wiki/MANIFEST)) | accessed | fetch | Version edits; CURRENT points to the latest manifest; atomic groups; rollover | — | Manifest alternative (R2) |
| S28 | Pillai et al., "All File Systems Are Not Created Equal", OSDI 2014 ([PDF](https://pages.cs.wisc.edu/~remzi/Classes/739/Fall2016/Papers/alice-osdi14.pdf)) | 2014 | raw: parts of §1–2 | Persistence properties vary by file system and configuration; atomic append is not universal (ext2, writeback modes); ordering assumptions break; append-before-rename bugs | 2014 file-system versions | Never assume append atomicity or ordering; CRC every record; fsync file, rename, fsync directory |
| S29 | Rebello et al., "Can Applications Recover from fsync Failures?", USENIX ATC 2020 ([PDF](https://www.usenix.org/system/files/atc20-rebello.pdf)) | 2020-07; rechecked 2026-10-17 | abstract/intro, §5 observations 7–8, conclusion | A retry after writeback failure need not restore durability; restart can also be unsafe | General storage faults exceed the planned crash-only model | Stop acknowledgments on error as a project policy; no automatic safe-restart theorem |
| S30 | Crotty, Leis, Pavlo, "Are You Sure You Want to Use MMAP in Your DBMS?", CIDR 2022 ([PDF](https://www.cidrdb.org/cidr2022/papers/p13-crotty.pdf)) | 2022 | raw: abstract, problem headings | Transactional safety, I/O stalls, error handling (SIGBUS), TLB shootdowns, eviction | DBMS focus | Disk recovery via `pread`; never infer physical reads from mmap |
| S31 | Linux man-pages: fsync(2), posix_fadvise(2), mincore(2), proc_pid_io(5), open(2), perf-stat(1) (man7.org) | accessed | raw excerpts | New directory entries need a directory fsync; `DONTNEED` does not drop dirty pages; `read_bytes` = bytes "really fetched from the storage layer"; `perf stat -r`, `-x` | — | Durability protocol; cold-cache method; physical-I/O metric |
| S32 | Kernel docs, "Perf events and tool security" ([link](https://docs.kernel.org/admin-guide/perf-security.html)) | accessed | raw | `perf_event_paranoid` ≥2: per-process user-space only; ≥1: per-process user + kernel; ≥0: system-wide; CAP_PERFMON | Ubuntu adds levels above 2 | DEC-2 |
| S33 | Kundu & Misra, "A Linear Tree Partitioning Algorithm", SIAM J. Comput. 6(1):151–154 | 1977 | biblio + secondary (S34) | Minimum number of connected clusters with weight ≤ a bound on a tree, in linear time | Full text not read | H-KM greedy (§6.6) |
| S34 | Buchin & Selbach, "Partitioning algorithms for weighted trees and cactus graphs", [arXiv 2001.00204v3](https://arxiv.org/abs/2001.00204) | 2022-03-02 | raw: abstract, §1.1 | MinNum (0,u)-partition is linear on trees [Kundu–Misra]; bounded partition minimizing edge cost is **NP-hard even on trees**, pseudo-polynomial O(u²n) [Lukes 1974] or O(un²) [Johnson–Niemi 1983]; min-max p-partition is polynomial on trees | Survey-level for the cited works | Complexity framing for §6 |
| S35 | Johnson & Niemi, Math. Oper. Res. 8(1):1–14, DOI 10.1287/moor.8.1.1; Lukes, IBM J. R&D 18 (1974) | 1983 / 1974 | biblio | DP techniques for tree knapsack and tree partition | Not read | DP style (§6.4) |
| S36 | Everett, "Generalized Lagrange Multiplier Method …", Operations Research 11(3):399–417, DOI 10.1287/opre.11.3.399 | 1963 | abstract | A Lagrangian minimizer is a true optimum for its own constraint level ("fail-safe"); some levels may be unreachable | — | Global store budget via a γ sweep (§6.5) |
| S37 | Yang et al., "Qd-tree: Learning Data Layouts for Big Data Analytics", SIGMOD 2020 ([arXiv 2004.10898](https://arxiv.org/abs/2004.10898)) | 2020 | abstract | Workload-aware routing tree minimizing blocks read; greedy and RL | Analytics context | Analogy |
| S38 | Sun, Franklin, Krishnan, Xin, "Fine-grained Partitioning for Aggressive Data Skipping", SIGMOD 2014 ([PDF](https://amplab.cs.berkeley.edu/wp-content/uploads/2014/05/mod415-sun.pdf)) | 2014 | abstract | Workload-driven blocking; NP-hard; bottom-up clustering; 2–5× | — | Analogy |
| S39 | OREO (arXiv 2405.04984, 2024); LayoutPilot (VLDB 2026) | 2024 / 2026 | search-level | Layouts degrade under workload drift; layout advice at ingestion time | Not read | Motivates L6 (cross-window robustness) |
| S40 | "Scalably Supporting Durable Subscriptions in a Publish/Subscribe System", DSN 2003 (IBM; authors include S. Bhola), DOI 10.1109/DSN.2003.1209916 | 2003 | abstract | Log each message once; **persist filtering information** so catch-up avoids re-filtering; early-release reclamation for misbehaving subscribers | Not read | Prior art for index-assisted catch-up; FellBehind policy |
| S41 | LLVM "Benchmarking tips" ([link](https://llvm.org/docs/Benchmarking.html)) | accessed | fetch | ASLR off, `performance` governor, `cset shield`, SMT sibling offline, turbo off, tmpfs | No hybrid-CPU guidance | Environment protocol (VALIDATION §5) |
| S42 | Google Benchmark user guide ([link](https://github.com/google/benchmark/blob/main/docs/user_guide.md)); releases | accessed | fetch + probe | `DoNotOptimize` semantics; repetitions and aggregates; random interleaving; minimum warm-up; JSON output; counters. Releases: v1.9.5 (2026-01-21), v1.10.0 (2026-10-14) | — | Microbenchmark protocol; pin v1.9.5 |
| S43 | Tene, wrk2 README ([link](https://github.com/giltene/wrk2)) | accessed | fetch | Coordinated omission; constant-rate load; latency measured from **intended** send time; HdrHistogram | HTTP setting | T4 open-loop design |
| S44 | Mytkowicz et al., ASPLOS 2009 ([page](https://sape.inf.usi.ch/publications/asplos09)); Kalibera & Jones, ISMM 2013 ([page](https://kar.kent.ac.uk/33611/)) | 2009 / 2013 | abstract | Measurement bias (link order, environment size); repetition planned per level | Not read in full | Record and vary the environment; repeat at process level |
| S45 | LLVM libFuzzer docs ([link](https://llvm.org/docs/LibFuzzer.html)); Clang [ASan](https://clang.llvm.org/docs/AddressSanitizer.html) / [UBSan](https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html) / [TSan](https://clang.llvm.org/docs/ThreadSanitizer.html) | accessed | fetch / link check | Fuzz target API and flags; **libFuzzer is in maintenance mode** (authors moved to Centipede; bug fixes continue) | — | Fuzz and sanitizer plan |
| S46 | Jane Street tech talk "Unboxed Types for OCaml" ([link](https://www.janestreet.com/tech-talks/unboxed-types-for-ocaml/)) + OxCaml search results | — | search-level | Unboxed layouts avoid the uniform boxed representation | — | I-3 |
| S47 | Local environment probe | 2026-10-16 | probe | §3.8 | Laptop with a hybrid CPU | Benchmark protocol, sizing, DEC-2 |
| S48 | GitHub release metadata | 2026-10-16 | probe | Benchmark v1.9.5 / v1.10.0; HdrHistogram_c 0.11.10 (2026-06-29), 0.12.0 (2026-10-02), 0.12.1 (2026-10-16); googletest v1.18.0 (2026-08-10); system googletest 1.17.0 | — | Pin settled releases (DD-15) |

DOI links returned HTTP 403 to scripted checks (publisher bot-blocking). They are cited as identifiers.

---

## 3. Area syntheses

### 3.1 ITCH 5.0 (S05, S06, S07, S08) [V]

**Encoding**
- Integers are unsigned big-endian. Alpha fields are left-justified and space-padded.
- `Price(4)` has 4 implied decimals (maximum 200,000.0000). `Price(8)` is used for MWCB levels.
- **Timestamps are 6 bytes of nanoseconds since midnight.**

**Common header (every message):** Message Type (1), Stock Locate (2), Tracking Number (2), Timestamp (6).
- Stock Locate sits "at the same position in all messages to support efficient filtering".
- Locate codes are assigned daily, starting at 1, via Stock Directory `R` messages at the start of day. They never change intraday and should not be assumed stable across days.
- Locate is **0** for messages that are not stock-specific.

**Message lengths (bytes, payload only; derived from the spec offsets):**

| Type | Name (spec §) | Len | Symbol field? | | Type | Name (spec §) | Len | Symbol field? |
|---|---|---:|---|---|---|---|---:|---|
| S | System Event (1.1) | 12 | no (locate 0) | | A | Add Order, no MPID (1.3.1) | 36 | yes |
| R | Stock Directory (1.2.1) | 39 | yes | | F | Add Order, MPID (1.3.2) | 40 | yes |
| H | Trading Action (1.2.2) | 25 | yes | | E | Order Executed (1.4.1) | 31 | **no** |
| Y | Reg SHO (1.2.3) | 20 | yes | | C | Executed w/ Price (1.4.2) | 36 | **no** |
| L | Market Participant Position (1.2.4) | 26 | yes | | X | Order Cancel (1.4.3) | 23 | **no** |
| V | MWCB Decline Level (1.2.5.1) | 35 | no (locate 0) | | D | Order Delete (1.4.4) | 19 | **no** |
| W | MWCB Status (1.2.5.2) | 12 | no (locate 0) | | U | Order Replace (1.4.5) | 35 | **no** |
| K | IPO Quoting Period (1.2.6) | 28 | yes, **but locate "Always set to 0"** | | P | Trade, non-cross (1.5.1) | 44 | yes |
| J | LULD Auction Collar (1.2.7) | 35 | yes | | Q | Cross Trade (1.5.2) | 40 | yes |
| h | Operational Halt (1.2.8) | 21 | yes | | B | Broken Trade (1.5.3) | 19 | **no** |
| I | NOII (1.6) | 50 | yes | | N | RPII (1.7) | 20 | yes |
| O | DLCR (1.8, added 2023-04-28) | 48 | yes | | | | | |

**Semantics that matter for this project:**
- E, C, X, D, U, and B carry only locate (plus order or match reference), so routing them needs the locate → symbol directory. K needs symbol-based routing.
- Executions: E, C, and P together give "a complete view of all non-cross executions"; crosses arrive as one Q per symbol. C can be **non-printable** (to avoid double counting with the cross print).
- P has had its order reference zeroed since 2010, and buy/sell is always "B" since 2014.
- Broken Trade and Order Delete can arrive after End of System hours.
- System Event codes: O, S, Q, M, E, C (C is always the last message).
- Symbols are up to 8 characters and may contain a "." delimiter (App. B).
- TotalView-ITCH covers **Nasdaq's own book** for Nasdaq-, NYSE-, NYSE American-, NYSE Arca-, and BATS-listed securities. It is not the consolidated US market.

**Historical-file framing (S06), checked on real files (S08):** each message is preceded by a 2-byte big-endian length. A zero-length message ends the session, and its absence means the file is incomplete. The first bytes of both the 2019-12-30 file and the 2025-12-08 file decode as:
- `00 0c 53 …` → a 12-byte `S` with event `O`, timestamps 03:04:32.057544 (2019) and 03:01:29.045484 (2025);
- `00 27 52 00 01 …` → a 39-byte `R`, locate 1, symbol "A", market category N.

### 3.2 Datasets (S08–S10) [V unless marked]

**NASDAQ samples** (`https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/`):

| File | Bytes (gzip) | Last-Modified | Notes |
|---|---:|---|---|
| `12302019.NASDAQ_ITCH50.gz` | 3,524,013,057 | 2019-12-31 | Smallest listed selected sample; exact decompressed size unknown. ISIZE does not restrict it to the two candidates stated in v1.0 (S54). Completeness/counts await P1. |
| `07302019.NASDAQ_ITCH50.gz` | 3,662,140,094 | 2019-07-31 | |
| `10302019`, `08302019`, `01302019`, `03272019`, `01302020` | 3.87–5.60 GB | 2019–2020 | |
| `S112825-v50.txt.gz` … `S121225-v50.txt.gz` (2025-11-28 to 2025-12-12) | 4.74–12.55 GB | posted 2026-08-05 | Same BinaryFILE framing (verified on S120825) |
| `itch50_05_15.gz`, `itch50_05_18.gz`, `S061226-v50.txt.gz` | 13.0–17.9 GB | 2026-06 | Larger, recent |

Further facts:
- The server supports HTTP range requests (`Accept-Ranges: bytes`).
- The listed `.md5sum` and `.done` files return HTTP 404, so integrity must rely on gzip's CRC (`gzip -t`) plus our own recorded SHA-256.
- **No license or terms text** was found for the samples. Policy [D]: never redistribute raw or message-level derived data; publish only code, checksums, and aggregate statistics; you confirm terms before publishing anything derived.

**Binance spot trades** (`https://data.binance.vision/data/spot/daily/trades/<SYM>/<SYM>-trades-YYYY-MM-DD.zip`):
- Columns: trade id, price, qty, quoteQty, time, isBuyerMaker, isBestMatch.
- Timestamps are in **µs from 2025-01-01**.
- Measured sizes: BTCUSDT 2025-01-01 = 14,017,578 B; 2026-10-14 = 24,911,579 B; monthly 2026-09 = 662,364,112 B; ETHBTC 2025-01-01 = 310,816 B.
- SHA-256 `.CHECKSUM` files exist.
- Terms: CC BY-NC-SA 4.0 (v1.0, 2026-08-26).

**Limitations of the Binance data** [V/I]:
- Trades only, so no order-book reconstruction.
- One exchange.
- No cross-symbol sequence; any global order across symbols is **constructed** by us (by time, symbol, trade id).
- Archived files may be revised later.

### 3.3 Retained logs, rings, positions (S11–S13, S40)

- **Aeron** [V]: in-band padding frames fill the end of a term; frames are aligned; positions are monotonic 64-bit, so readers detect overruns by comparing positions; a frame is published by writing a negative length, then the frame, then a positive length.
- **Linux ring buffer** [V]: two policies, overwrite-oldest or reject-newest. Ours is overwrite-oldest, with explicit errors for readers that are overrun.
- **Kafka** [V]: retention removes whole segments; offsets out of range raise an error; a copy-on-write segment list gives readers consistent views.
- **DSN 2003** [V, abstract]: persisting filtering information to avoid re-filtering on catch-up is long-standing prior art, so the per-partition index is not presented as a new idea.
- **Transfer** [D]: an 8-byte-aligned variable-length record ring with in-band PAD; logical 64-bit positions that are never recycled; whole-record eviction; position-based staleness checks (ARCHITECTURE §5.3).

### 3.4 Index pools, reader lifetimes, reclamation (S01, S14–S17)

- The article's design [A] is a shared pool of 1024-entry blocks, with a block freed once all its messages have left the ring.
- **Single-threaded core** [D]: a generation counter per block plus position checks are enough.
- **Concurrent extension**: candidates are epoch-based reclamation (S14), generation-validated optimistic reads on type-stable pool memory with atomics and fences (S16), and hazard pointers. Hart et al. (S15) found **no globally best scheme**, so R4 must measure.
- The project stays on C++20. Base draft interfaces and later C++29 proposals must be distinguished; availability is a local library/toolchain question, not an established universal negative (S17, S58).

### 3.5 K-way merging (S18–S25)

- A loser tree costs ⌈log₂ k⌉ comparisons per output and has a predictable access path (S18).
- A binary heap's replace-top can **stop early** when the new key is still the smallest (S23). Bursty or low-interleave inputs may favor heaps.
- Real reports are mixed: large gains in Prometheus, where the heap baseline paid interface dispatch (S22); 3–13% and some regressions in PostgreSQL work in progress (S23); a win in a DBMS external sort (S21).
- d-ary heaps trade height against wider comparisons (S20).
- Galloping (S24) is a run-skipping optimization. It is safe here because positions are unique across partitions, so the boundary is strict (ARCHITECTURE §5.7).
- **Transfer** [D/H]: build an optimized inlined binary heap, a 4-ary heap, a loser tree, and a galloping wrapper, each with packed 64-bit keys; measure them against `std::priority_queue`; **presume no winner**.

### 3.6 Persistence and crash consistency (S13, S26–S31)

- Validate the tail of the newest segment by length and CRC, then truncate (S13, S26).
- Never assume appends are atomic or ordered (S28).
- fsync the file before rename, and fsync the directory after creating or renaming entries (S28, S31).
- Stop durable acknowledgments on fsync errors as a conservative policy [D]; retry/restart alone do not establish safe recovery after writeback faults (S29, S55).
- Use `pread`, not mmap, for measured recovery (S30). Measure physical reads with `/proc/self/io` `read_bytes` and block-device statistics (S31).
- Attempt file-page eviction with page-aligned `posix_fadvise(DONTNEED)` after successful synchronization; record the immediate `mincore` residency snapshot. This is not a guarantee of cold device/controller caches (S31, S56).

### 3.7 Tree partitioning and workload-aware layout (S33–S39)

- The article's store layouts are **connected partitions of the topic tree** (I-4).
- Known results (S34): minimum count under a weight bound is linear on trees [Kundu–Misra]; min-max p-partition is polynomial on trees; but **bounded partitions minimizing an edge cost are NP-hard even on trees**, with pseudo-polynomial DPs.
- Our workload-aware objective (bilinear in store bytes × reader weight) is a different problem. The plan claims exactness only for the model and algorithms in ARCHITECTURE §6 (enumeration, and a DP exponential only in the number of consumer classes per partition), and **no** general polynomial-time result.
- Workload-aware data-skipping layouts (S37, S38) and drift-aware layouts (S39) are **analogies**, not direct prior art for topic-tree store splitting.

### 3.8 Benchmarking, testing, environment (S32, S41–S45, S47, S48)

**Environment probe (S47), 2026-10-16:**
- HP laptop, Intel i5-1235U (hybrid): P-cores are CPUs 0–3 (SMT pairs 0/1 and 2/3, up to 4.4 GHz); E-cores are CPUs 4–11 (up to 3.3 GHz). L2 6.5 MiB, L3 12 MiB.
- 14 GiB RAM; NVMe (KIOXIA) on ext4 with 30 GB free.
- Ubuntu 26.04, kernel 7.0.0-38. GCC 15.2. Clang 21.1.8 with ASan/UBSan/libFuzzer runtimes. CMake 4.4. No ninja, hyperfine, or fincore.
- **`perf` 7.0.14 with `perf_event_paranoid=4`:** even software events failed for an unprivileged user.
- Governor `powersave`, turbo enabled, SMT on. AVX2 and SSE4.2 present.
- valgrind 3.26; googletest 1.17.0 installed; numpy 2.4.6 and matplotlib 3.11.1 present; pandas, scipy, pyarrow, and hypothesis absent. `/proc/self/io` and `iostat` available.

**Protocol inputs:**
- LLVM's tips assume non-hybrid CPUs (S41), so the plan adapts them by pinning to one P-core and keeping its SMT sibling idle.
- Google Benchmark: repetitions, random interleaving, JSON output (S42).
- Coordinated-omission-safe open-loop measurement (S43).
- Measurement bias and repetition planning (S44).

### 3.9 Developments in 2025–2026 that affect the plan

- The article and its context are newer than most other sources: the intern round-up (S02, 2026-09-30) and the Antithesis-on-Aria post (S04, 2025-12-03).
- Nasdaq posted **2025 and 2026 full-day samples** (S08), and the spec PDF was regenerated in 2024 (S05).
- Binance moved spot data to µs timestamps (2025) and published **CC BY-NC-SA terms on 2026-08-26** (S09, S10).
- PostgreSQL's loser-tree discussion ran Dec 2025 to May 2026 (S23).
- 2026 hazard-pointer follow-up proposals explicitly target C++29; they are not evidence of local standard-library availability (S58).
- libFuzzer is in maintenance mode (S45).
- Google Benchmark v1.9.5 remains the chosen documented baseline. HdrHistogram_c 0.12.0/0.12.1 release notes contain correctness fixes; optional T4 should review/pin 0.12.1 rather than assume older means safer (S48, S57).
- LayoutPilot (VLDB 2026) and OREO (2024) work on workload-aware and drift-aware layouts (S39).
- No 2024–2026 work on topic-tree store splitting for message buses was found in a bounded search. That is **not** a claim of novelty.

### 3.10 Directly applicable vs analogy

| Directly applicable | Useful analogy only |
|---|---|
| ITCH spec, BinaryFILE, Nasdaq samples (S05–S08) | Linux ring buffer (S12) |
| Article design facts (S01, S02, S04) | Qd-tree, data skipping, OREO, LayoutPilot (S37–S39) |
| Aeron padding and positions (S11); Kafka recovery (S13) | Prometheus and PostgreSQL merge experience (S22, S23), since workloads differ |
| Sanders loser tree (S18); CPython galloping (S24) | DSN 2003 durable subscriptions (S40) |
| Crash consistency (S28, S29, S31); mmap pitfalls (S30) | Demaine et al. adaptivity (S25) |
| Tree-partition complexity (S33–S35); Everett (S36) | OxCaml unboxed types (S46) |
| Benchmark and coordinated-omission method (S41–S44); sanitizers and fuzzing (S45) | |

---

## 4. Paper analyses

"Depth" says what was actually read. Everything not listed was not read.

**Sanders 2000, Fast Priority Queues for Cached Memory (S18).** Depth: abstract, the §2 loser-tree paragraph, Appendix A.5 code.
- *Problem:* priority queues that are cache-efficient.
- *Assumptions:* comparison keys; k-way merge of sorted sequences.
- *Method:* sequence heaps built on loser-tree k-way merging; external-memory ideas applied to caches.
- *Evaluation:* at least 2× faster than tuned binary and 4-ary heaps for large inputs (late-1990s machines).
- *Limitations:* old hardware; a priority-queue setting, not filtered posting-list merges with random record fetches.
- *Transfer:* loser-tree layout (leaf-to-root replay, losers stored at internal nodes, sentinel for exhausted inputs); the point that access paths are predictable; inline key + index entries.

**Polyntsov et al. 2022 (S21).** Depth: abstract and conclusion lines.
- *Problem:* which structure to use for the merge step of an external sort.
- *Method:* naive, binary heap, and loser tree inside one DBMS.
- *Evaluation:* the loser tree was best (84 runs).
- *Limitations:* external sort with I/O in a single system; no inputs with long runs.
- *Transfer:* worth implementing a loser tree. It does not decide our case.

**Hart, McKenney, Demke Brown 2006 (S15).** Depth: abstract and introduction.
- *Problem:* the cost of memory reclamation for lockless structures.
- *Method:* QSBR, EBR, and hazard pointers in one microbenchmark framework.
- *Result:* no globally optimal scheme; it depends on structure, workload, and environment.
- *Limitations:* 2006-era multiprocessors.
- *Transfer:* R4 compares generation-validated reads against EBR empirically, and the core avoids concurrency.

**Fraser 2004, §5.2.3 (S14).** Depth: section text.
- *Method:* garbage goes onto per-epoch limbo lists; the list from two epochs back is reclaimed once all threads have observed the current epoch.
- *Limitation:* one stalled thread blocks reclamation.
- *Transfer:* the candidate for R4 block reuse, alongside generation-validated reads.

**Pillai et al. 2014, ALICE (S28).** Depth: parts of §1–2.
- *Problem:* crash-consistency bugs in application update protocols.
- *Method:* BOB measures file-system persistence properties; ALICE explores crash states.
- *Findings:* properties vary widely; atomic appends are not provided by some modes; ordering assumptions fail; 60 vulnerabilities across 11 applications (abstract).
- *Limitations:* 2014 file-system versions.
- *Transfer:* CRC on every record; no reliance on append atomicity; the fsync → rename → directory-fsync protocol; crash-state tests (R1).

**Rebello et al. 2020 (S29).** Depth: abstract and introduction.
- *Problem:* how applications handle fsync failures.
- *Findings:* file systems mark pages clean after a failure, and application strategies are insufficient.
- *Transfer [corrected v1.1]:* fail-stop is a conservative project policy, not a proved recovery procedure for arbitrary I/O failure. Distinguish EINTR from writeback EIO; a retry after EIO is not evidence that data became durable. A process restart alone does not prove a valid durable state.

**Crotty, Leis, Pavlo 2022 (S30).** Depth: abstract and problem headings.
- *Problem:* mmap as a buffer pool in a DBMS.
- *Findings:* problems with transactional safety, I/O stalls, error handling through SIGBUS, and performance (TLB shootdowns, eviction).
- *Transfer:* explicit `pread` with large buffers for recovery reads; physical I/O measured, never inferred from mmap.

**Buchin & Selbach 2022 (S34), with Kundu–Misra 1977 (S33) and Lukes / Johnson–Niemi (S35) seen through it.** Depth: abstract and §1.1.
- *Problem:* (l,u)-partitions of weighted trees and cactus graphs into connected clusters.
- *Landscape (from §1.1):* MinNum under an upper bound is linear on trees; edge-cost minimization under a weight bound is NP-hard on trees with pseudo-polynomial DPs; min-max p-partition is polynomial on trees.
- *Transfer:* (1) the KM greedy is exact for *its* problem (minimum store count under a byte bound with forced singletons; ARCHITECTURE §6.6); (2) do not expect a general polynomial algorithm for workload-weighted objectives; our DP is exponential in the number of consumer classes, not in tree size.

**Everett 1963 (S36).** Depth: abstract.
- A minimizer of J + γ·|stores| is optimal for the budget equal to its own store count; budgets between hull points may have a duality gap.
- *Transfer:* global allocation of the store budget across partitions (ARCHITECTURE §6.5).

**Qd-tree 2020 (S37), Sun et al. 2014 (S38), OREO 2024 / LayoutPilot 2026 (S39).** Depth: abstract or search-level.
- Workload-aware layouts that minimize blocks read; the Sun et al. formulation is NP-hard and solved heuristically; drift degrades fixed layouts.
- *Transfer:* define the objective from a stated workload; test robustness across windows (L6). These are analogies only.

**Mytkowicz et al. 2009; Kalibera & Jones 2013 (S44).** Depth: abstracts.
- Bias from incidental setup such as link order and environment size; plan repetitions at each level of variation.
- *Transfer:* record the build and environment; repeat at process level; randomize interleaving; report uncertainty.

**DSN 2003 durable subscriptions (S40).** Depth: abstract.
- Persisted filter information avoids re-filtering on catch-up; early release reclaims storage from misbehaving subscribers.
- *Transfer:* prior art for index-assisted catch-up; the FellBehind policy.

---

## 5. Not verified, and research still needed

| Item | Status | Resolved by |
|---|---|---|
| Uncompressed size and message counts of the 2019-12-30 file | Unknown; modulo/per-member ISIZE gives no finite candidate list | P1.2 full streaming count with decompressor errors checked |
| Actual skew, family mix (deletes vs executions), interleaving, partition-tree sizes | Not measured | L1 (P1.7) |
| Kundu–Misra full text | Publisher abstract and secondary account checked; full text unread | Analytical argument plus future brute-force check V30 |
| Knuth §5.4.1 | Not inspected | Not needed (S18 suffices) |
| Hardware counters on this laptop | Blocked at paranoid level 4 | DEC-2 |
| Nasdaq sample-data terms | None found | You, before any publication |
| Whether `perf stat --control` works on perf 7.0 with hybrid PMUs | Unchecked | P0.4 |

## 6. Research refresh and design audit — 2026-10-17

### 6.1 Scope and actual evidence

Reviewed all seven planning files against MASTER_PROJECT_PROMPT.md and split independent reviews across core algorithms, layout optimization, and data/validation. The reference PDF's already-read account is unchanged. Bounded searches covered recent primary merge discussions, 2026 layout/drift/storage papers, current tool release notes, WG21 proposals, and current official specifications. Sources below were inspected on **2026-10-17 (Asia/Kolkata)**. New-to-this-plan does not mean published overnight; no claim of exhaustive literature coverage is made.

No application code, optimizer, implementation tests, benchmarks, package installs, system changes, or full-dataset downloads were performed. Arithmetic/counterexamples in this review are analytical reasoning. Original dated probes remain original evidence; current listing/spec checks do not revalidate yesterday's file-byte or checksum-404 probes.

### 6.2 Additional evidence ledger

| ID | Source / publication date | Inspected on refresh | Supported consequence / limit |
|---|---|---|---|
| S49 | [PostgreSQL follow-up](https://www.postgresql.org/message-id/CABPTF7WRcm=y-2dRs-vK3SLyCVyxLvUyTDQ-9%2B-OLoBYAwG%2B=Q@mail.gmail.com), 2026-05-25; [Graefe/Do EDBT paper](https://openproceedings.org/2023/conf/edbt/3-paper-42.pdf), 2023 | Entire message; EDBT abstract/intro/§3. Linked [ACM DOI 10.1145/3778176](https://dl.acm.org/doi/10.1145/3778176) full text returned 403 and was not read | Continue regression/cutoff experiments. Offset-value coding targets richer comparisons; no demonstrated need for scalar log-position keys. Thread is not proof of adopted code or speedup. |
| S50 | Liu/Borovica-Gajic, *Toward Drift-Aware Database Benchmarking*, [PVLDB 19(8):1818–1825](https://www.vldb.org/pvldb/vol19/p1818-liu.pdf), 2026, DOI 10.14778/3811243.3811254 | Abstract, taxonomy §2, DriftSpec §3/example, §4 overview | Separate data distribution drift from query/subscription drift, specify temporal shape and seeds. Database setting; optional methodology, no new dependency. |
| S51 | Liu et al., *Workload-Aware Incremental Reclustering in Cloud Data Warehouses* (WAIR), [arXiv v2](https://arxiv.org/abs/2602.23289v2), 2026-03-16; PACMMOD 4(3), article 250, June 2026, DOI 10.1145/3802127 | Abstract, introduction, §3 definitions; no full proof/evaluation replication | Optional disk-roadmap analogy for limited reorganization work. Range-boundary micro-partitions differ from connected topic stores; no theorem transfer. |
| S52 | Shawger et al., *XLL: Cross-Layer Logging for Data Deduplication in Consensus-Based Storage*, [NSDI 2026 paper](https://www.usenix.org/system/files/nsdi26-shawger.pdf), May 2026 | Abstract, §1, write-amplification discussion/§5.1; not full implementation | Count payload writes across WAL/pack layers in R3. TiKV/consensus design is not the tiplog core; its gains are not targets or predictions. |
| S53 | Liu/Kipf/Borovica-Gajic, *LayoutPilot: A Lakehouse Physical Design Advisor*, [final PVLDB 19(12):4578–4581](https://www.vldb.org/pvldb/vol19/p4578-liu.pdf), 2026, DOI 10.14778/3827998.3828070 | Four-page demo: abstract/metadata, system description, §2.4 verification and §3 | Compare recommended/ranked candidates against observed measurements. Use final publisher metadata, not the author manuscript's placeholder DOI/pages. Analogy, not exact optimization evidence. |
| S54 | [RFC 1952](https://www.rfc-editor.org/rfc/rfc1952), May 1996, §§2.2/2.3.1 | Member structure and ISIZE definition | ISIZE is one member's uncompressed size modulo 2³². Concatenated members are allowed; full-stream size needs actual counting. |
| S55 | [fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html); S29 ATC 2020 paper | DESCRIPTION/ERRORS; paper §5 observations 7–8 and conclusion | Separate interruption from writeback failure, stop acknowledgments, and scope recovery guarantees to tested failure models. |
| S56 | [Perf security](https://docs.kernel.org/admin-guide/perf-security.html), [Intel hybrid perf](https://raw.githubusercontent.com/torvalds/linux/master/tools/perf/Documentation/intel-hybrid.txt), [perf-stat](https://man7.org/linux/man-pages/man1/perf-stat.1.html); [fadvise](https://man7.org/linux/man-pages/man2/posix_fadvise.2.html), [mincore](https://man7.org/linux/man-pages/man2/mincore.2.html), [process I/O](https://man7.org/linux/man-pages/man5/proc_pid_io.5.html) | Access-control and control-ack excerpts; full short hybrid note; relevant advice/residency/accounting sections (man-pages 6.19, 2026) | Probe actual PMU/events and record scheduling/scaling. Residency is a snapshot; fadvise is advice. Device-wide I/O includes other traffic. |
| S57 | HdrHistogram_c [0.12.0](https://github.com/HdrHistogram/HdrHistogram_c/releases/tag/0.12.0) and [0.12.1](https://github.com/HdrHistogram/HdrHistogram_c/releases/tag/0.12.1) release notes; Oct 2/16 on release rendering | Release descriptions, including bounds/UB/decoding and percentile fixes; code not audited | Review/pin 0.12.1 in optional T4. Empty histograms remain no-data cases. Release-year metadata from old S48 was not independently API-reproduced. |
| S58 | WG21 [P3427R7](https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2026/p3427r7.pdf), 2026-07-24; [P3428R4](https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2026/p3428r4.pdf), 2026-06-10; [atomic_ref draft](https://eel.is/c++draft/atomics.ref.generic) | First proposal history/interface/motivation; entire six-page second proposal; atomic_ref lifetime/alignment/access clauses | Follow-ups target C++29, unlike base C++26 draft interface. Atomic readers alone do not validate concurrent byte overwrite. C++20 core unchanged. |
| S59 | Aeron, [Persistent Subscriptions: Managing live and replay transitions](https://aeron.io/software-release/persistent-subscriptions-replay-to-live-transitions/) and [2026 meetup account](https://aeron.io/other/aeron-community-meetup-whats-new-march-2026/) | Main article text, especially handoff/recovery sections; 1.51 release context. Exact article publication day not exposed/verified | Delayed live attachment, convergence and repeated fallback deserve explicit R2 cases. Two underlying subscriptions have resource costs. No Aeron dependency or transferred benchmark gain. |
| S60 | Adam Yi, [How recurring network maintenance exposed 6 bugs](https://blog.janestreet.com/how-recurring-network-maintenance-exposed-6-bugs/), 2026-10-02 | Introduction and outage/retry/resource-limit sections; linked patches not audited | R5 should test outstanding-attempt bounds, real cancellation and connection/FD counts after repeated outages. Network/DNS story is roadmap context, not a new core feature. |
| S61 | Stanislaw Maczka, [Flex Model: an event-driven feature engineering system](https://blog.janestreet.com/flex-model-an-event-driven-feature-engineering-system/), 2026-10-13 | Main article, especially history versus coalescing, handler/eval separation and performance discussion; no internal code inspected | Equal-valued events remain distinct history. Add replay/consumer regression reasoning; later R6 can reuse identical feature-update logic for reference/replayed streams. No feature-DAG framework added. |

### 6.3 Decisions strengthened by this review

**Immediate corrections, not optional features.** Replace the late-seal FIFO with ordered expiry; align replay errors/checkpoints across modes; enforce safe ring/key/id limits; account for all pool memory. These are requirements of the existing core contract. ARCHITECTURE §13 and VALIDATION §13 give the amendments and planned regression cases.

**Layout evidence.** The class-mask reformulation is sound for the declared nonnegative full-window model; it does not suffer the state-loss objection to a count-only DP. Add rational scaling, checked arithmetic, a capped-convolution argument, finite threshold searches, correct nonnegative Lagrangian bounds, and per-workload exact coverage. S34's different NP-hard problem is not a hardness theorem for M-store. Publisher abstracts for [Kundu–Misra](https://epubs.siam.org/doi/10.1137/0206012), [Johnson–Niemi](https://pubsonline.informs.org/doi/10.1287/moor.8.1.1), and [Everett](https://pubsonline.informs.org/doi/10.1287/opre.11.3.399) were rechecked; full texts remain unread. S33 publication is March 1977, not its 2006 online posting.

**New study design, optional scope preserved.** DriftBench supplies a useful taxonomy; define separate volume-skew and subscription-popularity changes in L6. OReO (S39, re-read abstract/§III-A–C and relevant discussion) and WAIR motivate accounting for rewrite cost before favoring repeated re-layout. LayoutPilot motivates testing whether the modeled best layout is fastest in R3. These do not add learned layouts, SQL engines, or external research frameworks to the core.

**No automatic technology migration.** Keep the documented Google Benchmark v1.9.5 baseline. Review the optional histogram pin because its newer release fixes correctness issues. Keep C++20; verify actual library support only if an authorized roadmap phase needs it.

**Recent engineering articles.** Screened Jane Street's current archive through its October13 entry and Aeron's 2026 release discussion. S61 strengthens event-preservation semantics; S59 strengthens later recovery/handoff tests; S60 supplies later network failure scenarios. These are useful additions without changing the core product. A repeated price or unchanged derived state does not authorize dropping an event from this retained log. Release/vendor descriptions are supporting design evidence, not independent performance measurements.

### 6.4 Read-only environment refresh

Observed on 2026-10-17: GCC 15.2.0, Clang 21.1.8, CMake 4.4.0, perf 7.0.14, paranoid=4. Topology/sysfs still identify CPU 2 as a P-core with sibling 3. Current `python3` resolves to Python **3.14.4**; installed metadata reports numpy **2.3.5**, matplotlib **3.11.0**, pytest **9.0.2**, pandas **3.0.3**, and no hypothesis/scipy/pyarrow. The bare `python` shim is not a reliable project command. About 31.4 GB disk was free at observation. These differ from the historical S47 Python/package entries; do not reuse old pins without compatibility checks. No packages/settings were changed and counters were not collected.

### 6.5 Reconfirmed facts and outstanding limits

- Official Nasdaq listing still has the selected 2019 file and newer 2025/2026 samples. BinaryFILE length/terminator semantics were re-read; no full stream or fresh byte-range probe was performed.
- Official Binance README confirms the **spot-only** µs transition, checksums, and possible archive updates. Dataset terms were re-read; code licensing is separate.
- Exact size/count/skew, actual compiler output, merge winner, pool behavior, optimizer agreement and coverage, counters, disk cost parameters, and performance remain implementation-phase measurements.

## 7. Phase 0 just-in-time source inspection — 2026-10-17

P0 reuses S32/S41/S42/S45/S47/S48/S56 and DD-15/DD-18. No paper algorithm or Jane Street implementation detail is needed for this tooling phase. The earlier article/PDF and paper read-depth limitations remain unchanged. No unavailable Aria code is inferred or reused; P0 plumbing is independently written.

| Original material actually inspected | Sections/revision and result | P0 consequence |
|---|---|---|
| [Git command reference](https://git-scm.com/docs/git) | `--git-dir`, `--work-tree` and corresponding environment variables; live documentation accessed 2026-10-17. Local Git 2.53.0 verified separately. | Explicit writable `.tiplog-git` and original worktree preserve managed `.git`; `scripts/git.sh` makes this layout usable. |
| [CPython 3.14 venv](https://docs.python.org/3.14/library/venv.html), [pip freeze](https://pip.pypa.io/en/stable/cli/pip_freeze/) | Creating environments, isolated site-packages, explicit interpreter invocation and non-portability; freeze description/default bootstrap omissions. Live documentation renders Python 3.14.8/pip 26.2.1, distinct from tested Python 3.14.4/pip 25.1.1. | Create isolated `.venv` with `/usr/bin/python3`; pin complete installed project dependencies and record interpreter/pip separately. Freeze is a version snapshot, not a cross-platform lockfile. |
| [NumPy 2.3.5](https://pypi.org/project/numpy/2.3.5/), [Matplotlib 3.11.0](https://pypi.org/project/matplotlib/3.11.0/), [pytest 9.0.2](https://pypi.org/project/pytest/9.0.2/) | Release metadata/Python compatibility and binary distributions; NumPy/Matplotlib CPython 3.14 Linux wheel listings inspected. Installed wheels then exercised directly. | Keep the refreshed top-level versions; resolve/freeze their actual compatible transitive dependencies. NumPy arithmetic and Agg PNG rendering pass in the isolated venv. No optional scientific stack added. |
| [Benchmark CMake at `192ef10025eb2c4cdd392bc502f0c852196baa48`](https://github.com/google/benchmark/blob/192ef10025eb2c4cdd392bc502f0c852196baa48/CMakeLists.txt); [GoogleTest CMake at `52eb8108c5bdec04579160ae17225d66034bd723`](https://github.com/google/googletest/blob/52eb8108c5bdec04579160ae17225d66034bd723/CMakeLists.txt) | Approved v1.9.5/v1.17.0 tag references resolved; relevant project/options/test/library definitions and license files inspected in original archives. Exact inspected ranges, hashes and commands in [build-source notes](../../results/p0/build-sources.md). | Fixed commit archives with SHA-256; exact system GTest preferred, tested pinned fallback; upstream benchmark tests/downloads disabled. No benchmark run or source adaptation. Original licenses stay in dependency archives/trees. |
| [CMake FetchContent](https://cmake.org/cmake/help/v4.4/module/FetchContent.html), [presets](https://cmake.org/cmake/help/v4.4/manual/cmake-presets.7.html); LLVM [ASan](https://clang.llvm.org/docs/AddressSanitizer.html), [UBSan](https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html), [libFuzzer](https://llvm.org/docs/LibFuzzer.html) | FetchContent Overview/Declare/MakeAvailable; configure/build/test schema; sanitizer compile/link/runtime usage; fuzzer vs fuzzer-no-link. Live CMake docs render 4.4.4; executable tested is 4.4.0. | Four Makefiles presets; instrument normal fuzz-preset plumbing without a fake fuzz target. Sanitizer runtime options remain enabled; sandbox ptrace incompatibility resolved by authorized execution outside tracing, not weakened checks. |
| S32/S56 [perf security](https://docs.kernel.org/admin-guide/perf-security.html), [hybrid note at Linux v6.17](https://raw.githubusercontent.com/torvalds/linux/v6.17/tools/perf/Documentation/intel-hybrid.txt), [perf-stat](https://man7.org/linux/man-pages/man1/perf-stat.1.html); S41 [LLVM benchmarking](https://llvm.org/docs/Benchmarking.html) | Access-control sections; entire short hybrid note at named tag; event/no-scale/CSV/control-ack semantics; LLVM Introduction/General/Linux/Intel. [Detailed reading limits](../../results/p0/environment-sources.md). No implementation code copied. | `cpu_core` membership + actual CPU pin/frequency diagnostics; failed counter probes retained. DEC-2 fallback, no privileged setting changes or hardware-counter claims. No assumption that upstream paranoid level alone proves access. |

Actual environment/import/build outcomes are linked from [PROGRESS](PROGRESS.md); they do not validate later replay/index/optimizer invariants. New sources did not change scope, dependencies beyond the planned frozen tooling, semantics, or phase acceptance criteria.

## 8. P1 source inspection and measured input facts — 2026-10-17

The user jointly authorized P1–P5 after P0. P1 reuses S05–S09/S54 rather than collecting a new open-ended bibliography. [Python source ledger](../../results/p1/python-sources.md) and [independent C++ ledger](../../results/p1/cpp-sources.md) record original Nasdaq ITCH message tables, the complete two-page BinaryFILE document, actual revision/read depth and implementation/test symbols. ITCH's latest inspected revision remains 2023-04-28; O is supported in synthetic parser tests even though the input is from 2019. No third-party parser code or unpublished Aria implementation was copied.

[Acquisition-source notes](../../results/p1/acquisition-sources.md) record the official listing, actual HTTP metadata and inspected original curl options. The current source still has 3,524,013,057 compressed bytes. Complete download, gzip validation and SHA-256 identity are saved in [data/manifest.json](../../data/manifest.json). The source remains local; only aggregate evidence is tracked.

**Measured, not inferred from ISIZE:** independent full-stream C++ framing and `gzip | wc -c`, with decompressor failures propagated, agree on **8,251,407,909 uncompressed bytes**. The C++ walker observes **268,744,780 messages**, **18 present message types**, **8,907 locates**, and **0 timestamp inversions**. [Raw counts](../../results/data/itch_20191230_counts_cpp.json), [consistency evidence](../../results/p1/cpp-full-day-consistency.json). Python reconciliation and skew are recorded only when actually executed in PROGRESS.

**Source limitation:** the downloaded gzip is intact and ends on a complete ITCH frame, but has no zero-length BinaryFILE terminator. It is explicitly `incomplete=true` under S06/V02. This does not establish session completeness, and no terminator is synthesized. The plan already specifies this outcome; neither a new acquisition day nor a scope/semantic amendment is introduced. Conversion must preserve the flag and original event order.

The independent P1–P5 [source/requirements audit](../../results/p1/review-sources.md) also re-inspected targeted Aeron/Kafka/Sanders/merge-discussion/Benchmark documentation for later authorized mechanisms. Its exact sections and pinned/moving-document limitations are recorded. Those design preparations do not claim any later phase code or gate has completed. Existing abstract-only/inaccessible-paper limitations remain unchanged.

**Fuzz execution correction (S45):** original LLVM `llvmorg-21.1.8`, commit `2078da43e25a4623cab2d0d60decddf709aaea28`, was inspected in `FuzzerFlags.def` (`max_len`, `len_control`, timing/final-stat flags) and `FuzzerLoop.cpp` (seed loading, length control, loop timing and final statistics). [Exact sections and execution notes](../../results/p1/fuzz-segmented-notes.md). A host wall-clock discontinuity made earlier elapsed-time reports insufficient. The project runner therefore checkpoints successful segments and verifies at least 1,800 accumulated monotonic seconds, preserving corpora, full length range, sanitizer/leak checks and final statistics. The accepted F1/F2 binaries, logs, totals and corpus hashes were independently rechecked in [fuzz gate verification](../../results/p1/fuzz-gate-verified.json). No LLVM code was copied and no phase acceptance threshold was reduced.

**P1 review corrections:** the F2 real-prefix seed stays in ignored local storage with an [identity manifest](../../results/p1/fuzz-F2-real-seed.json). F02's CCDF now groups equal volumes before computing survival probability, so every symbol with volume equal to x contributes to P(volume ≥ x). These are validation/plotting fixes, not changes to routing, trace semantics or scope. [Finding-to-code/check map](../../results/p1/traceability.md).
- No directly applicable new replacement for this topic-tree DP was established. This is a bounded search outcome, not evidence of novelty or a claim that every relevant publication was found.

## P4 execution-method confirmation — 2026-10-18

Finding28's four-byte-entry warning affects actual accounting: portable index gauges exactly report fixed metadata/deltas, sealed flags, heap/list capacities, control storage, live/stale/open/sealed/free slots and high-water. Allocator overhead is separately observed through a supported fresh single-thread glibc2.43 `mallinfo2` process boundary. [Original material, method and actual observations](../../results/p4/memory-sources.md) records the inspected local header and official manual §3.2.3.10. The signed allocator-minus-reserved difference includes rounding/retained allocation effects and is not per-object headers or RSS. No allocator settings, architecture, dependency, scope or acceptance criterion changed.

P4 also corrected the randomized campaign's declared partition bound from39 to41: compiling a nonexistent exact term interns two extra ancestor partitions. [Engine traceability](../../results/p4/engine-sources.md) records the independently sufficient generic16 pool sizing. The engine's reported tail is never substituted for oracle retention; true pressure is checked against prior hand arithmetic and golden replay bytes. Actual P4 completion still depends on its timed F3 gate in PROGRESS.


## P5 bounded implementation reading — 2026-10-18

P5 reuses the saved S18/S23/S49/S42 findings with targeted original reading,
not a new research sweep. [Merge source ledger](../../results/p5/merge-sources.md)
records the actually inspected Sanders §2 and AppendicesA.2/A.5, original
short merge discussions, installed GCC15.2 StdPQ/heap implementation ranges
and pinned Google Benchmark1.9.5 revision192ef10025eb2c4cdd392bc502f0c852196baa48.
S20 full text remains uninspected; unavailable S22 pages and S49 linked ACM
text are not claimed read. Quad padding is independently checked geometry,
loser replay is an independent guarded tournament algorithm, and no code or
speedup is attributed to unavailable Aria internals.

Pinned Benchmark source confirms its random interleaving uses internal entropy
without an exposed replay seed, and explicit Iterations would override adaptive
minimum-time calibration. The harness therefore preserves actual invocation
order, input seed and raw repetitions while keeping adaptive iteration counts.
[Method and reading boundaries](../../results/p5/pilot-method.md). A read-only
[generated-code review](../../results/p5/assembly-review.json) confirms the
actual record touch feeds the sink and records representative compiler choices;
it makes no branch-free, cache-benefit or performance-ordering claim.

The [installed Valgrind3.26 original manual inspection](../../results/p5/cachegrind-sources.json)
records exact sections and document identity. In this version cache and branch
simulation must be enabled explicitly. The reduced fallback will retain whole
program instruction and **simulated** cache/branch counts, including setup;
these are neither modern-PMU observations nor isolated hot-loop attribution.
This reading changes no approved dependency, semantics, scope or gate. Actual
checks and pending/complete status remain in PROGRESS and the P5 phase gate.
