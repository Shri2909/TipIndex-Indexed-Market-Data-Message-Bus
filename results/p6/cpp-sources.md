# P6 C++ experiment support: source and contract ledger

2026-10-19. This is original project implementation within approved v1.1 Tier B.
No Jane Street or other reference implementation was copied. No unpublished
Aria algorithm or machine-code performance property is assumed.

The P5 gate and its source/method ledgers were inspected before adding these
tools. P5 is passed; older pending paragraphs in its development notes are
historical. Engine observer additions require the affected acceptance checks
to be rerun against the final instrumented source; prior timings are not
silently treated as timings of this new executable.

## Original material actually inspected

- NIST FIPS PUB 180-4, August 2015, official PDF
  <https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.180-4.pdf>:
  SHA-256 functions §4.1.2, constants §4.2.2, padding §5.1.1,
  parsing §5.2.1, initial state §5.3.3 and computation §§6.2–6.2.2.
  Accessed 2026-10-19. Scope is the hash implementation only; this is not
  a NIST-validated cryptographic module or security claim. Constants and
  algorithm are attributed to the standard; no source implementation reused.
- Installed glibc 2.43 `/usr/include/malloc.h` lines 80–118: exact
  `mallinfo2` field types and declaration. Reuses the previously inspected
  official glibc manual and its limitations in
  [P4 allocator ledger](../p4/memory-sources.md). No allocator tuning or
  implementation code reused. The local header identity is captured below
  in the implementation evidence manifest rather than inferred from a version.
- Pinned Google Benchmark v1.9.5 original header `benchmark.h`:
  `State::error_occurred`, `RegisterBenchmark`, adaptive iteration API;
  revision **192ef10025eb2c4cdd392bc502f0c852196baa48**. The detailed original
  timer/interleaving source inspection and hashes remain in
  [P5 method reading](../p4/p5-method-reading.json). Setup before the state
  loop is excluded; iteration-capped runs are not substituted for adaptive
  measurement. Internal randomization has no exposed seed.
- LLVM Benchmarking tips official current page
  <https://llvm.org/docs/Benchmarking.html>, Introduction, General, Linux and
  Linux Intel body (page lines306–365), accessed 2026-10-19; page marked
  updated2026-10-18. Initial navigation-only retrieval was followed by the
  complete relevant body. It separates noise from bias and discusses repeated
  measurements, affinity, frequency/ASLR/SMT controls. These are reference
  recommendations: the approved no-privilege fallback governs actual controls;
  no privileged settings were changed or low-variance guarantee transferred.
- Local design requirements actually read: PHASES_6_TO_8 implementation
  prompt in full; VALIDATION §§5–7, experiment/figure tables; ARCHITECTURE
  replay/index contracts; STUDY ST-12; existing P4/P5 source ledgers and
  complete current `Engine`, `Replay`, `Ring`, `Index`, `Registry` headers
  and replay loops.

## Finding → decision → implementation → validation

