# Independent P6 campaign review — 2026-10-23

Read-only review of `scripts/run_p6_micro.py` and
`scripts/run_p6_campaigns.py`, including their P5 protocol helpers and the
P6 driver/normalizer/analysis boundaries. No timing campaign ran during this
review. Synthetic dictionaries passed directly to response functions below
are test inputs, not saved measurements. Root owns the fixes and follow-up
recovery tests; findings were sent immediately when identified.

## Findings requiring correction before measurement

1. **Interrupted micro stages restart accepted blocks.** In the reviewed
   `run_p6_campaigns::micro`, the orchestrator always called the micro runner
   without `--resume`. A partial 20-block M1 campaign would start another
   session, unnecessarily repeating already accepted blocks. The micro runner
   itself supports source-bound resume and skips its passed blocks; the
   orchestrator must bind the actual child session and pass that path on retry.
   Also consult an already bound local session before reading the mutable
   `micro-*-latest.json`: a later unrelated failed latest pointer must not
   invalidate an accepted stage. Root acknowledged and is repairing recovery.

2. **Interrupted consolidation can publish a truncated analysis input.** The
   reviewed orchestrator wrote `evaluation-observations.jsonl` directly to its
   final name, then skipped creation whenever it already existed. Interruption
   partway through concatenation could leave a prefix that resume accepted and
   re-hashed as if complete. Write to a temporary file, flush/fsync and replace
   atomically; on resume verify the ordered source concatenation or a bound
   manifest. This repair can reuse every accepted measurement session.

3. **An existing malformed Google Benchmark JSON bypasses outcome rows.** In
   the reviewed micro runner, `gbench.json.exists()` led to `normalize_gbench`
   before the protected `verify_block` try. A crash can leave an empty or
   truncated existing JSON. That parser error escaped to the session handler
   without appending a process-failure row, although the raw command/error was
   retained. Protect parsing/normalization too and emit an explicit unusable
   output/process-failure observation with return code and raw references.
   This matters when a later resumed attempt passes and analysis includes the
   campaign's failed attempts.

The independent T-output auditor referenced as
`scripts/check_p6_experiments.py` was not present on the first review read.
Root confirmed another agent is implementing it and will wait for its checks
before freezing/starting the campaign. Its initial absence is a preflight
dependency, not evidence that any measurement passed.

## Additional audit improvement

The M3 auditor already checks eight exact names, full 32817244 input records,
`diagnostic=false`, every invocation digest against its independent posting
vector/lower-bound reference and the operation count. For directly auditable
input equality it should additionally require B/name agreement,
`seek_queries==4096`, and consistent posting/query input hashes, logical head,
trace identity and size across all eight profiles. The current frozen C++
construction guarantees these properties by sharing one `Data` object; this
is stronger persisted evidence, not a discovered C++ output mismatch.

## Confirmed design and executed plan-only checks

- Matrix declaration and exact name sets agree: M1/M1-touch **20 blocks / 900
  unique cases**, M2 **6 blocks / 120 cases**, M3 **1 block / 8 cases**.
  The pilot declares exactly one M1 case. No duplicate declared name occurred.
- Plan construction gives **1 pilot, 8 training and 41 evaluation workloads**.
- Independent function checks exercised 30 equal observations and selected
  **15 micro / 10 end-to-end repetitions**; 30 alternating 50/150 observations
  selected **30 / 20**. A 29-observation pilot raised `ValueError`.
- Micro normalization explicitly declares independent random-interleaved
  repetitions with null paired IDs. It does not invent process pairing from
  Google Benchmark repetition indices. T workloads retain distinct process
  rounds, seeded shuffled arms and a saved separate warm-up.
- The final concatenation's declared inputs contain M1/M1-touch, M2, M3 and
  held-out T evaluation only. Pilot and training files are kept separate.
  Auto calibration requires the declared training split and writes a frozen
  policy before held-out execution; evaluation observations used is zero.
- Full source provenance includes scripts/source/build flags through the P5
  helper and all project Python/config files through P6 extensions; required
  executables are hashed. Resume checks source/binary identities. Root's broad
  freeze intentionally means no further development during measurement.
- Micro blocks and T driver use saved quiescence declarations, visible-process
  checks, CPU2 affinity, fresh environment captures and 60-second settling.
  Unsupported controls retain their documented fallback. These checks cannot
  establish host-wide absence of unrelated activity, and do not claim to.
- Analysis `report_status` excludes `measurement_command_ok=false` rows even
  if the engine outcome and digest remain successful. Those rows are reported
  as invalid measurements rather than included in performance summaries.

The executed read-only command imported both runner modules and checked
`plan`, `expected_names`, `response` and `matrix.make_plan` with assertions.
Its output was:

```text
pilot-M1 1 1
M1 20 900
M2 6 120
M3 1 8
pilot training evaluation workloads 1 8 41
response checks passed; no measurements run
```

These checks do not exercise interruption recovery or an actual benchmark
process. Root should test the corrected recovery state transitions and then
rerun the relevant plan/unit checks before creating the measurement freeze.

Review snapshot identities (root may subsequently repair the files):

| File | SHA-256 |
|---|---|
| `scripts/run_p6_micro.py` | `7d4e76db957b369dee31b54be6639a5ff6342447526782147f5b8301c281e5fb` |
| `scripts/run_p6_campaigns.py` | `f0719e46ee46c0d64f8046ca643cb20fce5ba073b36075f3b29161843e89c40d` |
| `py/tiplog_py/exp/run.py` | `38e745938c7f825cabc161580e5c5e538aae91a30cac5b9e77f333950ca90fe8` |
| `py/tiplog_py/exp/audit.py` | `85defa57f14b422305da784b9c4ac55e8a12e452245773c910858880626e2c4a` |
| `py/tiplog_py/analysis/summarize.py` | `09e56d777e5acfad09412d5e00efe780ef37664e2231260144ea7e9391aa14ee` |
