# Final P6 runner review — 2026-10-24

The three blocking recovery findings in `campaign-review.md` are corrected in
the reviewed files. No further blocking issue was identified. This review
executes temporary artifact fixtures only; it does not pass an experiment gate
or supply performance measurements. Production source files were read only.

- `saved_micro_session` prefers the campaign-owned local record, then the
  previously bound child session. The mutable latest pointer is consulted only
  to recover the narrow interruption before a child binding was saved, with
  kind, repetition and start-time checks. Passed child blocks remain reusable.
- `consolidate` computes the ordered complete source digest, preserves an
  existing mismatching destination under an interrupted name, writes and fsyncs
  a temporary complete concatenation, verifies its digest and replaces the final
  path. A matching complete destination is reused without rewriting it.
- Micro JSON normalization and invocation audit now share a protected error
  boundary. Unusable or absent benchmark output produces an explicit crash row;
  available normalized rows retain failed validation and raw references. The
  append identity prevents duplicate publication on retry.
- The M3 manifest checks now require B/name agreement, 4096 queries and one
  consistent trace/posting/query identity across the eight profiles, in addition
  to every invocation's independently expected result and operation count.

Executed commands:

```sh
PYTHONPATH=py .venv/bin/python scripts/check_p6_experiments.py --self-test
.venv/bin/python results/p6/campaign-final-review-fixtures.py
```

Both exited 0. The independent auditor accepted 11 temporary fixture process
rounds through 2476 checks and rejected six separate mutations: output digest,
first-reader digest substituted for a T2 cohort, dictionary semantics, allocator
arithmetic, missing repetition and reused process PID. The recovery fixture
passed seven checks, including partial consolidation recovery, exact digest
reuse, owned/bound session preference, pre-binding recovery, rejection of an
unattributable interruption and retained failure-row deduplication. The earlier
root-run recovery log `campaign-recovery-regressions-20261023T145215.625024Z.log`
also reports all its five recovery assertions passed.

Reviewed implementation identities:

| File | SHA-256 |
|---|---|
| `scripts/run_p6_micro.py` | `be8826a549ed6bd04eac369c7b07d4f3ac661c8e70b7c71dc57560c03fefccfc` |
| `scripts/run_p6_campaigns.py` | `f0719e46ee46c0d64f8046ca643cb20fce5ba073b36075f3b29161843e89c40d` |
| `scripts/check_p6_experiments.py` | `200c49939d5dee754e2ec7aaae8ef46c5b7eb90f190b3c18245aa1e73ba16371` |
| `py/tiplog_py/exp/run.py` | `947a28b3114f23946ebbf2d7e927063facd6800123882959df0afc819c837a41` |
| `py/tiplog_py/exp/oracle.py` | `477c8f57dad712357500bc94c469533c4c8fdae9d5efc799861427020fd40048` |

The final root change omits the repeated full Git status text from individual
observation rows, while keeping Git identity and a reference to complete source
provenance. The auditor has no exact Git-dictionary assumption. This does not
change the reviewed recovery or validation semantics.

The temporary recovery fixture is saved as
`results/p6/campaign-final-review-fixtures.py`; it never launches a benchmark.
No builds, fuzzing, data preparation, research or measurements were run by this
review. The reviewer is quiescent after writing these records.
