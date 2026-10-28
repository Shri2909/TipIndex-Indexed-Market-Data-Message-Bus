# P5 merge kernels and M1 source-to-validation record

Accessed **2026-10-18 (Asia/Kolkata)**. P4's saved gate passed before this
implementation. This is Tier B P5 work; galloping, P6 calibration and broad
performance conclusions remain outside this phase. Implementations are original
project code. No external implementation was copied, and no unavailable Aria
implementation detail is asserted.

## Material actually inspected

- S18, Peter Sanders, [*Fast Priority Queues for Cached Memory*](https://ae.iti.kit.edu/documents/people/sanders/papers/spqjea.pdf):
  original extracted PDF text, **§2 loser-tree paragraph, printed page 5**;
  **Appendix A.2, printed page 20**; **complete Appendix A.5, printed pages
  23–24**. This is targeted reading, not complete-paper inspection. The paper
  describes tournament losers, the extra winner node and winner-path replay;
  it motivates aligned child groups. We independently implement bottom-up
  initialization, packed identities, power-of-two padding and guarded exhaustion.
  Its older-machine results establish no modern performance ordering here.
- S23, [Linnakangas, 2025-12-03](https://www.postgresql.org/message-id/28f47336-84e2-445e-8216-d1ce7d3ddc3e%40iki.fi)
  and [Naylor, 2025-12-08](https://www.postgresql.org/message-id/CANWCAZZ6KpsL%2BoEJFyQxqMMNv7FHRxPqUGafn9sqJzg_BmH5Qg%40mail.gmail.com):
  both complete short original messages, including their quoted context. These
  are review discussions asking for adverse inputs and precise comparison
  accounting, not an adopted PostgreSQL implementation or reproduced speedups.
- S49's prior original-message inspection and limitations are retained in
  [P1 review sources](../p1/review-sources.md). Its linked ACM full text was not
  reopened or claimed inspected. No offset-value kernel enters this scope.
- S20 LaMarca–Ladner full paper remains uninspected. Quad's three-word padding
  geometry is our directly checked address calculation, informed by the targeted
  S18 Appendix A.2 reading; it is not attributed to unavailable text.
- S22's Prometheus PR original page and API endpoint were attempted through
  the web reader during this P5 pass and were unavailable. Earlier research
  reading limits remain in force. We make no new PR-code or reproduced-result
  claim; the approved identical-input/inlined-baseline requirements independently
  govern this implementation.
- Installed GCC **15.2.0, Ubuntu 15.2.0-16ubuntu1**:
  `/usr/include/c++/15/bits/stl_queue.h` **lines 830–896**, `push`/`pop`;
  `/usr/include/c++/15/bits/stl_heap.h` **lines 220–250**, `__adjust_heap`.
  This inspects the actual system library used for the StdPQ baseline. Exact
  file identities are saved in `merge-source-identities.json`; no library code
  was copied into the custom heaps.
- S42 Google Benchmark **v1.9.5**, revision
  `192ef10025eb2c4cdd392bc502f0c852196baa48`: original local
  `docs/user_guide.md` **runtime/reporting lines 240–270, preventing optimization
  and statistics lines 1084–1174**; complete `docs/random_interleaving.md`;
  `src/benchmark.cc` **State constructor lines 180–225, timing/error methods
  lines 253–317, loop start/finish lines 319–347 and random interleaving
  lines 440–490**. This confirms setup before the state loop is excluded,
  reset/init can be paused, and skipped states must not be resumed. The pinned
  library seeds its interleaving internally from `random_device`; that entropy
  seed is not exposed. We preserve input seed and actual invocation order.
  Additional prior targeted reading/hashes are in
  [P4 method reading](../p4/p5-method-reading.json).

Jane Street's published observations remain the separately attributed source
of the project's motivation. These four independent kernels, their padding,
synthetic distributions and benchmark outcomes are our own work, design choices
and hypotheses. No published gain is transferred to this implementation.

## Finding → contract → task → code → validation → executed evidence

| Source/finding | Decision/invariant and task | Code | Validation | Executed evidence |
|---|---|---|---|---|
| v1.1 representation correction | Unique packed `(position,id)` word, positions below 2^51, k≤65535, IDs≤65534, all-ones exhaustion; P5.1/P5.2 | `merge::pack`, `position`, `cursor_id`, `detail::validate_heads` | `MergeKeys.V35BoundarySentinelIdentityAndAlignmentGuards`; near-limit and maximum-k V21 cases | Strict syntax check passed; central runtime gate results are appended below when executed |
| S23 adverse-input and baseline concerns | Real StdPQ pop+push; separate inline early-exit BinHeap; P5.2 | `StdPQ::replace_top`, `BinHeap::sift` | V21 independent balanced `std::merge` reference; uniform/skew/long-run/empty/singleton cases | Same evidence status as above |
| S18 tournament replay | Preserve original winning leaf's fixed update path even when candidate identity changes; power-of-two sentinel padding; P5.2b | `Loser` constructor/`replace_top` | Non-power-of-two and initially empty leaves; staggered exhaustion; explicit identity-changing replay test | Same evidence status as above |
| S18 alignment motivation + independent address calculation | 64-byte physical allocation with either 3 or 0 prefix words; measure the variants without assuming a cache benefit; P5.2b | `Quad` constructor/`sift` | `MergeQuad.V21AlignedAllocationAndThreeWordPaddingGeometry`; all functional lists also tested with pad0 | Same evidence status as above |
| C++ ownership/lifetime review | Moved-from Quad and Loser are empty and guarded; no stale scalar count can index moved storage; P5.2b | explicit move constructor/assignment in `Quad`, `Loser` | Quad move geometry case and `MergeLoser.V21MovesTransferOwnershipAndLeaveEmptySource` | Same evidence status as above |
| VALIDATION §§6.1/7, S42 timing/sink semantics | Identical deterministic lists and protected all-output hash; setup/reset/init excluded; full matrix exposed; P5.5 | `make_input`, `merge_once`, `run`, `add_profile` in `bench/micro/merge_bench.cpp` | `--verify-only`, independent sorted-union count/hash; raw M1 pilot is a later root-owned check | Syntax passed; functional and timed checks remain pending until recorded |
| M1-touch footprint review | Fully write 1 GiB with deterministic nonconstant words, load 8 B at stride-256 positions; record actual span/line/read-byte footprint; P5.5 | `make_input`, `touch_value`, `metadata`, `merge_once<true>` | Same output/hash across kernels including touched values; metadata checks | Pending root-owned functional/pilot checks |
| S42 skipped-state precondition | Record hash/count failure without resuming skipped timing; P5.5 | `run` error exit after `SkipWithError` | Source inspection of pinned State API, normal functional/pilot checks; failure remains a retained run outcome | Syntax passed; no synthetic performance failure has been induced |

The kernel test reference uses a balanced sequence of `std::merge` calls; it
does not reuse a tested priority structure. Benchmark expected output uses a
separate sorted union and folds every emitted key, plus every touch value.
M1 runs use concrete template dispatch outside the output loop. No optional
galloping or per-output interface dispatch is introduced.

## Executed checks and continuation

- `merge-syntax-20261018T154811.314325Z.json` / `.log`: strict GCC C++20 syntax
  check of kernel source, V21 unit source and M1 source, **passed**, exit 0,
  no compiler diagnostics.
- Release/sanitizer V21 execution, reduced diagnostic verification, full-size
  functional verification, generated-code review and isolated timed pilot are
  **pending central execution** at the time of this ledger entry. They must
  not be represented as passed by this document alone.

M1 CLI: `merge_bench --profile=pilot --quad-padding-both` plus approved Google
Benchmark flags. Full matrix: `--profile=full`; functional verification:
`--verify-only`. Reduced simulated-tool verification explicitly requires
`--diagnostic --outputs=4096 --touch-bytes=1048576`; it never counts as the
full-size timed pilot. The pilot's selected uniform-k64, geometric-mean64-k64
and uniform-touch-k64 profiles do not establish the full matrix's results.


## Accepted terminal execution — 2026-10-19

Earlier pending wording describes the implementation handoff. The final157-case
release and sanitizer suites passed, including11 merge cases. All15 full-size
functional profiles passed and the representative generated-code inspection is
in [assembly-review.json](assembly-review.json). The isolated M1/M1-touch pilot
passed225 measured repetitions; independent input/output/count/CPU/identity checks
passed for every logged invocation. [Actual pilot results](pilot-results.md),
[audit](pilot-audit.json), [central phase criteria](phase-gate.json). The reduced
[Cachegrind diagnostic](cachegrind-summary.json) passed15 functional cases with
whole-process simulated counts; it is not hot-loop hardware attribution.
