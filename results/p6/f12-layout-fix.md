# P6 figure presentation amendment — 2026-10-25

This amendment changes presentation only. No raw observation, input, timing,
ratio, confidence interval, statistical function, benchmark, C++ binary or
production experiment driver is changed. The original figure source/tests,
first actual figures/manifest and active provenance manifests are preserved in
[the before record](f12-layout-compatibility/before.json). Parent-owned
regeneration must verify numerical artifact hashes and inspect the actual plots.

## Findings, decisions and code

| Observed defect → decision | Implementation | Focused executed validation |
|---|---|---|
| Eight F12 arms occupy identical `(k,selectivity)` coordinates, hiding each other's colors → display eight distinct slots per categorical cell | `py/tiplog_py/figures/tip.py:_crossover_panel` and F12 rendering retain the existing traffic/cache facet key; assign four fixed kernel columns and two mode rows; retain true values as tick labels and metadata | Actual fixture scatter collections have 32 distinct positions for four cells × eight arms, with 31 colored ratios and one explicitly unavailable marker. Plotted log2 colors equal the original paired ratios. Input reordering leaves the mapping unchanged; ambiguous duplicate cell/arm input is rejected. |
| Failed/invalid pairs must remain visible without being represented as numeric speedups → gray crosses | F12 records each alternative's true coordinates, arm, ratio or null, pairing status and nonzero outcome counts. Existing incomplete-pair withholding remains. | An invalid-config fixture remains a gray unavailable point with null ratio and its status count. |
| F09/F10's 54 combined arm/family legend entries obscure plots; F11 draws two sets of arm/cost entries → factor the encoding | `_lines`/`_factorized_legend`: fixed requested-arm colors, family/cost markers and two compact legends. F11 accumulates both cost factors across calls without stacking stale legend artists. | All 54 arm/family curves, their x/y data and CI endpoints remain; two legends contain nine arm and six family entries. F11's two calls retain all 18 curves and two legends with nine arm/two cost entries. Arm colors agree across panels. |
| Actual F13 titles/footer extend outside their available area → wrap complete text and reserve footer height | F13 wraps long titles; `_save` wraps footers to figure width and sizes the bottom margin for their complete line count | Fixture footer is multiline with the same words as the complete original; F13 long titles wrap. Parent must visually inspect the actual regenerated images. |
| F13 nonnegative slot counts show an unnecessary negative symlog region → start that axis at zero | F13 slot-count axis has lower bound zero; the separate allocator-delta axis is unchanged | Every rendered fixture slot-count axis has lower bound zero. |

## F12 display contract

The number and identity of the 54 actual P/Zipf/run-length/cache facets are
unchanged. The true breadth and selectivity values become categorical tick
labels; spacing is explicitly labeled categorical. Within every cell:

- Left to right: StdPQ, BinHeap, Quad, Loser.
- Upper row: Indexed; lower row: Auto.
- Kernel x offsets: −0.27, −0.09, +0.09, +0.27 from the categorical center.
- Mode y offsets: +0.16 for Indexed and −0.16 for Auto.
- Color: the original log2(Scan CPU / requested-arm CPU) ratio, with the same
  shared symmetric color-limit calculation.
- Gray cross: unavailable paired ratio; no invented numeric value.

The figure title explains the subgrid, eliminating per-panel legends that
would cover its points. `figure_facets.F12` records per-point true coordinates,
display positions, arms, ratios and unavailable outcomes. `figure_layouts.F12`
records the ordering/offsets. Successful ratio configuration coverage retains
its existing meaning; unavailable crosses are separately explicit in the facet
point metadata. Baseline Scan configurations are recorded as references.

`factorized_legend_encoding` records the F09/F10/F11 arm order, fixed RGBA
colors and family/cost markers. Output filenames and the eight figure pairs
(16 PNG/PDF artifacts) remain unchanged. Complete numerical summaries and raw
evidence retain their original roles.

## Executed focused check and identities

```sh
PYTHONPATH=py .venv/bin/python scripts/run_check.py p6 figure-layout-focused-tests -- .venv/bin/python -m pytest py/tests/test_analysis_figures.py -q
```

Passed: **3 tests**, exit 0, pytest 4.77 seconds. These use explicit temporary
synthetic figure fixtures, not experimental observations.
[Command/status JSON](figure-layout-focused-tests-20261025T043234.286174Z.json),
[actual stdout](figure-layout-focused-tests-20261025T043234.286174Z.log).

Final source SHA-256:

- `py/tiplog_py/figures/tip.py`:
  `f156ad50beb039315b48c95a9e10772a4e4d2c4377951f76562619489e8d758f`.
- `py/tests/test_analysis_figures.py`:
  `5e1f0e84e70dfe84430fe6a92f9d49512de3c239cbc13a0440fd638bc04f49a8`.

The parent owns strict provenance compatibility, one-command actual
regeneration, numerical-hash comparison, visual review and the P6 gate.
Focused fixture success alone does not establish those pending checks.