| Finding/contract | Decision/task and code | Validation and evidence status |
|---|---|---|
| V27/CC-4; independent trace oracle | `tools/tiplog_bench/main.cpp::drain`: timed bytewise FNV1a over u64 little-endian sequence then payload. A separate untimed replay computes SHA-256 of the sequence list and concatenated raw payload; count, sink, outcome, checkpoint and work must match | `bench_contract` tests pin endian/hash/sink, empty/abc/million-a and padding boundaries. Independent Python trace/synthetic oracle compares every configuration; root records actual executed evidence |
| FIPS 180-4 §§4–6 | `tools/tiplog_bench/contracts.hpp::Sha256`, no new dependency; hashing outside timed replay | Exact known-vector tests plus Python hashlib comparisons in phase integration. Current code is not claimed validated until executed |
| T1–T3 same resources, bounded snapshot, v1.1 outcome-aware accounting | One prefilled immutable Engine/process; shuffled request list; identical output sink across Scan/Indexed/Auto and four kernels. Request and actual effective mode both emitted; full checkpoint/error and expiry retained | Root runs final release/ASan tests, CC-2/F3 affected regressions and independent CC-4; tooling does not drop expired configurations |
| T1 work metrics, no hardware-counter claims | `ReplayWork` in `src/tiplog/engine/engine.hpp/.cpp`: actual replay-loop decoded record spans, DATA fetches, popped postings, delivered, PADs; separate ring seek header counts and index seek calls | Exact counter tests cover Scan/all four kernels, zero budget, move, completion, initial expiry and wide fallback. Bytes are logical decoded spans, not physical bytes or CPU cache traffic. Index seek comparisons and Auto estimate work are not guessed |
| VALIDATION §7 open→Done timing | Vector reserve, subscription compilation, cache treatment, source loading, SHA checks and JSON serialization outside timer; per reader clocks begin immediately before `open_replay` and end after final output sink/Done | Source review and independent timer-boundary inspection; process clock and wall clock reported, no request-latency distribution claim |
| VALIDATION §§5.3/5.5 cache and failure protocol | `main`: repeat-warm executes same replay once before measured replay; scratch treatment writes/reads a 64 MiB buffer at sequential 64-byte strides before timing; every result and rejected request written to JSONL | Access order and size declared; scratch treatment does not prove target cache cold. Parent protocol handles distinct process rounds, affinity/AC/frequency and non-ok accounting |
| T2 writer cost must be measured on same real window | `load`: separate real-window publish wall/CPU diagnostic, same input traversal and seq/payload sink for index on/off; excludes trace validation and topic registration. Emit diagnostic even with no replay requests | Matched real trace/C/B/anchor/index-on-off process rows; Python adds measured CPU difference to reader totals. Synthetic M2 is not substituted for this contribution |
| T3 declared deterministic generator | `load` uses fixed integer SplitMix64-style mixer constants; rejection bounded RNG; Bernoulli switch probability 1/L and forced different owner; stationary Zipf no-self interval rotation; 3 event probabilities .01/.09/.90; measured ITCH size mix | Independently implemented Python generator and CC-4, seed/parameters, full owner counts/hash and actual run count/mean recorded. This is synthetic, not a claim of exchange traffic realism |
| M3 real ITCH partition sizes and interleaving | `bench/micro/index_bench.cpp`: independent chronological trace framing positions and per-partition posting arrays; shared immutable indexes B64/256/1024/4096; exact lower_bound query and complete per-partition scan hashes | 4096 predeclared seek queries; full input scan outputs; preflight checks all B, independent list reference and recount; raw GBench rows normalize by operations_per_iteration |
| T5 full memory accounting, H4 | `memory`: real trace schedule, all exact pool/list/heap metadata gauges, independent recount, high-water, ring/checkpoint/registry counts | Structural invariants and exact gauges/memory recount; allocator value explicitly separate from portable subtotal |
| Allocator boundaries cannot be inferred from portable requested bytes | `allocator`: store actual partition/position/tail/eviction/retained-count transitions; destroy initial Engine; reconstruct Index alone within `mallinfo2` boundary, checking complete final Stats equality | Raw before/after and signed allocator charge-minus-reserved delta, no clamping. Existing schedule, trace mapping/output objects outside boundary; no Ring/Registry, RSS or per-object-header claim. Unsupported ASan/non-glibc rejected |

## Stable CLI contract

`tiplog_bench --trace PATH|--synthetic --requests TSV --output JSONL`
accepts `--records`, `--anchor-ts` (exclude timestamps greater than or equal
to anchor), `--ring-bytes`, `--block-entries`, `--index-enabled 0|1`,
`--auto-max-partitions`, `--auto-max-fraction`, `--seed`, `--partitions`,
`--zipf`, `--run-length`, and `--mix`. Output appends; callers use a unique
path per process. `--memory` emits T5 gauges; `--allocator-replay` performs
the separate allocator observation. `--measure-prefill` is accepted for
explicit caller intent; the prefill diagnostic is always retained.

Optional `--term-dictionary PATH` accepts a headerless UTF-8 text file of
`lowercase-SHA256-of-term-string<TAB>actual-semicolon-separated-terms` lines.
TSV `terms` can then be `@` followed by that 64-digit identifier. The parser
validates identifiers and their SHA-256 content binding, rejects duplicate or
malformed dictionary lines before loading the workload, and resolves aliases
before subscription preparation. Missing aliases become per-request
`invalid_config` rows. Direct terms retain their existing interpretation.

TSV columns, in order: `id`, `experiment`, `after_seq`, `terms`, `mode`,
`kernel`, `cache`, `batch`, `readers`. Header row is optional. Terms are
semicolon-separated `exact:path` or `subtree:path`. Modes are lowercase
`scan/indexed/auto`, kernels `stdpq/binheap/quad/loser`, cache treatments
`repeat-warm/scratch-thrashed`. For W2 T2, submit distinct independently
sampled requests (`readers=1`) and aggregate the declared group; `readers`
greater than one repeats the identical subscription and is not a W2 sampler.

