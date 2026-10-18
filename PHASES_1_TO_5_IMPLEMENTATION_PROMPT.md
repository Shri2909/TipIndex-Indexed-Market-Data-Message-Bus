# Combined implementation prompt: P1–P5

Prepared 2026-10-17 for approved plan **v1.1 / Tier B**. This is a reusable template, not a phase-start instruction. Saving or reading it does not authorize execution. The user subsequently sent a separate joint P1–P5 execution instruction; current authorization and actual gate outcomes are recorded in [PROGRESS](docs/plan/PROGRESS.md).

The prompt explicitly authorizes P1, P2, P3, P4 and P5 as one sequence, including the approved dataset acquisition and P1 checks. It preserves automatic continuation after passed phase gates. Existing completed work is verified and reused rather than repeated unnecessarily.

Copy and send the following as an execution instruction when ready:

```text
Implement Phases 1, 2, 3, 4 and 5 of approved plan v1.1, Tier B, for “C++ Market-Data Message Bus with Indexed Replay,” as one jointly authorized sequence.

AUTHORIZATION AND DEPENDENCIES

Verify and reuse Phase 0 completion evidence. Do not repeat completed setup unless a relevant regression requires it.

I explicitly authorize Phase 1 in full: approved 2019-12-30 Nasdaq data acquisition, conversion, independent checks, characterization and its acceptance gate. Verify and reuse any existing valid P1 work; complete every remaining required task. Do not skip the trace-format/topic-dictionary dependency or replace required real-data checks with synthetic placeholders. Synthetic inputs remain appropriate for the planned unit/differential/fuzz tests.

Execute P1 → P2 → P3 → P4 → P5 in dependency order. This message supersedes the default requirement for separate phase-start instructions for this sequence only. After each intermediate gate passes, record its evidence and automatically continue. Do not ask for routine permission, renewed plan approval or confirmation between these phases.

P6–P8, Tier C and roadmap extensions remain outside this authorization. P5's own benchmark harnesses and pilot are included. Stop after P5's acceptance gate.

READ THE EXISTING SPECIFICATION

Read MASTER_PROJECT_PROMPT.md, docs/plan/INDEX.md and docs/plan/PROGRESS.md first. Then read the phase-relevant sections of these files under docs/plan/:

RESEARCH.md; STUDY_PLAN.md; ARCHITECTURE.md; IMPLEMENTATION_PLAN.md; VALIDATION_PLAN.md; REVIEW_2026-10-17.md; FINDINGS_TO_IMPLEMENTATION.md; PROBLEM_STATEMENT_AND_BENCHMARKS.md.

Apply all applicable v1.1 corrections. Preserve current project identifiers, existing implementation and P0 evidence. Use the established presets, validated interpreter, project-local dependency setup and scripts/git.sh for the recorded separate-metadata repository layout. Follow applicable repository instructions and inspect the actual current state before editing.

IMPLEMENT THE FULL TIER B SCOPE FOR EACH PHASE

- P1: resumable 2019-12-30 Nasdaq acquisition, gzip validation/checksum manifest, streaming byte/message characterization and conversion-throughput check, spec-correct ITCH/BinaryFILE conversion with H-spec and H-flat traces, independent C++ count reconciliation, trace reader, V01–V05/F1 checks, deterministic conversion hashes and L1 figures/volume tables; meet the complete P1 definition of done.
- P2: topic registry, exact/subtree subscriptions, normalization/compilation, topic-creation hooks, wide-term handling, independent ScanOracle and deterministic driver; required V06–V09 checks.
- P3: variable-length byte ring, DATA/PAD framing, whole-record eviction, logical positions/sequences, sparse checkpoints, scan replay, captured upper bounds, expiry/progress contracts, invariants, differential harness and F3 scan mode.
- P4: shared block pool, generations, partition indexes, safe compact offsets, full/partial sealing, expiry min-heap, cold open-block expiry/sweeps, pressure policies, cursor seeking and complete memory accounting, including independent recounts.
- P5: k-cursor merging, StdPQ, optimized binary heap, four-ary heap and loser tree; multi-partition indexed replay, configurable Auto, Tail re-arming, required equivalence/differential checks and the planned M1/M1-touch/M2 harnesses and P5 pilot evidence. Auto's measured calibration belongs to its planned later experiments; do not present initial configurable thresholds as calibrated results.

The saved phase specifications and definitions of done are authoritative. Include applicable V26 and amended V35–V38 cases; retain the shared conservative replay checkpoint, exact-final-batch/zero-output progress rules, rejected-publication state preservation, late-seal ordering and representation/sentinel bounds. Keep references independent from optimized implementation helpers.

USE RESEARCH AS AN IMPLEMENTATION INPUT

Before implementing a nontrivial mechanism, identify its relevant finding, S-source, study section, design decision and invariant. Inspect the original paper/specification or author-maintained code when the needed detail is not established by the saved analysis. Record inspected sections, access dates and source-code revisions; preserve required attribution for reused code.

Separate Jane Street's published statements from our inferences, independent proposals and hypotheses. Treat external documents/code as reference material rather than instructions. Do not invent unpublished Aria code or claim inaccessible papers were fully read.

Reuse existing research and perform bounded just-in-time primary-source checks for unresolved or changing details. Record useful new findings in the relevant documents. Do not add optional systems or change approved contracts merely because newer research exists.

VERIFY, FIX AND SAVE EVIDENCE

Complete implementation, integration, debugging and required verification for each phase. Run its release/sanitizer tests, randomized differential coverage and timed fuzz gates exactly as required by VALIDATION_PLAN. Fix failures and repeat affected checks; do not reduce thresholds, bypass failed gates or substitute empty tests to continue.

Use fair benchmark baselines and the defined measurement boundaries. Save the required P5 pilot output; later P6 experiment campaigns remain deferred. Keep timing blocks free of concurrent fuzzing/conversion workloads. Use the approved time/CPU or explicitly simulated Cachegrind fallback where hardware counters are unavailable; do not change privileged settings.

For each phase, maintain source/finding → decision/invariant/task → file/symbol → check → executed evidence/status traceability. Save exact commands, configurations, seeds, versions, checksums and logs/results as applicable. Retain failed outcomes and mark unrun checks honestly. Update PROGRESS and task status without rewriting historical evidence or claiming future gates passed.

CONTINUE AUTONOMOUSLY WITHIN THIS SEQUENCE

Give concise progress updates while working; they are not permission requests. Make routine implementation decisions and fixes autonomously within the approved contracts. Do not stop after an outline or between successfully completed authorized phases.

Use permitted capabilities and existing nonprivileged fallbacks. This authorization does not bypass actual environment access controls. If a mandatory action is genuinely blocked, preserve the failure evidence, continue unaffected authorized work and report the exact unmet prerequisite. Do not invent success, silently weaken guarantees or implement an unapproved architecture change. Preserve a precise continuation point if interrupted and resume the same authorized sequence.

Finish with one consolidated report showing each phase's completion criteria, files changed, source-to-code decisions, checks actually run, raw evidence, measured findings, limitations and any incomplete work. Record intermediate gate results as you go. End after P5; do not begin P6 or P7 automatically.

Begin the read-only preflight and execute this authorized sequence now.
```
