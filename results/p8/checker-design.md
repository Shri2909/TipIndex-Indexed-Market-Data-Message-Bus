# Prepared closeout verification design

This is preparation for the authorized P7 → P8 sequence, not the P8 report,
acceptance gate, or a claim that either phase has passed. P7 studies were still
in progress when this checker was prepared. The authoritative instruction is
[the user authorization](../p7/authorization.txt); requirements remain
[the master prompt](../../MASTER_PROJECT_PROMPT.md), [plan INDEX](../../docs/plan/INDEX.md),
[PROGRESS](../../docs/plan/PROGRESS.md), [IMPLEMENTATION_PLAN §10.1/§11](../../docs/plan/IMPLEMENTATION_PLAN.md),
and [VALIDATION_PLAN §1.1](../../docs/plan/VALIDATION_PLAN.md).

`scripts/check_core_closeout.py` performs saved-evidence checks only. It does not
build, run CTest, fuzz, convert/download data, regenerate figures, time solvers,
stage files, commit, or alter managed Git metadata. Its only writes are the
requested checks JSON and artifact manifest. Run it after P7 passes, the final
documents exist, figure regeneration has actually executed, and final review
evidence has been recorded:

```sh
.venv/bin/python scripts/check_core_closeout.py
```

Default outputs are `results/p8/checks.json` and
`results/p8/artifact-manifest.json`. Exit 0 and `status=passed` require every
mandatory automated check to pass. Missing files, identities, contract entries,
or prerequisite gates yield exit 1 and `status=failed`. There is intentionally
no requirement for a P8 phase gate: write that gate only after this verification
and the final evidence review pass. A checker pass alone is not phase acceptance.

## Final review contract

Create `results/p8/acceptance-evidence.json` using this exact shape. The following
is a schema illustration with placeholders, not executed evidence:

```json
{
  "criteria": {
    "CC-1": {
      "status": "passed",
      "note": "Describe the final release/ASan full-suite scope and evidence applicability.",
      "evidence": [
        {"path": "results/p7/<actual-full-release-command>.json", "sha256": "<64 hex digits>"},
        {"path": "results/p7/<actual-full-asan-command>.json", "sha256": "<64 hex digits>"}
      ]
    },
    "CORE-1": {
      "status": "passed",
      "note": "Record the completed phase/task review.",
      "evidence": [{"path": "results/p7/phase-gate.json", "sha256": "<64 hex digits>"}]
    }
  },
  "final_identities": {
    "src/tiplog/layout/model.cpp": {"sha256": "<64 hex digits>", "bytes": 0},
    "docs/report/REPORT.md": {"sha256": "<64 hex digits>", "bytes": 0}
  },
  "figure_regeneration": {
    "command_record": {"path": "results/p8/<actual-regeneration-command>.json", "sha256": "<64 hex digits>"},
    "inputs": {"results/p7/analysis-inputs.json": "<64 hex digits>"},
    "outputs": {"results/figures/F01_itch_type_mix.png": "<64 hex digits>"}
  }
}
```

Every entry in `CC-1` … `CC-6`, `RC-1` … `RC-3`, and `CORE-1` … `CORE-8` is
mandatory. Each needs `status=passed`, a substantive scope/review `note`, and at
least one explicit `{path, sha256}` reference to executed evidence or an
evidence-backed review. JSON command evidence must have exit 0; saved `status`
fields must be `passed`. Referenced command logs should also be explicit evidence
references so their identities are bound by the contract. An unchanged historical
gate may be evidence when its dependency applicability is established. The
acceptance contract, checker outputs and future P8 gate cannot serve as their
own evidence.

