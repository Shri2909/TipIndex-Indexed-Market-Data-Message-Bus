# README figure panels

These PNGs crop existing historical figures so their axes and legends remain
readable in the project README. They do not introduce measurements or change
the source plots. Original PNGs, PDFs, raw results and acceptance records are
preserved.

| Panel | Original | Pixel box (left, top, right, bottom) |
|---|---|---|
| [Replay breadth](replay-breadth.png) | [F09](../../results/figures/F09_catchup_breadth.png) | `(0, 0, 752, 552)` |
| [Publishing cost](publish-index-cost.png) | [F08](../../results/figures/F08_publish_index_cost.png) | `(1504, 2183, 2256, 2723)` |

Coordinates use the originals' native resolution, with right/bottom exclusive.
Recreate from the repository root with Python and Pillow (an optional plotting
dependency in [the analysis environment](../../py/requirements.txt)):

```python
from PIL import Image

Image.open("results/figures/F09_catchup_breadth.png").crop(
    (0, 0, 752, 552)
).save("docs/readme/replay-breadth.png")
Image.open("results/figures/F08_publish_index_cost.png").crop(
    (1504, 2183, 2256, 2723)
).save("docs/readme/publish-index-cost.png")
```

Measurement identities and numerical inputs are in the
[P6 figure manifest](../../results/figures/p6-figures.json) and
[engine result report](../report/results_tip.md). The README captions specify
the selected workloads; the unabridged figures retain the other configurations.

## Compact replay comparisons

[replay-comparison.csv](replay-comparison.csv) contains two unchanged rows from
the historical `results/derived/tip-paired-ratios.csv`, which is intentionally
ignored because of its size. The rows select Scan/Indexed BinHeap CPU ratios
for the spec-hierarchy, 1 GiB ring, 1,024-entry blocks, 10-second backlog,
repeat-warm BOOK-top1 and BOOK-top1000 subscriptions at the 10:00 anchor.

The [provenance record](replay-comparison-provenance.json) identifies the original
CSV hash, comparison IDs, source binary, dates and local raw paths. These are
presentation extracts, not new measurements or acceptance records. The linked
engine report explains the 20 paired process rounds, bootstrap intervals and
limitations. Restore the ignored inputs using the
[reproduction guide](../report/REPRODUCE.md) to recompute the full analysis.
