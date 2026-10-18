# P3 ring: source inspection and implementation traceability

Inspected **2026-10-18 (Asia/Kolkata)**. This records P3.1/P3.3 and the ring
portion of P3.4. P1/P2 gates passed before this work; no index, merge kernel,
concurrency or durable log implementation is introduced here.

Read `MASTER_PROJECT_PROMPT.md`, `PHASES_1_TO_5_IMPLEMENTATION_PROMPT.md`,
INDEX/PROGRESS and the applicable approved tasks. Consulted ARCHITECTURE
§§3.5–3.7, 5.3–5.4, 9–10, 13; STUDY ST-03/ST-04; VALIDATION CC-1/CC-2,
V09–V11/V36; FINDINGS rows 11–15/21; and the dated review's PAD/arithmetic/
representation corrections. Existing source limitations remain applicable.

## Original material actually inspected

| Source | Read depth and revision | What transfers; limitation |
|---|---|---|
| S11 [Aeron Transport Protocol Specification](https://github.com/aeron-io/aeron/wiki/Transport-Protocol-Specification) | Terminology (term/offset/frame); General Header Format; Data Frame alignment note; Padding Frames; SHM Memory Ordering for Frame Writing. Wiki displays edit **2025-03-12**, 22 revisions. Re-inspected the original rendered specification; no Aeron implementation source code was inspected or copied. | In-band end padding and logical offsets motivate explicit framing. Aeron's 32-byte header/alignment and shared-memory publication protocol are different; this core is single threaded and claims no concurrent safety. |
| S13 [Kafka log implementation note](https://github.com/apache/kafka/blob/trunk/docs/implementation/log.md) | Complete short rendered log note: identification/offset paragraphs, Writes, Reads, Deletes, Guarantees/recovery. Moving **trunk documentation**, accessed 2026-10-18; no source-code revision or copied implementation applies. | Explicit failed expired reads and deletion of whole units motivate retention/error contracts. This historical byte-offset note is an analogy, not a specification of all current Kafka APIs. Sparse DATA checkpoints and the ring algorithm are independent project design. |

No external implementation code was reused. Jane Street statements remain in
the research ledger under their original source IDs; neither ring internals nor
the checkpoint algorithm are represented as unpublished Aria details.

## Finding → decision/invariant → task → symbol → validation

| Finding/source | Approved decision/invariant | Task and implementation | Check/evidence |
|---|---|---|---|
| Reused physical slots differ from monotonic message order (S11; findings 11) | Separate dense `Seq` and logical byte position; R1/R3/R5 | P3.1: `Ring::append`, `Ring::commit`, `head_seq/head_pos`, bytewise little-endian header codecs in `src/tiplog/ring/ring.cpp` | V10 explicit header/fit/full/wrap tests; V11 per-operation invariant checks |
| Variable records require end handling (S11; findings 12–13; v1.1 review) | Eight-byte alignment, DATA≥16, PAD≥8; `max_record<=C/2`; R2–R6 | P3.1: `checked_config`, `dry_run`, `decode`, `commit` | V10/V36 hand-computed C64 exercise (sizes 32/24/24/16/24, PAD56–64, final head128/tail64/tail_seq3), zero payload and exact fit |
| Overflow or resource rejection after eviction breaks publication (findings 21; independent review) | All rejection precedes mutation; exclusive resulting head bound `<2^51`; published sequence leaves next sequence representable | P3.1: `dry_run`, alias-aware `plan_append`; nonallocating `commit(Plan&&,topic) noexcept` | V36 oversize/SIZE_MAX/near position/sequence limits compare complete storage, counters and logical state; abandoned plans do not mutate |
| A publication input can borrow ring memory | Capture aliased bytes during preflight before overwritten headers/padding; borrowed DATA spans expire on mutation | P3.1: `Plan::alias_copy_`, `plan_append`, `commit` | Ring-storage source overlapping the destination header; prior delivered payload republished across PAD/wrap/eviction |
| Seq lookup should skip most retained DATA (S13 analogy; finding 15) | Checkpoint every `2^L` DATA, generic16 sizing, floor seek examines ≤`2^L` DATA plus PAD | P3.1: fixed `checkpoints_` allocation `floor((C/16)/2^L)+2` positions, **8 B each**; retained DATA validates sequence identity; `note_checkpoint`, `seek_after` and seek metrics | V36 12,000 zero-payload publishes / every retained seek with default L8, checkpoint reuse/expired floors with L2, PAD between floor and target |
| Capacity-only retention is maximal; pressure may shorten it (v1.1 review) | R7 smallest surviving item start≥new_head−C; declared pressure counted separately | P3.1/P3.3: `dry_run` complete-item eviction plan; `check_invariants`, ring counters | V11 random append checks; V36 explicit pressure boundary preview/commit and exact extra DATA/byte accounting. P4 will attach its own independently checked pressure policy, not infer it from ring state. |

`tests/unit/ring_test.cpp` defines **17 ring cases**, including 64,000 random
appends with `check_invariants()` after every commit. These are ring unit checks;
they do not substitute for P3's independent oracle differential campaigns or F3.

## Execution evidence

Build/test execution is owned by the parent integration task to avoid concurrent
mutations of shared build trees. At source handoff the above checks are
**implemented, not yet represented as passed here**. The parent will attach
actual release/sanitizer commands and results to `results/p3/` and the P3 gate.

Prepare/commit is a single-threaded transaction: a plan must be consumed once,
with no intervening mutation. A violated internal precondition terminates rather
than taking a new failure path after eviction. `at(pos)` requires a retained
item boundary; `is_boundary` provides explicit validation for untrusted resume
positions. Configuration limit hooks exercise the same checked production path
without allocating a petabyte log. Pressure support only previews/applies a
declared boundary; no P4 policy or index is implemented by this P3 module.