| Contract item | IMPLEMENTATION_PLAN §10.1 requirement |
|---|---|
| CORE-1 | All core phase DoDs met; PROGRESS links executed evidence per phase |
| CORE-2 | CC-1–CC-6 and RC-1–RC-3 satisfied |
| CORE-3 | Every applicable fuzz target ran ≥30 minutes at its last gate; crashes resolved and regressed |
| CORE-4 | Every input has a checksum/local-data requirement; tracked packaging excludes raw and message-level data |
| CORE-5 | F01–F18 regenerate through `figures.build --all`; claims point to actual raw evidence |
| CORE-6 | Non-ok outcomes, uncertainty and failures reported; percentile and latency claims supported |
| CORE-7 | Optimizer claims follow ARCHITECTURE §6.9, exactness coverage is honest, worked example reproduced |
| CORE-8 | Report covers limitations/threats; resume numbers are supported or the bullets are removed |

CORE-5–CORE-8 need the saved claims/checklist review based on actual measured or
modeled results. File presence or matching hashes cannot verify the truth of a
scientific claim. The checker verifies that this explicit review and its
artifacts are recorded; it does not replace the review.

`final_identities` must cover every currently packaged source/documentation
identity listed in the artifact manifest's `source_and_documentation`. This
binds final code, build configuration, tests, checker, report, reproduction
guide, README and plan updates to the executed/reviewed snapshot. Complete and
review the final documents before creating this map. To obtain this map without
writing checker outputs, import the checker, construct `Audit` with the same
CLI defaults, call `packaging()`, and use
`audit.package["source_and_documentation"]`; this performs read-only inventory
and hashing. A preliminary full checker run can also provide the map, but its
result remains failed until every contract item and identity is valid.

The actual `figure_regeneration.command_record` must contain an executed argv
with `tiplog_py.figures.build` and `--all`, status passed and exit 0. Bind every
regeneration input manifest/summary actually consumed and all 36 F01–F18 PNG/PDF
outputs after the command. Include the command log's identity in RC-1 evidence.
The `outputs` map must additionally bind the regenerated current
`results/figures/p6-figures.json`; RC-1 evidence must explicitly bind
`results/p7/figure-extension-compatibility.json`. CORE-7 evidence must explicitly
bind the completed `results/p7/runtime-campaign.json`.
Use saved local data; no redownload/reconversion is required just to obtain fresh
evidence. P6 numerical inputs and the P1/P6 figure builder logic must remain
valid under the additive P7 dispatch.

## Automated applicability checks

- P0's accepted artifact checks and all-preset bootstrap summary, then P1–P7
  phase gates, must be present and passed. The gate chain is recorded explicitly
  as historical prerequisites. Explicit identity maps in historical gates are
  checked against their saved artifacts; historical gate status alone is not
  treated as final-source validation.
- [The pre-P7 baseline](../p7/baseline.json) pins the accepted P6 gate, master
  prompt, engine/parser/oracle/fuzz dependency files and all 19 core binaries.
  Their final hashes must agree. Managed `.git` stays empty and mode 0555.
- `CMakeLists.txt` may differ only by one additive P7 layout include; layout
  targets may link the layout/build-options/GTest dependencies, without an
  engine dependency. Original release and ASan compile-command entries must be
  byte-equivalent as JSON objects; only layout sources/tests/tools may be added.
- The original figure builder must remain AST-equivalent after removing the
  single P7 dispatch block. Its P6 numerical/source identities are preserved.
  The historical P6 figure manifest's raw hash is treated specially only under
  the mandatory compatibility proof described below; a mismatch is not ignored.
- CC-1 final evidence must include successful complete release and ASan CTest
  commands and logs with layout tests, a complete success summary and no
  sanitizer error signatures. Smoke or filtered CTest commands cannot satisfy it.
- CC-2 reuses the accepted 18-row final P6 matrix with the prescribed nine
  mode/kernel configurations, ≥1,000 release / ≥200 sanitizer seeds and ≥10,000
  operations per seed. CC-4 uses the accepted full-output/outcome audit.
