# C++ tools, trace, layout and microbenchmark remediation

Date: 2026-10-26. This implements the approved audit remediation scope. The
work-budgeted replay/tail polling feature remains deferred; no replay/polling
API work was done here. Historical results, accepted ledgers and gate evidence
were left unchanged.

## AUD-005 — ITCH byte-offset diagnostics

The C++ `ItchWalker` now tracks consumed bytes and each frame's starting prefix
offset independently of feed chunk size. Unknown types, specification-length
mismatches, unsupported lengths, truncation, trailing bytes after the terminator,
and counter overflow report a byte offset in `FormatError`. Existing acceptance
and count semantics remain unchanged. Tests cover multiple chunks, errors after
a valid frame, incomplete prefixes/payloads, and the first trailing byte.
Python routing/conversion diagnostics are handled by the Python remediation.

## AUD-013 — Trace dictionary amplification

Duplicate-path detection now uses temporary `string_view` keys borrowing the
reader's immutable mapped/span bytes, removing the extra owned string copy per
dictionary entry during validation. The retained dictionary still owns its
paths and id index. Views are discarded before construction completes and never
refer to vector elements, so vector reallocation cannot invalidate them.

The reader also rejects paths above the shared 4,096-byte / 128-segment topic
contract before allocating a path; this closes its AUD-001 entry point in
coordination with the Registry change. Exact boundary and over-bound tests are
included. No arbitrary aggregate dictionary cap was added: the original finding
was informational, dictionary storage remains bounded by file size, and a cap
would reject otherwise supported large dictionaries. Full-file immutable trace
validation is preserved. The previous measured 7.6x amplification is historical;
no new amplification/RSS claim is made without a new controlled measurement.

## AUD-022 — Final evidence write failures

`tiplog_bench` flushes, checks, closes, and checks its owned result stream after
the final prefill/memory/allocator write. Its existing per-request checks remain.
The worked example and CC-5 explicitly flush and check stdout; owned files are
closed and checked before success. CC-5 saves its requested file successfully
before printing the success summary. The layout frontends now check final
flush/close too. Microbenchmark input manifests and invocation diagnostics also
check final flush/close. Standalone result-writing tools check stdout completion.

CLI regressions exercise `/dev/full` for the no-request benchmark, memory and
allocator branches, worked-example file/stdout, CC-5 file/stdout, and M3 input
manifest; valid outputs are parsed to ensure success paths still produce records.
The allocator branch is unavailable under sanitizers and fails explicitly there.

## AUD-023 — Synthetic distribution integrity

Both C++ harnesses use one shared payload-mix parser. It checks the exact header,
complete row shape, one-letter unique type, supported payload range, positive
uint64 counts, read failures, and checked cumulative addition. Synthetic
`tiplog_bench` validates every row before constructing/publishing the workload.
Harness-specific upper payload limits remain supported (M2: 256; integrated
benchmark: max DATA record minus its 16-byte header). CRLF remains accepted.

Tests reject the reproduced two-count overflow, malformed later rows, duplicate
and invalid types, bad sizes/counts/headers and empty mixtures. A total exactly
UINT64_MAX remains supported and safely sampled. Valid deterministic workload
draw order is unchanged.

## AUD-024 — Finite simulator policy options

The simulator parses Auto fractions only when finite and in `[0,1]`, before
backend selection. NaN, both infinities, negative values and values above one
fail for both recording and engine backends. Endpoints zero and one produce
valid JSON. The recording backend cannot bypass this validation.

## OBS-01 — Benchmark failure taxonomy

Known per-request validation (including typed topic/index representation errors) emits
`invalid_config`, retaining the expected reject-arm process contract. Exceptions
outside that explicit validation scope cannot become configuration rejections.
Replay construction is probed before warm-up/cache treatment, so explicit
Indexed cursor limits or a disabled index are validated as known configuration
rejections. Only invalid_argument and the typed index representation limit are
caught there; unexpected construction errors still fail the process.
Timed/untimed divergence throws `ValidationFailure`, emits `validation_failure`
and makes the process exit nonzero. Other request execution exceptions emit
`runtime_error` and also make the process fail. Unexpected compilation failures
propagate to the top-level nonzero exit.

A unit regression injects digest/work/checkpoint disagreements and verifies the
distinct classification; bad allocation and an unexpected invalid_argument
from execution classify as runtime errors. CLI tests verify ordinary malformed
requests and excessive topic depth still yield explicit invalid_config rows.
Python downstream rejection of internal-failure statuses is covered by its
own remediation tests. The existing Python 100,000-partition packed-cursor
regression was also executed against the final tools binary: every explicit
Indexed arm remains invalid_config/process success, every Auto arm falls back
to Scan, and independent oracle comparisons pass. See
`tools/packed-limit-regression.log`.

## OBS-02 — M3 fixture preparation and resident references

Google Benchmark initialization and filter processing precede trace/fixture
preparation. Only B values selected by the pinned extended-regex filter (including
its leading `-` exclusion form) construct pools. Selecting no arms avoids opening
the input trace at all. The verify-only path still validates all four B values.
After all selected fixtures pass independent query/scan digests and recount,
build-only chronological and per-partition postings are released. The retained
partition count, query expectations and reference hashes support identical
measurement operations/metadata. Selecting every B still retains four pools;
selecting a single B retains one.

A filtered one-iteration functional invocation matches its independent
verify-only metadata/digest, and a no-match invocation proves input preparation
was skipped. This is a resource/startup correction, not a new timing result.

## OBS-03 — Prefill flag clarity