M3 is an index-only measurement over the selected trace's complete chronological
posting schedule, using aligned DATA sizes and no Ring/PAD/eviction. Its
per-partition counts therefore match the selected input limit, rather than an
invented C1GiB retained subset. It does not measure record-payload fetches or
end-to-end replay; those costs belong to T1/T3. Four B variants coexist as
immutable inputs so each is measured against the same process resource setup.

Synthetic random draws per sequence: sequence one selects owner without
drawing a run-switch; later records first draw `bounded(L)` and switch to a
different owner only when zero. Initial owner uses `bounded(P)` for Zipf zero,
or `u=(next>>11)*2^-53` and the first normalized CDF entry strictly above u.
For subsequent uniform switches, draw `bounded(P-1)` and skip the old rank.
For Zipf switches, let the old owner's normalized CDF interval be [left,right),
and a be the maximum CDF interval width. Draw two independent unit values,
set `point=min(nextafter(right,left),left+u1*(right-left))`,
`shift=a+u2*(1-2*a)`, and `rotated=(point+shift) mod 1` (subtract one once
when greater than or equal to one); choose the first CDF entry above rotated.
The tool asserts the resulting owner differs, and rejects a≥1/2 or P<2.
All approved P/Zipf cases meet the precondition. This independent project
construction preserves stationary Zipf marginals: conditioning on an owner
with its interval probability makes point uniform on the circle; an
independent rotation preserves the uniform marginal. Intervals have width
at most a and shifts lie in [a,1-a], so an interval cannot overlap its
shifted point in exact arithmetic. The explicit endpoint rule and runtime
assertion qualify floating arithmetic; no uninspected published algorithm
is attributed with this construction. Bernoulli switches now give geometric
same-owner runs of mean L, rather than geometric redraw segments that could
merge. Actual run counts/means and full owner marginals remain measured.
Then draw `bounded(100)` (events e0 below1/e1 below10/e2 otherwise), then
`bounded(sum(empirical type counts))` for size in CSV order. Paths are
`synth/p{owner}/e{event}`; payload byte i is
`(seed + seq*17 + i*31) & 255`. Arithmetic RNG wraps u64. Python uses its
own implementation of this written contract, not generated engine output.

Executed checks for this subtask before integration: strict GCC syntax-only
compilation of all three new translation units passed. Full builds, tests,
functional real/synthetic digest checks, campaigns and terminal audits are
recorded by the phase controller; this ledger does not pre-label them passed.

Executed integration checks now inspected: [release163/163](release-tests-observer-20261019T012930.012253Z.json)
and [ASan/UBSan163/163](sanitizer-tests-observer-20261019T012938.955831Z.json)
passed, including all six new digest/work-contract tests. These tests exercise
the unchanged final observer/header/test sources. Later tool-only synthetic
coupling and metadata refinements require its rebuilt functional oracle checks;
the earlier unit suite is not represented as exercising those CLI paths.

## M3 input/audit integration — 2026-10-23

`index_bench::run` now uses the complete `State::name()` in invocation logs,
including `/B64`, `/B256`, `/B1024` or `/B4096`. Before the state loop it
appends one `TIPLOG_BENCH_INPUTS` JSON object and attaches the same object as
the Google Benchmark label. It declares actual operation count, input record
count, diagnostic/truncation status, B, trace path/size/limit, chronological
posting-input word hash, query-input word hash and independently computed
expected output word hash. This makes the phase controller's raw invocation
audit possible without reconstructing expected output from the index under
test. The declared word hash is the existing original project
`word-xor-multiply64-v1`, not the bytewise replay FNV or a cryptographic hash;
the complete trace SHA-256 remains part of campaign provenance. Every hash
and input object is prepared outside the timed state loop. `--verify-only`
exposes all eight objects without executing a timing campaign.

The new functional evidence helper
[`cpp-final-m3-check.py`](cpp-final-m3-check.py) imports no production modules.
It independently encodes a 16-record synthetic trace, models six partitions
(including an unused ancestor), reconstructs aligned posting positions and
4096 deterministic lower-bound queries, then checks all eight profiles for
both complete and seven-record selections. Its integer RNG separately
implements the written generator contract. Empty selection must fail
explicitly. These checks qualify the fixture and metadata integration;
they do not substitute for full-real-input M3 measurements or their audit.

Executed final checks:

- [Release target build](cpp-final-metadata-release-build-20261023T143233.049261Z.json):
  `tiplog_bench`, `index_bench` and `tiplog_bench_contract_test` built, exit 0.
  The log contains one GNU Make jobserver FIFO-exists diagnostic; it contains
  no C++ compiler diagnostic and the complete target build succeeded.
- [ASan/UBSan target build](cpp-final-metadata-sanitizer-build-20261023T143233.019930Z.json):
  the same targets built, exit 0.
