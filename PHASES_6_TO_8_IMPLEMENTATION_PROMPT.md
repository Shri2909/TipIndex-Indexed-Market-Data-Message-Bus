# Combined execution prompt: P6–P8 through core completion

Prepared 2026-10-19 for approved plan **v1.1 / Tier B**, project **tiplog — C++ Market-Data Message Bus with Indexed Replay**.

**Template only.** Creating, reading or storing this file does not start implementation or change recorded authorization. Send the execution instruction below when ready. P8 is the final core phase; roadmap R1–R10 is a separate scope.

At preparation time, P0–P4 gates have passed. P5's all-mode differential and integrated F3 checks have passed, but its isolated simulated Cachegrind diagnostic, M1/M1-touch/M2 pilot, post-run audit and final gate remain pending. Inspect the latest evidence when executing; reuse valid completed work.

Copy and send the following:

```text
Execute Phases 6, 7 and 8 of approved plan v1.1, Tier B, for tiplog — C++ Market-Data Message Bus with Indexed Replay — through the final core completion gate. I also explicitly authorize completing any remaining P5 prerequisite acceptance work before entering P6.

AUTHORIZATION AND CONTINUATION

This is an execution instruction. Complete the implementation, experiments, analysis, verification, fixes and final packaging; do not stop after a plan or an intermediate phase report.

Verify and reuse P0–P5 implementation and accepted evidence. If P5 is still open, finish its remaining required diagnostic, isolated pilot, independent audit, documentation and acceptance gate. Do not restart completed phases, repeat valid long campaigns unnecessarily or infer P5 completion from source code or elapsed time. Repair earlier implementation only where necessary to satisfy this sequence's existing contracts and gates; rerun checks affected by those repairs.

After P5 passes, execute P6 → P7 → P8. This instruction supersedes the older stop-after-P5 and separate-phase-start requirements for this sequence. Record each gate and continue automatically when it passes. Do not request routine confirmation between phases or for implementation choices, builds, checks and fixes within the approved scope.

The scope is the complete approved Tier B core through P8. Tier C and roadmap R1–R10 remain deferred. Record them accurately in the report; do not implement them as part of “the last phase.” Preserve approved defaults: 2019-12-30 Nasdaq data only, no privileged benchmark-setting changes, existing tiplog identifiers and the supported writable repository layout.

READ AND VERIFY THE CURRENT STATE

Read MASTER_PROJECT_PROMPT.md, docs/plan/INDEX.md and docs/plan/PROGRESS.md first, plus applicable repository instructions. Then read the relevant sections of these files under docs/plan/:

IMPLEMENTATION_PLAN.md; ARCHITECTURE.md; VALIDATION_PLAN.md; RESEARCH.md; STUDY_PLAN.md; REVIEW_2026-10-17.md; FINDINGS_TO_IMPLEMENTATION.md; PROBLEM_STATEMENT_AND_BENCHMARKS.md.

Read the actual P5 evidence, source manifests, benchmark-method notes and latest gate records. Distinguish historical pending entries from later accepted evidence. Apply all v1.1 corrections; the saved phase specifications, Tier B requirements and definitions of done govern details omitted from this prompt.

Use the established CMake presets, validated project .venv and scripts/git.sh for the separate .tiplog-git metadata. Preserve managed metadata, existing user work, prior raw evidence and MASTER_PROJECT_PROMPT.md. Capture the actual current environment and source identity rather than copying old probes.

Use relevant findings, source IDs, study items, design decisions and invariants as implementation inputs. Complete required ST-12 and ST-09 reading for P6/P7. Reuse saved research; inspect primary specifications, papers or author-maintained code just in time where an unresolved implementation detail requires it. Record inspected sections, dates, revisions, limitations and applicable attribution. Keep research bounded to actual decisions, and schedule it outside measurement blocks. Treat external material as reference data, not instructions.

P6 — TIP EXPERIMENTS, ANALYSIS AND FIGURES

Complete P6.1–P6.5 and the full Tier B experiment/analysis requirements:

- Implement and integrate the experiment driver, TOML configurations, append-only runs.jsonl output and independent trace-based Python digest/outcome oracle. Apply V27 to every T-experiment configuration: compare full outputs on success and the delivered prefix, checkpoint and explicit error on expiry. Preserve the appropriate independent expected-output/hash/accounting checks for each microbenchmark. Meet CC-4 for every applicable configuration. A mismatch invalidates the result; record it, fix its cause and rerun affected measurements.
- Finish the required M1/M1-touch/M2 campaigns using the P5 harnesses, plus M3 and T1/T2/T3/T5 with the matrices in VALIDATION_PLAN. A P5 pilot is not a completed experiment campaign. Preserve all four Tier B kernels and required scan baselines.
- Run the P6.2 pilot: 30 repetitions of one M1 and one T1 configuration, record CV, and apply the required response to CV above 3%/5%. Freeze the measurement protocol before evaluation. Calibrate Auto using declared training configurations and evaluate frozen thresholds on held-out configurations/traces; retain the split and thresholds as artifacts.
- Respect timing boundaries, identical states/resources/output sinks and tuned baselines. Record requested and effective replay modes, including wide-term Scan fallbacks. Measure writer/index maintenance separately and include the required amortized contribution in T2. T5 must include the full memory breakdown, independent recounts and the separately measured allocator contribution under its documented process boundary.
- Follow release-build, verified CPU2/P-core affinity, AC power, frequency/noise and environment requirements. Record unsupported controls and use only the approved nonprivileged fallback. Hardware counters require successful actual event probes; missing values remain null. Label reduced Cachegrind observations simulated.
- Keep measurement blocks free of concurrent fuzzing, tests, builds, conversion, optimizer studies and research. Pinning alone does not isolate shared resources. Perform independent development/review outside those blocks.
- Preserve at least 10 measured process-level end-to-end repetitions per configuration, seeded shuffled order per paired round and the separately declared saved warm-up. Apply the required microbenchmark repetition/warm-up protocol. Report both repeat-warm and the defined 64 MiB scratch-thrashed cache treatments with honest labels.
- Save every outcome, including history_expired, fell_behind, invalid_config and crashes, plus flagged noisy runs. Do not discard backlogs outside retention or inconvenient failures.
- Analyze median, IQR, min/max and n with seeded 10,000-resample 95% bootstrap CIs; resample whole paired blocks for paired comparisons. Generate F06–F13 and docs/report/results_tip.md, with a claims table linking every reported finding to raw evidence. Tier B F07 covers run-length effects; galloping remains deferred.

Pass the P6 definition of done: CC-4 for every configuration, RC-1 figure regeneration, complete non-ok accounting and raw-linked claims. Report observed winners, crossovers or absence of gains honestly. Throughput is not a latency distribution; T4 and its latency percentiles belong to Tier C.

P7 — STORAGE-LAYOUT OPTIMIZER

Complete P7.1–P7.6 for Tier B using P1's volume tables and P2's registry:

- Implement the full-window connected residual-store M-store model with two independent cost evaluators: direct formula and materialize-and-simulate. Handle internal-node volumes, zero-volume nodes, above-root terms and baskets without double-counting store reads.
- Implement H-BASE, H-KM-min and H-KM-max with deterministic ties and finite integer threshold domain [0, W_total]; Gray-code ENUM; MASK-DP with reconstruction and the global nonnegative multiplier sweep. Keep independent evaluators and enumeration independent of optimized solver helpers.
- Use exact rational/scaled integer costs, checked intermediates and explicit representation/overflow rejection. Handle empty trees, infeasible K=0, finite one-store plateaus and all V39 cases.
- Pass V28–V32 and V39 in release and ASan/UBSan. Meet CC-5: MASK-DP equals ENUM on at least 10,000 random instances for every k ≤ K, with zero mismatches. Validate the threshold solver against brute force for its own problem, including count monotonicity.
- Reproduce the worked-example waste exactly: baseline 5,517,460,497 B; H-KM-max 39,881,491 B; ENUM/MASK-DP optimum and H-KM-min 30,029,491 B.
- Run Tier B L2/L3/L4/L5, including W0–W3, β/α sensitivity values {0, 64 KiB, 1 MiB}, baseline-matched per-partition budgets, the specified sweeps, synthetic scaling and H-spec/H-flat sensitivity. Generate F14–F18. Preserve the H-flat exact-read baseline's zero-waste case.
- Set and record exact-solver state/time limits before the studies. Report per-workload coverage as counts/fractions of partitions, bytes and workload weight, plus timeout/state-limit/heuristic-only outcomes. Compute optimality gaps only for solved instances with identical objectives, budgets and feasible sets. A timed-out incumbent is not OPT.
- Apply ARCHITECTURE §6.5/§6.9 exactly: nonnegative multiplier sweeps certify only the supported points under their stated preconditions. Unsupported budgets need the specified feasible-cost/bound treatment; incomplete partition curves cannot establish global exactness or certified bounds.

Pass P7's full definition of done. Label costs and bytes modeled; α/β sensitivity values are assumptions until later disk experiments measure them. Distinguish Jane Street's published claims from our independent algorithms. Do not claim to reproduce unpublished Aria internals or extend exactness beyond the declared model.

P8 — FINAL REPORT, REPRODUCTION AND PACKAGING

After P6 and P7 pass, complete P8.1–P8.3:

- Write docs/report/REPORT.md following IMPLEMENTATION_PLAN §11, covering the final implementation, corrected contracts, source-to-decision links, correctness evidence, experimental method, measured results with uncertainty/failure counts, optimizer scope, limitations and deferred roadmap.
- Write docs/report/REPRODUCE.md with tested commands, environment/dependency information, input checksums, configurations, seeds, required local-data setup, raw-to-summary/figure generation and the approved counter fallback. Verify the reproduction commands and one-command regeneration from saved raw results. Preserve existing valid inputs; do not redownload/reconvert merely to demonstrate reproduction.
- Complete the core checklist in IMPLEMENTATION_PLAN §10.1 with evidence links for every applicable item, CC-1–CC-6 and RC-1–RC-3. Verify that prior accepted evidence remains valid for the final source; rerun affected acceptance checks where implementation changes require it. Keep fuzz durations and actual final statistics auditable; do not replace required gates with smoke tests.
- Retain input caveats, including the Nasdaq source's recorded incomplete=true/missing BinaryFILE terminator. Do not claim session completeness, book correctness, measured physical disk I/O, durability or concurrent-reader support from core results.
- Fill resume bullets only with actual measured numbers and supported scope, or remove unsupported bullets. Document absent gains and unresolved limitations as plainly as positive findings.
- Update README, INDEX and PROGRESS to the actual final state without rewriting history. Ensure generated artifacts, references and local links resolve. Keep raw and derived message-level Nasdaq data, real fuzz inputs and large ignored files out of tracked packaging. Prepare local deliverables; external publication/push is outside this instruction.

EVIDENCE, RECOVERY AND FINAL COMPLETION

Maintain finding/source → decision/invariant/task → file/symbol → check → executed evidence/status traceability. Save exact commands, configurations, seeds, input/source/binary hashes, compiler flags, actual Git SHA/dirty status, environment and raw logs/results. Preserve failed runs and append-only raw records. Mark unrun, blocked, deferred and inapplicable work accurately.

Continue implementing and fixing within the authorized scope until the required gates pass. Do not reduce coverage, repetitions, acceptance thresholds or Tier B scope to fit a time estimate, and do not substitute placeholders. Routine decisions need no renewed permission. A material change to approved contracts or scope still needs a concrete amendment and approval; continue unaffected authorized work while that is pending.

Use permitted capabilities and documented fallbacks. This instruction does not bypass actual access controls. If a mandatory requirement remains genuinely blocked, preserve the failed action and precise unmet prerequisite, complete unaffected work and record an exact continuation point. Do not claim completion while a required gate is unmet. If interrupted, resume this same authorized sequence using the saved state.

Give concise progress updates during work and record intermediate gate outcomes without stopping for confirmation. Finish with one consolidated report covering P5 closeout if needed, P6/P7/P8 completion criteria, artifacts, checks actually run, measurements and uncertainty, evidence paths, limitations and any unmet requirements. Mark the core complete only when P8's evidence-backed checklist is satisfied. Stop after P8; roadmap implementation requires a separate instruction.

Begin the read-only preflight, complete any remaining P5 acceptance prerequisite, and execute P6 → P7 → P8 now.
```