`--measure-prefill` remains a backward-compatible explicit-intent alias.
Prefill is always measured and emitted, as existing callers expect. The unused
boolean was removed and `--help` now states the behavior; no artifact schema or
measurement boundary was changed.

## OBS-04 — Aggregate frontend and preparation budgets

Both layout frontends expose these separate resource limits:

| Option | Default | Scope / check |
|---|---:|---|
| `--max-input-bytes` | 134,217,728 (128 MiB) | Complete input stream, including comments/separators; checked before appending the next byte. |
| `--max-curve-entries` | 2,000,000 | Sum of all retained global curves; checked before assigning each values vector. About 32 MB of raw 16-byte Cost values, plus bounded input/container overhead. |
| `--max-prepare-work` | 200,000,000 | Conservative aggregate preparation traversal budget across all CASE records. Per case: positive-volume nodes times (classes + terms). Checked before preparation/copying. |
| `--max-prepared-entries` | 2,000,000 | Materialized node/class memberships per prepared case; checked before each insertion. |

Library `prepare` defaults to 100,000,000 work per call and 2,000,000
memberships and accepts explicit `PreparationLimits`. The frontends pass their
configured work/membership limits and additionally accumulate preparation work
across cases. Defaults bound the previously uncapped input/setup stages without
changing objective arithmetic, exact solver state/work/time caps, eligibility,
or certified optimum semantics. Larger intentional offline inputs can set
explicit frontend budgets. Preparation remains outside the reported solver
interval, consistent with the existing protocol. These limits bound logical
input/work/storage counts; they are not a claim of an exact process RSS limit.

Compatibility preflight read all 32 frozen P7 input batches (verifying their
manifest sizes, case counts and SHA-256 values), plus all 24 frozen global-curve
batches. Maximum input size is 88,718,316 bytes; maximum aggregate conservative
preparation work is 120,300,000; maximum per-case work is 1,004,000, with at most
4,000 possible memberships per case. Global batches peak at 2,415,456 input
bytes and 120,904 curve entries. **All fit the final defaults.** The initial
64 MiB / 100M draft would reject `synthetic-n1000.tsv`; the final bounded
128 MiB / 200M values were selected from this compatibility evidence. See
`tools/frozen-budget-preflight.json` and the reusable read-only
`tools/check_frozen_budgets.py`. No solver/campaign timing was run.

Unit and CLI regressions cover boundary acceptance, cumulative multi-curve
rejection, multi-case preparation accounting, membership excess, input bytes,
and uint64-safe charging. Existing exact/evaluator/heuristic tests still pass.

## Validation performed

- Fresh focused Release build in `build/remediation/tools`.
- **47/47 focused CTests passed**: trace, layout, benchmark contracts and
  `tools.cli_contracts` (seven CLI regression groups). See
  `audit/remediation/tools/focused-tests.log`.
- Six CLI regression groups intentionally fail against the preserved
  original `build/release` executables, demonstrating regression coverage.
  See `audit/remediation/tools/baseline-red-tests.log`.
- Against the original binaries, M3 verify-only JSON for a deterministic
  4,096-record fixture, M2 default verify-only stdout, and worked-example stdout
  are byte-identical. See `audit/remediation/tools/deterministic-comparison.json`.
- Build logs are under `audit/remediation/tools/`. The root remediation runs the
  full Release/Debug/sanitizer/fuzz-preset test matrix after integration.
- No quiet-host performance measurements or accepted campaign/gate reruns were
  performed here. No claims of improved measured throughput were introduced.

The differential CLI also exposes the core remediation's
`nonuniform_payload_publications` counter so new payload coverage can be audited.

## Final correctness and historical measurement closeout

`tools/final-closeout-summary.json` combines the final read-only validations:

- All 32 frozen CASE batches retain their manifest hashes and fit the current
  frontend defaults; all 24 frozen global-curve batches fit as well. Actual final
  Release CLI help exposes the 128 MiB / 200M defaults.
- Current Release and ASan/UBSan CC-5 binaries each completed **10,000 cases**
  with zero mismatches and JSON identical to `results/p7/cc5-release.json`:
  57,461 exact-count comparisons, 57,461 at-most comparisons, 96,322 reconstructed
  layouts; result digest `c4b17e0577e35cab`.
- Release and ASan/UBSan worked-example output is byte-identical to the frozen
  `results/p7/worked-example.json` snapshot (SHA-256
  `1a7285138512abe020804aed6f7c3cfd5668c75cbe6cfcf2dcb02a5104a1f964`).
- Sanitizer closeout ran outside the tracing sandbox with leak detection enabled
  for CC-5, exit zero and empty stderr. The initial sandbox run hit LSan's known
  ptrace restriction after producing correct output; the untraced control resolves
  that environment issue. Commands, binary/output hashes and process statuses
  are in `tools/layout-closeout.json` and `tools/layout-closeout-untraced.log`.
- The original 2026-10-25
  `results/p6/auditor-t5-compatibility/measurement-files-before.json` enumerates
  SHA-256 identities for **all 5,364 original P6 measurement files**. Every listed
  file remains present and byte-identical: **4,105,957,437 bytes**, zero changed
  files. See `tools/frozen-p6-measurements.json` and the reusable verification
  script. The retained P8 artifact manifest itself matches the SHA-256 captured
  at remediation start and inventories the measurement identity manifest by
  path/size. P8 does not hash that identity manifest; the original saved manifest
  supplies the raw-file hashes. The 6,830-file remediation baseline covers source,
  documents and corpus, rather than these raw measurements.

All new outputs stay under `audit/remediation/tools`. No primary build was run
for this closeout, no historical artifacts were written, and no performance
measurements were asserted.