- [Independent release fixture](cpp-final-m3-reference-release-20261023T143324.694615Z.json):
  193 checks passed; [complete audit](cpp-final-m3-release-reference.json).
- [Independent ASan/UBSan fixture](cpp-final-m3-reference-sanitizer-20261023T143334.436237Z.json):
  193 checks passed outside tracing, with leak detection and halt-on-UB retained;
  [complete audit](cpp-final-m3-sanitizer-reference.json).

The final main-tool review also inspected prefill process/user/system clocks,
CPU/frequency endpoints and the immutable-registry compiled-subscription
cache. Cache lookup/compilation remains outside each replay timer and every
measured request still opens a fresh captured replay. Those unchanged
tool paths are built here; the controller's independent trace/synthetic
oracle checks remain the acceptance evidence for their outputs.

## Deterministic preparation and compact term input — 2026-10-23

The preceding immutable-registry comment was insufficient: incrementally
compiling new request strings could intern missing zero-volume topic roots
between timed arms. `main` now collects all distinct decoded term strings in
a sorted map, compiles every one before the first warm-up or measurement,
and retains compilation errors for the existing per-request `invalid_config`
path. Every request thereafter only looks up its prepared subscription.
Earlier prepared subtree observers receive any later setup-time topic
creations before timing starts. This preserves future-topic semantics while
making IDs, hooks, filters and registry resources independent of shuffled arm
order. Prefill output declares post-preparation registry counts, observer
count and the SHA-256 of `(topic-id u64LE, path-byte-length u64LE, UTF-8 path)`
in registry order. Each replay/error row declares its registry gauges.

The required P100000 workload also exposed repeated large term strings in
per-round request TSVs. The optional content-bound dictionary above stores
each unique term string once per workload; all aliases resolve to the same
literal terms before sorted preparation. This is input-storage plumbing,
not a change to subscription unions, timing boundaries, repetition counts or
the required matrix. The Python driver retains dictionary/input identities.
No new dependency or external implementation was added; SHA-256 uses the
already inspected FIPS 180-4 implementation documented above.

Finding/contract → decision/task → code → check → executed evidence:

- V27/CC-4 identical resources and shuffled order → settle all roots/plans
  before timing → `main::compiled`/`compilation_errors` preparation and
  `write_result` gauges → independent missing-exact/missing-subtree requests
  in both orders, checking exact registry-ID SHA, every gauge and replay hash
  → both functional audit records below passed.
- Existing disk budget plus full P100000 matrix → share content-bound terms
  without reducing observations → `term_dictionary`, `requests`,
  `Options::term_dictionary` → plain versus alias output equivalence and
  explicit malformed/duplicate/hash-mismatch/missing-alias cases → both
  functional audit records below passed.

Executed checks:

- [Release tool-only build](request-dictionary-release-build-20261023T144428.263660Z.json):
  passed, exit 0, no compiler diagnostic.
- [ASan/UBSan tool-only build](request-dictionary-sanitizer-build-20261023T144428.296303Z.json):
  passed, exit 0, no compiler diagnostic.
- [Release functional audit](request-precompile-dictionary-release-functional-20261023T144450.902132Z.json):
  **303 checks passed**; [full audit](request-precompile-dictionary-release-functional.json).
- [ASan/UBSan functional audit](request-precompile-dictionary-sanitizer-functional-20261023T144458.085177Z.json):
  **303 checks passed** outside tracing with leak/UB checks;
  [full audit](request-precompile-dictionary-sanitizer-functional.json).

The independent helper is
[`request-precompile-check.py`](request-precompile-check.py). It imports no
production module, encodes its own small trace, reconstructs registry prefix
insertion and ID hashes, checks expected replay sequence/payload SHA values,
and compares complete semantic rows across direct/alias × forward/reverse
inputs. Invalid term compilation remains per request. Missing/invalid aliases
also produce saved per-request errors; malformed dictionaries fail before
workload allocation. No output from these functional runs is included in a
timing campaign.

The first attempt
[request-precompile-release-functional-20261023T144219.998371Z.json](request-precompile-release-functional-20261023T144219.998371Z.json)
failed because the test fixture's short payloads violated the tool's declared
minimum 32-byte aligned DATA size. That rejection and raw fixture remain
preserved. The fixture was corrected to the existing bound; the production
bound was not weakened. No Engine, subscription or CMake source changed in
this tool-only integration, so the controller's concurrent core acceptance
campaign identities are unaffected. The full P100000 oracle regression and
campaign freeze remain controller-owned acceptance work.
