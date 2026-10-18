# P5 Engine integration study and handoff — 2026-10-18

**Preparation only during the running P4 F3 gate. No P5 code or acceptance is claimed.** This note translates the already approved ARCHITECTURE §§3.6–3.7, 4, 5.6–5.7/10 and VALIDATION V13/V14/V21/V23–V26/V35/V38 into concrete integration choices. The joint P1–P5 authorization permits implementation only after P4 passes. There is no proposed scope, semantic, dependency or acceptance amendment.

Source reading is reused from the saved source ledgers and dated RESEARCH limitations. The kernel-specific original-source study is recorded separately by the kernel owner before implementation. This note imports no unavailable Aria implementation detail, code or concurrent reclamation claim.

## Snapshot progress before merge state

ARCH §3.6 and INV-Q7 require Scan, Indexed and Auto to have identical ordered output prefixes, statuses, error fields, captured upper bounds and progress checkpoints under the same publish/open/batch schedule.

Preserve P3/P4's entry ordering:

1. Clear borrowed output. Check the engine lifetime before any owned engine access.
2. A zero budget makes no progress, including no cursor/kernel reinitialization and no Tail re-arm.
3. Return an already terminal snapshot unchanged.
4. For a positive nonterminal batch, unread position equal to the captured upper completes successfully **before** expiry checks.
5. If unread position is below current tail, return the conservative FellBehind outcome before touching index/cursor metadata. Irrelevant-record or PAD expiry still counts.
6. Only now seek cursors, acquire current filters and initialize the selected merge kernel.

The straightforward P4-compatible P5 integration re-seeks at most once per selected partition per positive batch, from the common unread checkpoint. It constructs local cursors and merge state for that batch. This avoids advancing a consumed old cursor whose block was recycled while its unread checkpoint remained retained. It introduces no publication hook or permanent vector reference. The setup cost is part of actual end-to-end replay; it must not be hidden in later measurements. M1 kernel-only setup has its separately specified outside-timing boundary.

A more persistent cursor optimization is unnecessary for correctness and should not be added unless its state transitions preserve the exact contract. In particular, a full output budget returns More immediately after the last delivered DATA, before advancing/peeking to decide whether that happened to be the final matching item. On the next positive call the common upper/completion rule decides Done first. Exhaustion before filling a budget advances checkpoint to captured upper, including zero-output snapshots.

Within a batch, publication cannot interleave. Every cursor still carries block ID/generation/index and a cached logical position; the index's generation validation and cached minimum-position defense remain invariant checks. Kernel entries represent only cursor positions below the captured upper. The record header supplies the topic and sequence; filtering remains intra-partition.

## IDs and filter lifetime

P2 explicitly permits `registry.intern()` to invalidate `CompiledSubscription::filters()` spans and `PartitionFilter*`. Store partition IDs, never these views, across calls. Reacquire filters after the common checks and retain pointers only within the noninterleaved batch. A Tail refresh must use the current compiled subscription's partition set, so previously empty/exhausted partitions and newly created matching partitions can be armed.

At snapshot open, later-created topics cannot have DATA positions below the captured upper. A snapshot therefore remains bounded even when compilation hooks add later topics between batches. For a new Tail snapshot, their postings must become visible. One record belongs to one partition and one compiled local filter; overlapping terms union their topic bits rather than duplicating delivery. Equal payloads at distinct sequence numbers remain distinct events (S61).

## Tail as a chain of completed ranges

ARCH §3.7 defines Tail as a chain of captured snapshots. Preserve a global initial requested sequence floor and a global last-delivered sequence separately from completed-range progress.

