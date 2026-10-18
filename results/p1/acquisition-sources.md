# P1 acquisition source inspection

Accessed 2026-10-17. The [official Nasdaq listing](https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/)
still lists `12302019.NASDAQ_ITCH50.gz` at 3,524,013,057 bytes. Actual source URL,
HEAD headers (including Last-Modified, ETag and range support), complete-download
size, gzip integrity and SHA-256 are retained in `data/manifest.json` and the P1
acquisition logs. Listing metadata is not an independent cryptographic checksum.

Inspected the [original curl manual](https://curl.se/docs/manpage.html):
`--continue-at`, `--range`, `--fail`, `--retry-all-errors`, header output, and
range-resume handling. The implementation uses curl as an external transfer
tool, with original Python orchestration; no curl code was copied. Verified
HTTP206 Content-Range in a 1 MiB probe before using bounded parallel ranges.

`py/tiplog_py/data/fetch.py` preserves existing partial input; verifies each
range's exact Content-Range and size; assembles in byte order; validates the
complete gzip; and hashes the downloaded compressed stream. The final version
also bounds stalled/oversized responses, locks the destination and preserves
per-invocation command logs. Actual range commands from the first successful
transfer are saved in `range-acquisition-commands.json`; those invocations
predate the added defensive timeouts/size bound. Their responses were HTTP206
and exact-size verified before assembly. No source setting or external account
was modified.

The unknown sample redistribution terms remain a limitation from S08. Raw
inputs, chunks, prefix-pilot data and message-level traces stay inside ignored
`data/raw/` and `data/traces/`. Only aggregate metadata, checksums and logs are
intended for tracking. No data is published by these checks.
