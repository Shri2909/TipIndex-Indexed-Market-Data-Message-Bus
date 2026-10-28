# Independent second-pass audit: layout, trace, C++ tools and microbenchmarks

Date: 2026-10-26. Production files were read, not edited. All probes run against
the existing release binaries. Reproduce with
`python3 audit/second_pass/layout_tools/probe_tools.py` from the repository root.
The script writes fixtures and command/exit/output JSON only into this directory.
Diagnostic wall times are not replacements for the controlled P6/P7 measurements.

**Fresh-build confirmation:** All three confirmed findings and the successful
request-flush control were rerun against isolated binaries built from the current
tree at `/tmp/tiplog-second-pass/release`. Results match. Fresh evidence is in
`fresh_release/`; `fresh_release/confirmation.json` includes binary SHA-256 values,
exit codes, both mixture head positions, and the invalid-JSON check. Reproduce:

```sh
TIPLOG_AUDIT_BIN=/tmp/tiplog-second-pass/release \
TIPLOG_AUDIT_SKIP_PREPARE=1 \
TIPLOG_AUDIT_EVIDENCE="$PWD/audit/second_pass/layout_tools/fresh_release" \
python3 audit/second_pass/layout_tools/probe_tools.py
```

## New confirmed findings

### LT-1 — Result-file flush failures can be reported as successful runs

- **Severity:** LOW. **Evidence:** CONFIRMED, executed against `/dev/full`.
- **Sources:** `tools/tiplog_bench/main.cpp:876-887` (flush/check only inside
  the request loop, followed by unchecked memory/allocator output),
  `tools/tiplog_layout/worked_example.cpp:246-260` (stream state checked before
  buffered close), and `tests/layout/layout_cc5.cpp:394-402` (same buffered-close issue).
- **Trigger:** An output write/close fails during a prefill/memory-only benchmark,
  worked example, or CC-5 run. A disk-full filesystem is a realistic cause.
- **Observed:** All three exit 0 without stderr while their requested output is
  unwritable. `bench_output_full.json`, `example_output_full.json`, and
  `cc5_output_full.json` contain exact commands and results. CC-5 prints its
  success JSON to stdout even though its requested evidence file was not saved.
- **Boundary checked:** Adding a valid replay request makes `tiplog_bench` exit 1
  with `failed writing result`, because that path explicitly flushes.
  See `bench_output_full_with_request.json`. Do not claim the request-loop path
  also fails this check. A later memory/allocator write still occurs after that
  last successful request flush.
- **Impact:** An automation that trusts exit status can accept missing or truncated
  benchmark/correctness evidence. No existing saved result is asserted to be lost.
- **Recommendation:** Explicitly flush and check the final stream; for owned
  files explicitly close and check before returning success. Keep write failure
  separate from an invalid request. Apply the contract consistently to evidence
  writers, including stdout if it is used as the requested artifact.
- **Meaningful validation:** Valid temporary output still parses and has the
  expected records; `/dev/full` yields nonzero for no-request benchmark,
  benchmark memory/allocator output, worked example, and CC-5 summary output.

### LT-2 — Overflow in custom synthetic payload counts silently changes the workload

- **Severity:** LOW. **Evidence:** CONFIRMED.
- **Sources:** `tools/tiplog_bench/main.cpp:281-299`, especially unchecked
  `result.total += tb::number(count)` at line 294; the resulting cumulative array
  is passed to `std::upper_bound` at lines 436-438. Contrast the already checked
  count accumulation in `bench/micro/publish_bench.cpp:71-76`.
- **Trigger:** CSV `A,12,9223372036854775809` and
  `B,64,9223372036854775809` after the normal header. Each integer individually
  fits uint64, but their total does not. The intended relative weights are equal.
- **Observed:** The cumulative sum wraps to 2; the array becomes
  `[9223372036854775809, 2]` and no longer represents the intended distribution.
  For the executed draws 0/1 both entries exceed the draw, so this particular
  reproduction does not require a query-specific search-precondition violation.
  The executable returns 0 and reports status `ok`. With 100 records it produces
  `head_pos=3200`, i.e. 100 records of aligned size 32, so every chosen payload
  has length 12. Replacing both counts with 1 (exact same relative distribution
  and the same total modulo uint64, so identical bounded RNG draws) yields
  `head_pos=5568`, with both lengths represented.
  Evidence: `overflow_mix.csv`, `equal_mix.csv`, `bench_overflow_mix.json`,
  `bench_equal_mix.json`, and both `*_mix_output.jsonl` files.
- **Impact:** A malformed/custom input can generate a different size/retention/
  publication-cost workload while being labelled successful. The checked-in
  empirical mix has not been shown to overflow.
- **Recommendation:** Reject `count > UINT64_MAX - total` before accumulation;
  validate the mix header and all row lengths/counts before generating records.
  Reuse a single validated mix-input contract across the two C++ harnesses.
- **Meaningful validation:** Overflowing cumulative counts must fail before
  publishing; valid equal weights and skewed weights still yield deterministic
  schedule/hash results; boundary totals equal to UINT64_MAX are handled safely.

### LT-3 — Recording backend accepts NaN and emits invalid JSON

- **Severity:** LOW. **Evidence:** CONFIRMED.
- **Sources:** `tools/tiplog_sim/main.cpp:24-31` parses floating input without a
  finite/range check; line 99 assigns the option. Engine validation lives in
  `src/tiplog/engine/engine.cpp:40-42`, but the recording branch at simulator
  lines 185-192 constructs no Engine. The raw double is emitted at lines 252-253.
- **Trigger:** `tiplog_sim --trace tests/fuzz/corpus/trace_reader/empty.mdt
  --backend recording --auto-max-index-fraction nan`.