- Opening with `after_seq > head_seq-1` rejects as `InvalidRange`, before any `after+1` calculation; it never lowers the requested floor. Snapshot replay retains its separate empty-future/no-checkpoint behavior.
- Keep one current Replay, even while its range is complete or initially empty. This also keeps the existing engine lifetime ownership assertion active. Tail may be movable but remains noncopying, and Engine must outlive it.
- Complete the current range before capturing a new upper. Resume from the completed checkpoint's `after_seq`, **not** from last matching output.
- `poll(0)` preserves the existing status/progress/range and cannot re-arm to a newer head.
- A positive poll after a completed range may arm another snapshot only when new DATA exists. Rebuild/re-seek the complete current partition set: an input exhausted in the old snapshot may now have records, and new matching partitions may exist.
- A completed zero-output range still advances the global resume point. Later matching records must not cause a replay of older irrelevant records or a false failure from resetting progress to last output.
- Failure is terminal for that Tail. An expiry found when opening the initial range is HistoryExpired. If a previously existing Tail waits after completion and retention passes its completed resume point, a newly opened snapshot would say HistoryExpired; project that later re-arm failure as **FellBehind**, because ARCH §3.7 describes an existing reader falling behind. Preserve Tail's original requested floor and global last-delivered value in its error rather than resetting them to each internal range's floor.
- Completion-before-expiry still protects a final exact-budget call: finish that captured range successfully first. If a later poll then attempts a newer range whose start has expired, report its distinct Tail FellBehind outcome.

These are observational requirements; the exact public exception/class spelling for InvalidRange and the poll signature are routine implementation choices. They do not authorize a disk fallback or change the core's final failure contract.

## Auto and representation limits

ARCH §5.6 chooses Scan when wide, when selected partition count exceeds an explicit K limit, or when a metadata count estimate exceeds an explicit ratio of candidate records. Expose configurable thresholds with validation; mark initial values **uncalibrated**. Measured tuning and held-out calibration remain P6. No initial threshold is evidence that Auto is faster.

The index-off configuration can use Scan; explicitly requested Indexed requires an index. Wide terms select Scan. Keep requested mode and effective selected mode visible in aggregate validation evidence so fallback does not masquerade as indexed coverage. Avoid sharing actual engine retention with the independent oracle to justify smaller pools.

ARCH §5.7/V38 bounds the inline key as `((pos>>3)<<16)|cursor_id`. Position and boundaries remain below 2^51; positions are 8-byte aligned; k is at most65,535, with IDs0…65,534. UINT64_MAX is reserved for exhausted input. The largest legal key is UINT64_MAX-1, so do not mask an overflowing position or permit ID65,535. For explicit Indexed, reject an unsupported cursor count before any replay state becomes externally active. Auto can choose Scan for an unsupported count. Power-of-two padding must support the65535→65536 case without a narrow integer overflow. Test near-limit values directly, without constructing petabyte traces or >32-GiB traffic.

## Required adversaries and evidence

| Existing requirement | Concrete integration adversary |
|---|---|
| V13/V35, INV-Q3/Q4/Q7 | Snapshot contains irrelevant A then wanted B; evict only A before next positive batch. All modes/kernels must produce the same conservative error and unchanged max0 result |
| V35 exact-final and long gaps | Deliver final matching DATA exactly at budget, then evict its block; next positive snapshot call completes if unread==upper. A full output budget before a long irrelevant gap must return More at the same DATA-end checkpoint |
| V14/INV-Q5 | Publish later matching events between batches; old snapshot excludes them while a newly captured range includes them |
| V14/V24, Tail re-arm | A selected partition exhausts in range1, then receives matching DATA in range2; another partition is created after subscription; all must arm again without duplicate older delivery |
| V14/V35, zero output | Complete an entirely irrelevant range, then publish matching DATA. Resume from range upper, retain the original requested floor and global last-delivered value |
| V18/V23 | Recycle the block of a delivered old cursor while unread checkpoint remains retained; the next positive batch safely re-seeks rather than advancing the old generation |
| V35 future/zero budget | Extreme future snapshot has no reusable checkpoint; extreme future Tail rejects InvalidRange; repeated max0 polls cannot lower floor, advance progress or capture a new upper |
| V21/V23/V38 | Empty active cursor set, k1, uneven exhaustion, four kernels, k/id/sentinel limits and padded loser-tree boundary |
| V23/V24/S61 | Multiple overlapping exact/subtree terms and equal-payload distinct events across partitions; sequence order exact with each event once |
| CC2/RC3 | Full required seeds/operations separately identify effective Indexed/Scan paths; replay status/error/progress/digest equal independent raw-path oracle; repeated/compiler runs retain exact commands and source identities |

No new tests or benchmark runs were executed by this preparation. P4's running timed F3 continues against frozen P4 sources; P5 implementation and its fresh gates start only after P4 terminal acceptance.
