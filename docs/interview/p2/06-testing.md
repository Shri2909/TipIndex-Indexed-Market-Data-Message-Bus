# 06 — Testing: what each test proves, and the bug stories

## How the P2 tests are organized

| Executable | Source | CTest prefix (from CMake) | Count now | At P2 gate |
|---|---|---|---|---|
| `tiplog_topics_subs_test` | `tests/unit/topics_subs_test.cpp` | `topics.subs.` (`cmake/p2.cmake:12`) | 19 | 16 (3 added in P6) |
| `tiplog_oracle_test` | `tests/unit/oracle_test.cpp` | `oracle.` (`cmake/p2_ref.cmake:16`) | 16 | 16 |
| `tiplog_driver_test` | `tests/unit/driver_test.cpp` | `driver.` (`cmake/p2_ref.cmake:22`) | 5 | 5 |

[Doc] phase-gate.json: 52/52 tests in each of release and ASan/UBSan at the gate, including 37 P2 cases. [Doc] subscriptions-scaling.md: the 19 topics/subs tests passed after the P6 repair in both presets.

The check IDs come from VALIDATION_PLAN:
- **V06**: registry ancestors, partitions and local IDs.
- **V07**: normalization and matching against a brute-force matcher.
- **V08**: topics created after subscribing.
- **V09**: oracle retention, hand-computed.
- **V38**: representation limits, rejected without mutation.

### Running only the P2 tests (when the machine is idle; never during a P6 campaign)

```bash
cmake --build --preset release --target tiplog_topics_subs_test tiplog_oracle_test tiplog_driver_test
ctest --preset release -R '^(topics\.subs|oracle|driver)\.' --output-on-failure
# sanitizer build: same with --preset asan-ubsan. Per README, it must run outside sandbox tracing
# so LeakSanitizer works.
```
`^oracle\.` deliberately excludes `oracle_tail.*`, which is P5's Tail reference.

### Independent references *inside* the tests

The registry and subscription tests don't trust production matching either:
- **`segments()` + `reference_match`** (`topics_subs_test.cpp:25-44`) splits paths into `vector<string>` segments with `std::getline(stream, seg, '/')` and compares segment sequences. That is a completely different algorithm from production's hash-of-prefix lookups.
- **`reference_normalize`** (`topics_subs_test.cpp:45-69`) is the old all-pairs algorithm, re-implemented on segment vectors. The comment says: "Deliberately retain the small all-pairs algorithm as an independent reference."
- **`check_reference`** (`topics_subs_test.cpp:70-79`) checks *every* topic in the registry against the reference, and checks that filters are strictly sorted by partition.

## Test map: topics and subscriptions (`topics_subs_test.cpp`)

