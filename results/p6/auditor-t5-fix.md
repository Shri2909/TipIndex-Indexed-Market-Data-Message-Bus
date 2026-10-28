# P6 T5 saved-output auditor amendment — 2026-10-25

This is a postprocessing-only correction. It changes neither benchmark code,
executables, inputs, timed regions, normalized measurement records nor the
approved matrix, repetition counts or acceptance criteria.

## Finding and independent contract

The completed evaluation's first independent audit ran 10,294,677 checks and
reported 504 failures: 12 memory workloads × 21 process rounds × two T5
request rows. Every failure compared a raw replay `work` dictionary with its
normalized counterpart. The real driver deliberately adds
`observed_allocator_overhead_bytes` from the separate allocator record to the
normalized T5 dictionary (`py/tiplog_py/exp/run.py`, T5 processing). The auditor
had required the raw and enriched dictionaries to be identical. Its temporary
self-test had omitted that real-driver enrichment.

The original failed audit, original auditor and both original provenance
manifests were preserved before any real re-audit. Their paths, sizes and
SHA-256 identities are recorded in
[the immutable before record](auditor-t5-compatibility/before.json).

| Finding → decision | Implementation | Validation → executed evidence |
|---|---|---|
| T5 normalized work adds one derived allocator metric; preserve every raw replay counter and derive the added value independently | `scripts/check_p6_experiments.py:audit_session` invokes the existing raw `memory` audit first, reconstructs expected work from raw replay work plus `(after.uordblks + after.hblkhd − before.uordblks − before.hblkhd) − raw reserved_bytes`, and requires exact dictionary equality | Focused temporary self-test: 2,487 positive-fixture checks across 11 process rounds and 13 rejected tampering cases; actual log linked below |

The raw allocator audit still checks memory/slot conservation, component-byte
recounts, reported requested bytes, the signed charged delta and reported
allocator overhead. The work comparison derives its value from the raw
allocator before/after observations and raw memory subtotal, never from the
normalized value. Negative observed overhead remains signed. A reserved
allocator-enrichment key in raw replay work is rejected. Outside this one
specified T5 enrichment, exact comparisons are unchanged: missing, changed or
unknown counters cannot be silently ignored.

## Focused executed check

```sh
PYTHONPATH=py .venv/bin/python scripts/run_check.py p6 auditor-t5-enrichment-self-test -- .venv/bin/python scripts/check_p6_experiments.py --self-test
```

Exit 0, passed. Actual command/status:
[JSON](auditor-t5-enrichment-self-test-20261025T041647.001633Z.json),
[stdout log](auditor-t5-enrichment-self-test-20261025T041647.001633Z.log).

The positive fixture now models the real driver's normalized T5 work
enrichment and exercises positive and negative allocator overhead. The seven
new negative cases reject altered or missing normalized overhead, changed
normalized work, an unknown normalized key, and changed/missing/unknown raw
work counters. The six existing digest, cohort, dictionary, allocator,
repetition and process-identity tamper cases continue to be rejected. The
temporary fixtures execute no engine, benchmark or experiment.

Auditor SHA-256 before:
`8a6943f3bf21343e5901bf1a60bbd2dcaa8f5c69343c3082b77146b265e5c2ab`.

Auditor SHA-256 after:
`2531f9e9c5f4a8272a207522edb92055b7fe20e44f46deac2efc0d290fb16f44`.

## Scope and continuation

This focused check is not the full saved-evaluation re-audit or the P6 gate.
The parent owns strict provenance compatibility, the real independent re-audit,
analysis and reporting. No actual measurement was rerun or edited for this
amendment. No C++ source or binary, production experiment driver, oracle,
input, normalized output or provenance file was edited by this subtask.