- F1/F2 and the final F3 gates must retain their accepted durations ≥1,800 s,
  binary identities, gate identities and saved log identities. Final F3 dependency
  freeze and converter/parser identities are checked. Isolated optimizer work
  does not trigger another engine fuzz campaign when these identities remain
  valid. A dependency mismatch fails verification and requires an impact review.
- RC-3 verifies the accepted repeated GCC/Clang summary, 180 child record
  identities and current source dependencies. CC-6 verifies the independent
  per-type/per-locate count reconciliation and its count-input identities.
- RC-2 reuses actual accepted two-hierarchy repeat-conversion evidence with
  unchanged converter dependencies. The multi-gigabyte trace/source files are
  not read again solely to refresh an already accepted identity audit.
- P6's unchanged 5,364-file measurement inventory is preserved and checked as
  accepted evidence; the 4.1 GB campaign is not repeatedly rehashed. The data
  manifest and P1 gate must preserve the actual `incomplete=true` source state.
- CC-5 verifies both saved 10,000-instance exact comparisons, zero mismatches,
  every-applicable-k comparison accounting and deterministic release/ASan
  identities. Exact worked-example waste is checked directly. The mandatory P7
  gate and final review must additionally cover V28–V32/V39, threshold solving,
  global certificates, workload studies, resource caps and coverage limitations.

## Regenerated P6 figure-manifest compatibility

A legitimate `--all` regeneration can change Matplotlib PDF `/CreationDate`
metadata, which changes PDF hashes and therefore the P6 manifest's `artifacts`
hashes. Its historical raw hash is not expected to identify that regenerated
manifest. The checker requires the saved old
`results/p7/baseline-p6-figures.json` to match the original P6 manifest hash in
`results/p7/p6-figure-extension-baseline.json` before allowing this exception.

The saved `results/p7/figure-extension-compatibility.json` must be `passed`,
contain a nonempty all-passed check list covering every required comparison, and
have no failures. The closeout checker also independently repeats the limited
comparisons against the current artifacts: P6 numerical/source byte identity;
all 26 F01–F13 PNG/PDF baselines present; PNG byte identity; PDF identity after
normalizing **only** the `/CreationDate (D:...)` metadata; all P6 manifest fields
except `artifacts` equal; artifact names equal; and every current artifact hash
equal to its manifest entry. P6 raw-render baseline hashes must agree with the
preserved old manifest. The unchanged figure-builder AST remains a separate
mandatory check.

Only when all these checks pass can the old current-manifest byte-identity check
be replaced by this compatibility proof. Missing evidence, failed comparisons,
other PDF changes or numerical/semantic changes fail verification. The current
manifest and compatibility proof must then be explicitly hashed in final RC-1
evidence from the actual regeneration command. Historical evidence remains tied
to the preserved old manifest; final evidence identifies the regenerated one.

## Controlled P7 runtime evidence

The saved runtime supplement is mandatory for the final closeout check once its
artifacts exist. Missing or incomplete runtime artifacts fail verification; the
checker does not run the timing frontend, sleep through settling, regenerate
inputs or repair a campaign. It requires the compact runtime campaign to be
passed with all 11 rounds, exactly one warm-up and ten measured rounds, 900
configurations, 900 warm-up rows and 9,000 measured rows under the original caps.

Every accepted round must have matching accepted/status records, exit 0,
`controls_validated=true`, a complete actual settling block of at least 60 s,
an independently recorded fresh process launch, the DP-only cap-preserving argv,
valid process-boundary AC/frequency observations and no recorded overlap threat.
Current hashes must match the complete raw output, stdout/stderr log, GNU time
resources, process audit, shuffled order and compressed round input. Saved
failed/interrupted attempts remain explicit and their status identities are
checked; they cannot satisfy an accepted round. CPU-3 idle ratios remain
descriptive and do not establish an exclusive host.