| Test | Check | What it proves | What it does *not* prove |
|---|---|---|---|
| `V06Registry.AncestorsPartitionsAndDenseLocalIds` (81) | V06 | Interning a depth-4 path creates IDs 1–4 with correct parent, depth, partition (0 for `itch`, 1 for the rest) and local IDs 0,1,2. Re-interning returns the same ID. New symbol → new partition. Depth-1 `bnc` → its own partition | Behaviour with hundreds of thousands of topics |
| `V06Registry.PathValidationAndLookup` (115) | V06 | All 6 malformed forms (empty, `/`, leading or trailing slash, `//`, embedded NUL) throw **and leave counts at 0**. UTF-8 and `%2F` are accepted. `get(0)` and out-of-range IDs throw | That the converter never produces such paths (P1's job) |
| `V07Subscriptions.DeterministicNormalizationPreservesUnion` (131) | V07 | 7 messy terms normalize to exactly 2. Normalization is idempotent. The compiled result agrees with the reference on `itch/AAPL/addition/A` (boundary) and `itch/AAPLX` (boundary). Not wide; the filter isn't `all` | Random inputs (next test) |
| `V07Subscriptions.RandomPathsTermsAndLateTopicsAgainstSegmentMatcher` (157) | V07/V08 | **128 seeds**, each with 72 random paths (24 before, 48 after compile) and 8 subscriptions of 1–12 terms. After late additions, every topic's match equals the reference, and filters stay sorted | Its alphabet (`r0-2`, `s0-6`) has no tricky characters like `-`; the next two tests cover that |
| `V07Subscriptions.NormalizationHandlesLexicalInterleavingAndSamePathKinds` (193) | V07 | **(P6)** The `a`, `a-foo`, `a/b` trap gives exactly `{Subtree a, Subtree a-foo, Subtree a0/b, Exact a0/bc}`. Same-path Exact+Subtree keeps the Subtree. Later topics like `a-foobar/new` and `a0/b-extra` match correctly. Wide is true | Large inputs |
| `V07Subscriptions.NormalizationMatchesIndependentAllPairs` (218) | V07 | **(P6)** 512 seeds × 64 shuffled terms (25% duplicated) drawn from roots designed to collide lexically (`a`, `a-foo`, `a0`, `market`, `market-data`, `Δ`). Equal to the all-pairs reference, and idempotent | Compile/filter behaviour (normalization only) |
| `V07Subscriptions.HundredThousandTermsCompileAndObserveWithoutTimingAssumptions` (240) | V07/V08 | **(P6)** 100k partitions × 2 topics with mixed Exact/Subtree terms: 100k filters, `all` set exactly for the Subtree partitions, 50k hooks, all 200k matches correct, and later topics behave | **Speed.** There is deliberately no timing assertion. It shows the case *finishes* within ctest's timeout |
| `V07Subscriptions.InvalidSpecsDoNotRegisterEarlierValidTerms` (273) | V07 | An empty spec, a bad path after a valid one, a NUL, or an invalid kind all throw, and **no topic is created** | Limit failures mid-compile (see `03`: those can leave earlier roots interned) |
| `V08Subscriptions.FutureSubtreesRespectSegmentBoundaries` (285) | V08 | A subtree created **before** its topics gains `add/A` and `add/F/deep`, but not `additional/A` or `AAPLX/add/A`. Exactly 1 hook | Many concurrent hooks |
| `V08Subscriptions.WideTermsIncludeFuturePartitionsAndShallowExactStaysNarrow` (297) | V08 | `Subtree(itch)` is wide and covers a **future** partition with `all`. `Exact(itch)` is not wide and doesn't match descendants. Neither matches `bnc/...`. `Subtree(itch/NEW)` is not wide: one filter with `all` | — |
| `V08Subscriptions.ExactPreinternedAndNoHookNeeded` (316) | V08 | Compiling an Exact term creates the topic. It matches, a sibling doesn't, and `observer_count() == 0` | — |
| `V08Subscriptions.CopyMoveAndDestructionReleaseHooks` (325) | V08 | Copies share state and see new topics. A moved-from subscription matches nothing. `belongs_to` rejects another registry. Hooks drop to 0 when the last copy dies. 100 create/destroy cycles leave no slots | Thread safety |
| `V08Subscriptions.RegistryLifetimeSafeEvenWithExternallyRetainedAnchor` (353) | V08 | **Bug-2 regression.** Holding `identity().lock()` past registry destruction: `alive()` becomes false, `matches` returns false, and destroying the subscription afterwards is safe. Run under ASan, so a use-after-free would be reported | — |
| `V38Registry.TopicLimitPreflightsEntireAncestorChain` (371) | V38 | With `max_topics = 3`, interning a 4-deep path when 1 exists throws, and **none** of the missing ancestors are created | — |
| `V38Registry.PartitionLimitAndReservedOwnerSentinel` (383) | V38 | `max_partitions = 1` rejects a second partition without mutation. Limits that can't be represented (2³² partitions or topics, 65,537 local IDs) are rejected at construction | That P4 actually uses `UINT32_MAX` (P4 tests) |
| `V38Registry.LocalLimitRejectsMissingAncestorsAndLeavesCompiledBitsUnchanged` (395) | V38 | `max_local = 3`: a failing intern leaves the registry **and the subscription's bits** unchanged; the remaining slot can still be used; the next intern fails | — |
| `V38Registry.FullUint16BoundaryAndLateBitsetGrowth` (411) | V38 | 65,536 topics in one partition: the last gets local ID **65,535**. The filter grows to 1,024 words with bit 63 of the last word set. The next new topic is rejected without mutation | — |
| `V38Registry.ZeroCapacityRejectsWithoutMutation` (431) | V38 | Zero topics, zero partitions or zero local IDs: the first intern throws and nothing changes | — |
| `V08Subscriptions.ObserverAllocationFailurePrecedesAllRegistrationCommit` (451) | V08 | An observer that throws `bad_alloc` in `prepare` leaves the registry (topic count, partition count, lookup) **and another subscription's bits** unchanged. After removing it, the same intern succeeds | `bad_alloc` from the registry's own reserves (same code path, not separately injected) |

## Test map: oracle (`oracle_test.cpp`)

| Test | What it proves |
|---|---|
| `OracleRetention.V09HandComputedPadAndWrap` (19) | The 5-step hand table in `04`: PAD at [56, 64), tail positions 32/56/64, a 16-byte empty DATA |
| `OracleRetention.V09ExactPhysicalFitHasNoPadAndWholeRecordEviction` (49) | A record that exactly fills to the physical end needs no PAD; eviction is of whole records |
| `OracleRetention.RejectsInvalidConfigsAndOversizedPublicationWithoutMutation` (60) | Non-power-of-two rings, max > C/2, max < 16 and non-multiples of 8 are rejected. Oversized payloads and bad paths leave all state unchanged |
| `OracleRetention.RejectsSyntheticLifetimeLimitsBeforeMutation` (78) | Position and sequence lifetime limits throw `overflow_error` before mutation |
| `OracleMatching.IndependentPathBoundaryAndUnion` (93) | String matcher boundaries (`itch/AB/add`, `other/path/child` don't match) and union |
| `OracleMatching.InvalidSubscriptionsAreRejectedIndependently` (109) | The oracle's own validation of empty, bad-path and bad-kind subscriptions |
| `OracleReplay.CapturedUpperExcludesLaterPublicationAndCopiesPayload` (117) | Upper bound captured at open; payload copied |
| `OracleReplay.HistoryExpiredHasExactFieldsAndStableTerminalState` (134) | Exact error fields `{HistoryExpired, 1, 1, 3}`; Error is terminal |
| `OracleReplay.ConservativeExpiryIncludesIrrelevantRecordsAndZeroBudgetDefersCheck` (146) | Irrelevant eviction causes FellBehind; `max = 0` doesn't check or advance |
| `OracleReplay.ErrorPreservesExactDeliveredPrefixAndLastDelivered` (162) | After an error, `last_delivered` and the checkpoint describe the exact prefix |
| `OracleReplay.ExactFinalBudgetIsDoneBeforeExpiryOnNextPositiveCall` (179) | Completion takes priority over expiry |
| `OracleReplay.FullBudgetDoesNotLookAheadAcrossFilteredGap` (193) | No look-ahead: the checkpoint stops at the last delivery |
| `OracleReplay.CompletedZeroOutputSnapshotAdvancesProgressAndChainsFromUpper` (207) | A zero-output completion advances to upper; the next snapshot chains from it |
| `OracleReplay.EmptyFutureAndExtremeQueriesAvoidOverflow` (223) | Empty ring, exactly caught up, and `UINT64_MAX`: no wrap, correct checkpoints |
| `OracleReplay.SeqOnlyOpenSkipsPadWhileFullBatchCanCheckpointBeforePad` (238) | Opening by seq skips a PAD; a batch checkpoint can sit at the end of DATA, before a PAD |
| `OracleReplay.EqualValuedDistinctSequenceEventsSurviveUnion` (250) | Identical payloads stay distinct events, and overlapping terms give no duplicates |

**What V09 can't prove by itself:** that the *production* ring obeys the same rules. That's P3's CC-2 differential testing (1,000 seeds × 10,000 operations in release, at least 200 seeds under sanitizers, per mode and kernel) and F3 fuzzing.

## Test map: driver (`driver_test.cpp`)

| Test | What it proves |
|---|---|
| `TraceDriver.SparseIdsMapPathsAndOpaquePayloadsInGlobalOrder` (54) | A hand-encoded trace v1 with dictionary IDs 7 and 900001 reaches the oracle with correct paths, payloads, global order and ticks (budget 64 by default) |
| `TraceDriver.ScriptedPausesCadenceAndMaxRecordsAreDeterministic` (75) | The worked schedule in `05`; two runs are identical |
| `TraceDriver.SeededBudgetsRepeatAndZeroBudgetDoesNotAdvanceReplay` (105) | Same seed → identical results. A different seed changes only the schedule digest. Jittered budgets are ≥ 1. A zero budget leaves an oracle replay's checkpoint unchanged |
| `TraceDriver.InvalidConfigurationsAndPublisherFailuresRemainExplicit` (142) | Missing publisher, cadence 0, pause at tick 0, overflowing pause, publisher returning 0, a non-dense publisher, and a throwing publisher: each is an explicit exception |
| `TraceDriver.EmptyLimitAndEmptyTraceReportNoPublications` (160) | `max_records = 0` and an empty trace publish nothing and report zeros |

## Kinds of testing used, and why

| Kind | Example | Why it's here |
|---|---|---|
| **Golden / hand-computed** | V09 retention table | The only place a *human* supplies the expected numbers. It anchors the oracle itself |
| **Randomized vs independent reference** | 128-seed matcher, 512-seed normalizer | Finds combinations nobody thought of. The seeds are fixed, so a failure reproduces exactly |
| **Boundary / limit with reduced limits** | V38 with `Limits{3,…}` | Reaches "out of IDs" in microseconds instead of creating 4 billion topics |
| **Fault injection** | `ThrowingObserver` throws `bad_alloc` | Proves the all-or-nothing claim instead of just asserting it |
| **Lifetime under ASan** | retained-anchor test | A use-after-free is invisible in release but fatal under ASan |
| **Property: idempotence** | `normalize(normalize(x)) == normalize(x)` | A cheap, strong sanity property for canonical forms |
| **Scale without timing** | 100k-term test | Catches algorithmic blow-ups without making tests flaky on a slow machine |

**Sanitizers** ([Doc] P0/README): ASan finds memory errors such as use-after-free and out-of-bounds; UBSan finds undefined behaviour such as signed overflow and bad shifts; LeakSanitizer finds leaks. The presets set `ASAN_OPTIONS=detect_leaks=1:abort_on_error=1` and `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1`, so any report fails the test.

## Bug stories, written for interviews

### Story 1: three components disagreed on what a valid topic is

- **Situation.** The registry, the trace reader and the oracle each validate topic paths.
- **Symptom.** The independent review noticed that `Registry::validate_path` accepted `std::string("a\0b", 3)`, while the oracle and trace v1 rejected embedded NUL ([Doc] review.md finding 1).
- **Root cause.** The registry checked empty segments and slashes but not NUL. `std::string` can hold NUL bytes, but any C API, log line or file name would truncate at it. So `"a\0b"` and `"a"` could look identical downstream.
- **Fix.** Reject `'\0'` in `validate_path` (`registry.cpp:76`), *before* any mutation.
- **Regression tests.** `V06Registry.PathValidationAndLookup` and `V07Subscriptions.InvalidSpecsDoNotRegisterEarlierValidTerms`, which also check that a valid term before the bad one wasn't interned.
- **Lesson.** When several components validate the same input, test them against each other. Inconsistent validation is a classic source of security and correctness bugs.

### Story 2: a `weak_ptr` check that wasn't enough

- **Situation.** Subscriptions keep a raw `Registry*` and guard it with a `weak_ptr` to a lifetime token.
- **Symptom.** The review found that `identity()` is public, so a caller can `lock()` it and keep the `shared_ptr`. The token then outlives the registry, the `weak_ptr` never expires, and `matches()` would dereference freed memory ([Doc] review.md finding 2).
- **Root cause.** It treated "the token is alive" as "the owner is alive". Those are different whenever someone else can share ownership of the token.
- **Fix.** Add an `alive_` flag that the registry's destructor clears first. `matches()` and `belongs_to()` check `lock() && alive()`.
- **Regression test.** `V08Subscriptions.RegistryLifetimeSafeEvenWithExternallyRetainedAnchor`, which runs under ASan.
- **Lesson.** A `weak_ptr` tracks the lifetime of *the object it points to*, not of whoever created it. If you hand out ownership of a token, its lifetime is no longer yours.

### Story 3: `reserve` made appends quadratic

- **Situation.** To keep commits non-allocating, the registry and oracle reserved capacity before each append.
- **Symptom.** The review spotted `reserve(size + pending.size())`. Each intern reallocated the whole vector, so total work grew quadratically with the number of topics ([Doc] review.md finding 3).
- **Root cause.** `vector::reserve(n)` sets capacity to exactly n (the authors confirmed this in libstdc++'s `vector.tcc`). That bypasses `push_back`'s geometric growth, which is what makes appends amortized O(1).
- **Fix.** `reserve_growth`: grow to `max(needed, capacity + capacity/2 + 1)`. The oracle uses doubling, and the hash map reserves geometrically too.
- **Regression tests.** The full-u16 test (65,536 interns into one partition) and repeated-subscription tests exercise it. There is no timing assertion.
- **Lesson.** Exception-safety techniques can quietly destroy complexity guarantees. Reserving is right; reserving *exactly* in a loop is wrong.

### Story 4 (after P2, in P6): correct but O(n²) under a 1000× larger parameter

- **Situation.** P2's normalize and compile compared every term with every term, and every topic with every term. All P2 tests passed.
- **Symptom.** In P6, the approved T3 experiment needed **100,000 partitions**. The Python integration test for that case timed out: 132 tests passed and that one didn't ([Doc] subscriptions-scaling.md).
- **Root cause.** O(n²) normalization and O(topics × terms) initial compilation.
- **Fix.**
  - Store subtree roots in a hash set, then check each term's own ancestors (O(depth) lookups).
  - Share one immutable `Matching` structure between initial compile and late-topic hooks, so both make identical decisions.
  - Preserve the old algorithm in the test as the independent reference.
- **Regression tests.** The three new tests in the map above. The full CC-2 (90M release + 18M sanitizer operations), RC3 and timed F3 gates were all re-run on the final source ([Doc] PROGRESS P6, "P6 final source checks").
- **Lesson.** Correctness tests at small scale don't reveal complexity bugs. Add at least one "large n, no timing threshold" test for every algorithm whose input can grow by orders of magnitude.
