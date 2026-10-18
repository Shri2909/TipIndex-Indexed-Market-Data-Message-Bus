# Independently hand-computed P4 pressure fuzz fixture

Design/test preparation while P3 F3 runs; **no P4 implementation or executed
pressure result**. This derives expected states directly from approved framing
and ForceEvict policy, before an index implementation supplies any answers.
It complements ample-pool randomized oracle campaigns. Never set oracle tail
from the engine under test.

Use C=64, max_record=32, B=1, N=1; pre-intern A and B in separate partitions.
With one full block, every later publication needs the only old block freed.
Choose alternating A/B with payload lengths 10,4,8,0,8. Whole-record capacity
alone would retain more, but the declared pressure policy must evict the old
block's DATA first. The prospective tail is always an existing item boundary.

| Step | Topic | Payload | DATA start | DATA bytes | Head | Tail | Oldest seq | Cumulative pressure DATA | Cumulative pressure bytes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | A | 10 | 0 | 32 | 32 | 0 | 1 | 0 | 0 |
| 2 | B | 4 | 32 | 24 | 56 | 32 | 2 | 1 | 32 |
| 3 | A | 8 | 64 | 24 | 88 | 56 | 3 | 2 | 56 |
| 4 | B | 0 | 88 | 16 | 104 | 88 | 4 | 3 | 88 |
| 5 | A | 8 | 104 | 24 | 128 | 104 | 5 | 4 | 104 |

Step3 introduces PAD[56,64), which remains at the tail. Step4 pressure evicts
that 8-B PAD plus the 24-B DATA. Capacity-only eviction is zero throughout.
After every step exactly the newest DATA is retained/indexed, allocation high
water is1, allocation count is step, free count step−1, and the sole block's
generation is step−1. B1 seals each new block immediately. Slot conservation is
one live entry, zero stale/slack/free slots. Recount independently verifies this.

Open two A replays after step1 with after_seq0. Leave one unconsumed; after
step2 a zero-budget call preserves More, then a positive call returns
FellBehind(requested_after0,last_delivered0,oldest_retained2). Let the other
consume one record exactly at its output limit: checkpoint{1,32}. After steps2
and3, its next positive call must return Done despite tail56>upper32, because
unread==captured upper is checked before expiry. A B replay opened before step2
with no matching snapshot records still uses conservative progress; if its
first positive call occurs after step2 it must FellBehind just as scan does.
If exhausted before step2, its zero-output Done checkpoint advances to upper32.

Repeat with RejectPublish: step1 succeeds, attempted step2 rejects before any
sequence/retention/content/index-membership/generation mutation. Requested
unused backing capacity may grow during preflight and must remain honestly
reported. Check the specific pressure rejection, not an arbitrary exception.

The P4 F3 target should execute this fixture branch from a genuine synthetic
pressure seed; a filename without an actual tiny pool is insufficient. Its
ordinary randomized branch can use an ample pool and the independent capacity
oracle. V15–V20/V37 unit tests separately exercise late partial seals, reduced
delta widths, sweeps, generation exhaustion and strong rejection. These are
existing acceptance requirements, not extra scope or measured findings.
