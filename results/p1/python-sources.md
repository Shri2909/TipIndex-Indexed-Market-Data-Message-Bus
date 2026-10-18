# P1 Python source inspection and implementation traceability

Inspected **2026-10-17** for approved v1.1 / Tier B P1. Source documents are reference material. All code here is an independent implementation; no third-party parser/source implementation was copied, so there is no reused-code revision or license notice to attribute. Nasdaq's protocol authority does not imply endorsement of the project. Jane Street's unpublished Aria implementation is not an input to these parsers or hierarchies.

| Source | Original material actually inspected | Revision/access limitation | Applied decision |
|---|---|---|---|
| S05 [Nasdaq TotalView-ITCH 5.0](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf) | Overview, Architecture, Data Types; message tables §§1.1–1.8 (printed pp. 3–20); latest Appendix A revision entry (p. 22); Appendix B symbol convention (p. 31). Inspected the original PDF's extracted tables, including all 23 supported message layouts and the distinct L/A/F/P/Q/I symbol offsets. | PDF served at the official URL on the access date; latest listed protocol revision **2023-04-28**. No claim of reading unrelated appendices C–E or the complete historical revision log. No source-code reference used. | Exact lengths; unsigned big-endian fields and scaled integer prices; nanosecond timestamps; day-specific directory; K by symbol; market-wide controls; preserve payload bytes. |
| S06 [Nasdaq BinaryFILE 1.00](https://www.nasdaqtrader.com/content/technicalSupport/specifications/dataproducts/binaryfile.pdf) | Complete two-page document, particularly §§1.1–1.2 and revision history. | Revision history 2008-12-31 / 2010-03-30. Nasdaq's two-byte framing is distinct from this project's little-endian trace format. | Zero-length session terminator; EOF without terminator explicitly incomplete; truncated length/payload fail; bytes following the terminator fail. |
| S54 [RFC 1952](https://www.rfc-editor.org/rfc/rfc1952.html) | §§2.2–2.3.1, member structure, CRC32 and ISIZE definitions. | May 1996. Initial `.txt` web fetch failed; official HTML was inspected successfully. | Count bytes through the full decompressed stream; consume the underlying gzip EOF and propagate decompressor errors. ISIZE is never used to infer full-day size. |

The saved research's limitations for papers and external implementations remain unchanged. No new dependency, protocol extension, book reconstruction, engine algorithm or later-phase experiment is introduced.

## Finding → decision/task → code → validation → executed evidence

| Finding | Approved decision/task | Code file/symbol | Check | Actual evidence/status |
|---|---|---|---|---|
| Inventory #1 / S05 | Validate all 23 types; P1.3/P1.4 | `py/tiplog_py/itch/protocol.py::{LENGTHS,FIELDS,parse_message}` | V01 independent hand-encoded structs/field values for every type | `results/p1/python-unit-tests.log`: 23 parametrized golden tests pass within the latest 68-test run |
| Inventory #2 / S06 | Strict bounded streaming framing, explicit incomplete status; P1.2–P1.4 | `protocol.py::BinaryFileReader` | V02 chunk boundaries, missing/zero terminator, malformed lengths/types, truncation, trailing bytes | Same log: passed; actual real-data completeness remains a separate root-orchestrated gate |
| Inventory #3 / S05 | Day-specific locate mapping; K symbol route, controls, unknown-locate fallback; P1.3/P1.4 | `routing.py::{Router,encode_symbol}` | V03 golden routes, late directory, mixed symbol offsets, mismatches, percent encoding | Same log: passed. Unknown/mismatch real-day counts must come from measurement |
| Inventory #4 / S54 / L1 | Complete stream counts, burst/run/skew and tree/class characterization; P1.2/P1.7 | `characterize.py::{Statistics,write_tables,inequality}`, `itch/__main__.py::measure` | Synthetic totals, windows and preserved timestamp inversions; real full-day independent comparison is V04/CC-6 | Synthetic integration tests passed. No full-day run performed by this agent; root owns actual acquisition/count reconciliation |
| Inventory #5 / DD-17 | Portable trace v1, deterministic bytes and checked provenance; P1.3/P1.6 | `trace/format.py::{TraceWriter,TraceReader}`, `itch/__main__.py::convert` | V05 byte-level golden, all truncated prefixes, malformed offsets/flags/dictionary, source-hash rejection, Python writer → independent C++ reader | Same log: passed including `build/release/tiplog_trace_check`; synthetic RC-2 repeat passed. Real source repeat and F1 timed evidence remain root-orchestrated |
| Inventory #6 / approved H-spec + H-flat | Preserve both hierarchies with identical original payload/order; P1.3/P1.7 | `routing.py::Router`, dual-output converter, topic-volume CSVs | Golden H-flat route and dual conversion under inverted timestamps | Same log: passed; production commands choose explicit 09:30–10:00 window |
| L1/F01–F05 | Scripted descriptive plots from actual saved aggregates | `figures/build.py::build` | Saved counts/volume CSVs → five PNG and five PDF artifacts | Synthetic 1005-message figure smoke passed: `results/p1/python-figure-smoke.json`. Real-data execution pending in this agent's evidence; root will update gate status with actual artifacts |

## Reproduction interfaces

Use the P0 venv with `PYTHONPATH=py`. These examples are commands, not a claim they have all run:

```bash
PYTHONPATH=py .venv/bin/python -m tiplog_py.itch measure data/raw/12302019.NASDAQ_ITCH50.gz --output results/data/itch_20191230_counts.json --volumes-dir results/data --start 09:30:00 --end 10:00:00
PYTHONPATH=py .venv/bin/python -m tiplog_py.itch convert data/raw/12302019.NASDAQ_ITCH50.gz --output data/traces/itch_20191230_H-spec.tpl --also-flat data/traces/itch_20191230_H-flat.tpl --start 09:30:00 --end 10:00:00
PYTHONPATH=py .venv/bin/python -m tiplog_py.figures.build --all
.venv/bin/python -m pytest -c py/pytest.ini py/tests/test_itch_protocol.py py/tests/test_itch_routing.py py/tests/test_itch_cli.py py/tests/test_trace_format.py -q
```

Every conversion hashes the actual compressed input and rejects a supplied source SHA-256 mismatch. Normal conversion scans the complete stream, selecting `[start,end)` by timestamp while preserving source order even if later timestamps invert into the window. There is no early-end shortcut. `--limit-bytes N` is only an explicitly **limited/incomplete throughput diagnostic** and stops at a complete framed message boundary; it is never a complete-day result. Buffered reads may read ahead less than a chunk. Final metadata records the actual bytes/messages consumed, elapsed boundary, routing anomalies, hierarchy and source/trace identities.

`convert --counts-output results/data/itch_20191230_counts.json --volumes-dir results/data` optionally combines the full-day aggregate pass with conversion. Its counts/window/tables equal the separate `measure` path; a synthetic comparison ignores only the deliberately different timing/boundary/source-hash fields. Dual-output conversion routes the source once under H-spec and derives each selected H-flat path from the same symbol/market/unmapped route, retaining identical payload order. This avoids an otherwise redundant full-day routing pass. Production explicitly selects 09:30–10:00 to end at the planned future T1 anchor; no P6 experiment runs during P1.

`framed_bytes` means the original `payload+2` BinaryFILE representation and reconciles directly with the independent C++ walker. `record_bytes` means `align8(16+payload)` for the project's trace/DATA framing, excluding a future ring's wrap PAD. Both are recorded, avoiding an ambiguous optimizer byte model. Partition complexity CSVs report active raw workload counts and distinct nonempty local match-set counts; these are descriptive P1 quantities, not a claim that P7 exact solvers cover every partition or that a class-coalescing optimization has been authorized.

## Commands actually run by the Python implementation agent

- `.venv/bin/python -m pytest -c py/pytest.ini py/tests/test_itch_protocol.py py/tests/test_itch_routing.py py/tests/test_itch_cli.py py/tests/test_trace_format.py -q` — initial 64 tests passed; after identity/combined-pass regressions, **68 passed in 0.15 s**, exit 0. The latest output is saved in `results/p1/python-unit-tests.log`.
- Synthetic figure smoke: generated 5 directory messages and 1000 D/E messages in a temporary gzip, ran `measure` and `figures.build::build`, verified **5 PNG + 5 PDF**, exit 0. `results/p1/python-figure-smoke.json` identifies the synthetic inputs/artifacts. Matplotlib used its `/tmp` cache fallback because the home config directory is read-only; production may set a writable `MPLCONFIGDIR`. The smoke does not establish real-data figures or timing.
- Original sources were inspected through the web reader at the URLs/sections above. No external implementation was downloaded or reused.

These tests do not establish real-data CC-6, actual full-day RC-2 or the timed F1 gate. Those must be linked to the root's separate executed evidence before P1 can pass.
