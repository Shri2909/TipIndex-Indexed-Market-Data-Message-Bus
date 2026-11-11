# Public checkout and local evidence

TipIndex keeps implementation, tests, small result summaries, figures and audit
records in Git. The source namespace, executable names and historical reports
retain the original name `tiplog`.

Build outputs, virtual environments, raw Nasdaq data, message-level traces and
large experiment files are ignored. Documentation labels paths to these files
**local-only**, rather than linking to absent files in a public checkout.
The [reproduction guide](REPRODUCE.md) describes their acquisition and identities.
The README's [compact comparison excerpt](../readme/replay-comparison.csv) and
[provenance](../readme/replay-comparison-provenance.json) expose its two historical
replay ratios without publishing the entire large derived CSV.

## Prompt files and historical source archives

Root-level prompt Markdown files are local-only. Two historical audit source
archives also contain copies of those prompts, so they are excluded from the
publishable tree. Their local bytes are preserved unchanged:

| Local archive | SHA-256 |
|---|---|
| `audit/independent-20261027T041900Z/final-source.tar` | `5f9482dbe73a70182c18a9a520da876bbbabcc9462dcf529e1bf0e0f2bd9ae1a` |
| `audit/independent-20261027T041900Z/initial/source-snapshot.tar` | `1817d584516c0ec345fab0144bf511adc05e6a71a885600ba3a3384f5bce2db9` |

The frozen audit manifests still identify the original archives. Reproducing
the full before/after audit requires these local files and the other declared
local inputs; a fresh public checkout alone is insufficient. They are not
rewritten to make a later source tree match historical acceptance.

This packaging policy does not remove content from earlier Git commits.

## Validation scope

Historical acceptance applies to its recorded source snapshot. Later code,
documentation and packaging changes require their own checks; they do not
renew the historical acceptance. Normal build and lightweight demonstrations
do not need the raw datasets or source archives. Audit binaries and fuzz
corpora that serve the preserved evidence remain in Git.
