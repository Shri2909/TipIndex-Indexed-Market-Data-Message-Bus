# P3 F3 source, grammar and evidence

The joint P1–P5 instruction authorizes this P3 gate. The structure-aware target
is original project code in `tests/fuzz/targets/fuzz_engine_ops.cpp`; it imports
the production engine and the independent test-only oracle. They share value
interfaces, while their matching, storage and retention algorithms stay separate.
No Nasdaq payload bytes or external implementation code enter this target.

Finding #45–47 / S45 → independent in-process comparison and memory checks →
P3.5/V26 → `compare_state`, `compare_reader`, `batch` and operation grammar →
actual commands in `live-state.json` and the terminal gate when available.
The pinned LLVM source sections and revision used to interpret libFuzzer options
were already inspected in [P1 execution notes](../p1/fuzz-segmented-notes.md).
No new dependency or scope change is introduced.

The configuration byte chooses C=64…8192 and max_record=min(C/2,256). Up to four
readers interleave publication, captured replay opens, positive/zero budgets,
close, bounded draining, future-topic creation and oversized rejected inputs.
After every operation, ring boundaries/sequence retention and invariants are
checked against the oracle. Every returned batch compares copied sequence,
position, raw path and payload plus exact status, error fields, upper bounds and
resume checkpoint. Open inputs include retained/expired starts, current head and
UINT64_MAX future starts. Overlap, wide, nonexistent and future-descendant
subscriptions are present. Only Scan is implemented at this phase.

Seven independently decoded synthetic seeds exercise PAD8/wrap, exact-final
budget followed by eviction, irrelevant-prefix expiry, future/max0/zero-output,
late topic hooks, rejected oversized input state and equal-valued distinct events.
The target's expected oversize exception was corrected to `std::length_error`
before builds; an independent reviewer checked grammar/seed decoding. This was
a test-target defect found before execution, not a production crash.

The seed-only smoke passed. Final release and ASan/UBSan each pass 86 tests;
CC-2 passed 1,000×10,000 release and 200×10,000 sanitizer operations. These do
not replace the timed gate. F3 runs with ASan/UBSan and leak checks, no tracing,
persistent synthetic corpus and at least 1,800 confirmed monotonic seconds using
the restartable runner. Timing is fuzz execution evidence, not a benchmark.
`F3-initial-sources.json` records initial source/corpus/binary identities.

Current terminal status and continuation are in [live-state.json](live-state.json).
No P3 completion or P4 start is implied until the root records the passed gate.