- **Observed:** Exit 0 and stdout contains `"auto_max_index_fraction":nan`,
  which is not a JSON number. `recording_nan_json.json` retains the command and
  complete stdout. Engine backend rejects this configuration, so the defect is
  specifically reachable through the recording backend.
- **Impact:** A successful simulator command can break a strict downstream JSON
  parser; invalid finite ranges are also accepted on that backend.
- **Recommendation:** Validate finite `[0,1]` fractions at option parsing, shared
  across backends; never serialize nonfinite numbers as raw JSON tokens.
- **Meaningful validation:** NaN, infinity, negative values, and values above 1
  fail consistently for both backends; endpoints 0 and 1 produce valid JSON.

## Code-confirmed review items / optimizations (not reproduced engine defects)

1. **Benchmark validation exceptions are labelled `invalid_config`.**
   `tools/tiplog_bench/main.cpp:843-849` throws `logic_error` for timed/untimed
   replay disagreement, but the broad catch at 866-874 emits `invalid_config`
   and continues to eventual exit 0. Allocation and unexpected runtime failures
   in that block have the same classification. Consider a separate
   `validation_failure`/`runtime_error` status and nonzero overall result;
   reserve `invalid_config` for known validation exceptions. A controlled injected
   replay mismatch would be the meaningful regression test. Coordinate with the
   Python experiment audit before deciding whether downstream validation already
   prevents a failed arm from being accepted. No actual mismatch was found.

2. **M3 eagerly builds and retains all four indexes before Google Benchmark
   filtering.** `bench/micro/index_bench.cpp:231-239` builds B=64/256/1024/4096
   and scans every index before `benchmark::Initialize` / argument filtering at
   272-274. A user selecting one arm still pays four index constructions and
   retains all four pools. `Data::chronological` stores an additional 16-byte
   pair per posting and `lists` an additional 8-byte position per posting
   (before vector spare capacity); these arrays remain resident during timing
   although only their sizes, query/reference hashes, and query vectors are
   needed then. For the documented 32.8M-posting fixture, these reference
   postings alone require at least ~787 MB decimal, with vector capacity adding
   more; four index posting pools add at least another ~525 MB decimal.
   Consider initializing/filtering first, constructing selected B fixtures,
   releasing build-only reference data, and/or isolating B arms in processes.
   This is a concrete memory/startup optimization, not evidence that the saved
   hot-loop timings or explicit Index-memory counters are incorrect.

3. **`--measure-prefill` has no effect.** `tools/tiplog_bench/main.cpp:63,86-88`
   stores it but no other code reads the flag. Prefill is measured unconditionally.
   Remove the flag or define/test its actual behavior; LOW CLI clarity item.

4. **Global input memory is bounded per curve, not per run.**
   `tools/tiplog_layout/main.cpp:393-397` (runtime frontend equivalent:
   505-509) allows up to `--max-states` entries in each curve while retaining
   every curve in `GlobalInput`. Many tiny CURVE declarations with large
   maximum_count can allocate arbitrary aggregate memory. Default 2M entries
   means ~32 MB per curve (16-byte Cost). Consider an aggregate entry/byte budget
   when exposing this offline tool to untrusted input. No destructive memory
   exhaustion run was performed. This is not a failure of the exact DP state cap.

## Negative results, scope qualifications, and report errata

- Every assigned production file was read: all six `layout/*`, four `trace/*`,
  nine tool `.cpp` files, `tools/tiplog_bench/contracts.hpp`, and all four
  `bench/micro/*` files. Relevant layout, trace and benchmark-contract tests were
  inspected. No new solver optimum/reconstruction mismatch, trace bounds error,
  or ITCH chunking defect was established.
- **Preprocessing is outside solver time limits:** Valid 12k-node/12k-class
  cases in `prepare_12000.tsv` return `representation_limit` with zero solver
  work after the uncapped O(nodes × classes × terms) prepare loop at
  `model.cpp:273-283`. The diagnostic process time is ~0.3 s while reported
  solver time is ~30 µs even with `--time-limit-ms 1 --max-work 1`.
  However, `docs/report/results_layout.md:370-385` explicitly excludes
  preparation and independent materialization from reported solver timing.
  Therefore this is an end-to-end resource limitation / possible future
  input-size budget, **not a contradiction of recorded runtime claims**.
  No larger stress run is needed. See `prepare_*.json`.
- `Reader` validates the complete immutable mapped trace before honoring
  CLI record-count limits; repeated calls also recheck per-record headers/padding.
  This is a deliberate validated-input contract, not a new correctness defect.
  Header+dictionary-only lazy streaming would need a separate explicit trust
  mode rather than silently weakening this contract.
- The hard-coded CPU2 frequency path is explicitly disclosed by microbenchmark
  metadata and runtime frontend help, and the controlled protocol pins CPU2.
  Do not call that a flaw in the recorded pinned campaigns.
- Existing report R-ITCH-1 says `terminator ⇒ incomplete`; it should say
  **missing terminator ⇒ incomplete**. Both implementations and tests agree on
  that behavior (`itch_walker.cpp:102-104`, `protocol.py:118-150`). This is a
  report typo, not a new code issue.
- C++ walker errors also lack byte offsets (`itch_walker.cpp:58-81`), consistent
  with the general malformed-ITCH diagnostic gap already covered by AUD-005;
  extend that item's scope if useful rather than assigning a duplicate finding.

## Feature recommendation from this scope

For project performance work, a resource-aware workload preflight is more
valuable than another merge kernel: report predicted ring/index/fixture bytes,
exact-method eligibility, and which input/setup costs are outside measured
intervals before a long campaign starts. It should reject invalid distributions
and bound aggregate fixture/input allocation. This remains a suggestion; the
parent audit should choose one project-wide feature after combining all scopes.