The checker reads the 900 original synthetic DP reference rows and each saved
runtime output. It checks all 900 unique case IDs/order/metadata per round, every
child CPU/AC/frequency observation, outcome counts, the saved read/useful/curve
digest and exact objective/curve/store/read/useful/waste/touched/cut parity for
every case solved in both observations. Non-solved cap outcomes must retain
non-exact labels and no invented feasible metrics. The warm-up is excluded from
the 9,000 measured rows and 18,000 measured frequency samples.

All 9,000 measured frequency-flag entries must be retained with the actual raw
sample values. The checker recomputes the session median and each strict
greater-than-10% flag using exact rational comparison, checking flagged totals
and the retained-observation policy. It does not filter or replace noisy runs.
Source, binary, build, protocol, compiler/tool executable and reference-output
identities are checked against the completed campaign. The large original
metadata/TSV input hashes are reused from that completed before/after campaign
audit with their local presence recorded; the checker hashes compressed per-round
inputs instead of decompressing/re-hashing roughly 1.3 GB of repeated plaintext
inputs. The final contract explicitly binds the passed runtime campaign in
CORE-7 evidence.

## Link and packaging policy

The checker audits local inline/image/reference Markdown file links in the new
REPORT/REPRODUCE documents, README, INDEX, PROGRESS and existing report Markdown.
It ignores external/URI URLs, network URLs and anchor-only links, strips file
anchors/query suffixes, decodes URL paths, and skips fenced/inline code. It
checks target existence, not anchor spelling. The lightweight preparation audit
found no missing local targets in the existing README, INDEX, PROGRESS or
`docs/report/results_tip.md`. Current-status prose in INDEX/PROGRESS still
contains older finish-P6-and-stop wording; the final P8 documentation pass should
reconcile current status while preserving dated historical records.

If a real historical missing target appears, `--historical-links FILE` accepts
an explicit `historical_missing_links` map keyed `document::target` with an
honest explanation. Such defects appear as warnings and remain visible as
missing in the output; they never become valid evidence links. Missing local
links in REPORT/REPRODUCE always fail. No exception is enabled by default.

Read-only `scripts/git.sh ls-files` and `ls-files --others --exclude-standard`
inspect tracked files plus visible untracked core-owned paths. The inventory
records other untracked work separately without modifying it. Ignored raw data,
traces, raw measurements, real fuzz seeds/logs, managed metadata, nonregular
files and large artifacts are excluded. The default large-file threshold is
10 MiB. A tracked prohibited/large file fails the packaging check; excluded
untracked large aggregates remain available locally and their requirements must
be documented. Accepted tracked synthetic fuzz corpora are retained; untracked
corpus mutations are not automatically attributed to this phase.

No files are staged or deleted. This inventory is a reviewable local packaging
description, not publication. Source/document hashes exclude the generated
checks/manifest, acceptance contract and future P8 gate to avoid circular hashes.
The final P8 gate should bind the completed checker result and manifest only
after they exist and all mandatory review items pass.

## Preparation checks actually performed

Only syntax/schema inspection, small Markdown-parser examples, the current
additive figure-builder AST comparison and read-only packaging inventory were
performed during preparation. The full closeout checker was not run and no
`checks.json` or acceptance gate was produced. The first parser-example assertion
used an incorrect expected source line (7 instead of 6); correcting that expected
line made the example pass. The first packaging inventory identified an overly
broad filename rule: `results/p1/fuzz-F2-real-seed.json` is the accepted P1 seed
metadata record, not the real binary seed. The exception is limited to that exact
metadata path; actual real seeds remain excluded. The corrected inventory found
no tracked packaging violations. File counts are live inventory observations and
can change while P7 artifacts are still being written.

The later figure/runtime checker extension was syntax-inspected without running
the full checker or any campaign. A lightweight hash check confirmed that the
saved old P6 figure manifest matches its pre-extension baseline identity. No
compatibility result or runtime success was invented while those future
artifacts remained unavailable.
