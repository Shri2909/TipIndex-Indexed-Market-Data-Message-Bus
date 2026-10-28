# Saved P6 experiment audit method — 2026-10-24

`scripts/check_p6_experiments.py` independently audits persisted artifacts
against the prepared Python oracle expectations. It never executes an engine,
benchmark, compiler, converter or oracle accelerator. Its result does not
replace the separate approved-matrix review, source reading, correctness gates,
pilot response or measurement controls.

The auditor was checked against the actual driver in
`py/tiplog_py/exp/run.py`, including `aggregate_t2`, process command construction,
subscription transport, per-reader publication, compact process metadata and
the commit journal. It imports the independent oracle's `validate` function;
it does not call a production replay implementation to generate expectations.

For each prepared workload it checks the frozen case/config/source/binary/input
hashes; exact request and expectation coverage; a saved warm-up and every
required distinct process round; request TSV identities and semantics; actual
CPU2 commands, successful exits and recorded AC observations; actual trace or
synthetic input parameters; and every raw and normalized outcome against the
saved independent expectation. Expiry and invalid-configuration outcomes remain
outcomes, not successful timing samples. Preparation must already have passed
the independent approved-matrix review; the auditor explicitly limits its scope
to the supplied prepared plan.

Subscription dictionaries are checked by recomputing each SHA-256 alias from
its term string, requiring the exact set of requested subscriptions, hashing
the saved dictionary identity and verifying that command, record and workload
paths resolve to the same file. `@alias` request references are checked against
the independently hashed original terms.

For T2 each reader keeps its own validated sequence/payload/sink/progress result
in `reader-runs.jsonl`. The whole cohort correctly has null stream digests,
checkpoint and error fields: one reader's digest cannot stand for an ordered
cohort of different streams. The auditor requires those null fields, complete
reader-index coverage and a reference to the actual per-reader file. It checks
summed reader count, payload, CPU, wall and logical work; complete outcome; both
actual publisher inputs and their index-on/off states; the signed CPU delta;
and its amortization exactly once per cohort over the actual publisher window.

For T5 it checks independent retention positions, retained posting count,
allocated/free block and slot conservation, requested-byte component recount,
the actual separate allocator boundary and signed allocator arithmetic. These
are requested/allocator accounting checks, not a claim about hardware traffic
or process RSS.

The process metadata comparison intentionally removes only the large
`owner_counts` vector, matching the driver's compact publication, and attaches
the same actual raw output path. The full raw vector remains in the raw prefill
record. Each completed process must have exactly one metadata row, matching
command record and committed journal/state; normalized publication counts must
match. Orphan normalized rows fail the audit. Unconfirmed raw attempts are
listed with hashes, outcome counts and malformed-line counts; they remain
preserved and are not substituted for a completed round.

Executed review self-test:

```sh
PYTHONPATH=py .venv/bin/python scripts/check_p6_experiments.py --self-test
```

Exit 0: 2476 checks over 11 temporary fixture rounds, including retained expired
and invalid cases. Six independent tampering cases were rejected: raw digest,
misleading T2 cohort digest, dictionary semantics, allocator arithmetic, omitted
process repetition and reused PID. These are format/recovery tests only; no
experimental observations or performance claims were created.

Auditor SHA-256:
`200c49939d5dee754e2ec7aaae8ef46c5b7eb90f190b3c18245aa1e73ba16371`.
