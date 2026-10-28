# Reproduction and evidence identities

Run from `/home/abc/Desktop/Jane Street`. Use `scripts/git.sh` for this workspace. Do not rerun historical writers into accepted result paths. The current [acceptance.json](acceptance.json) binds the final [source freeze](source-freeze.json), [artifact manifest](artifact-manifest.json), and command/log records. GCC 15.2, Clang 21.1.8, CMake 4.4 and the project virtualenv were used; exact compiler executables, cache/compile flags and hashes are in each final build record. Initial environment capture and manifests are under `initial/` and `evidence/initial-environment-*`.

## Recheck the retained final evidence

```sh
.venv/bin/python audit/independent-20261027T041900Z/acceptance.py
```

This performs read-only source/binary/raw checks and reconstructs summaries; it writes only this run's current acceptance/artifact inventory. It intentionally rejects later source/build changes. It does not regenerate old phase gates.

## Rebuild/retest in a fresh evidence namespace

```sh
cmake --preset debug
cmake --build --preset debug --parallel 2
ctest --preset debug --parallel 2 --no-tests=error --output-junit /tmp/tiplog-debug.xml
# Repeat for release, asan-ubsan and fuzz.
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -c py/pytest.ini py/tests tests/scripts -q
.venv/bin/python -m pip check
.venv/bin/python scripts/check_p6_experiments.py --self-test
```

Keep ASan/UBSan/leak checks enabled. In this managed environment sanitizer execution used the tool approval mechanism to run outside tracing, with `ASAN_OPTIONS=detect_leaks=1:abort_on_error=1` and `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1`. Full-suite evidence requires explicitly empty/unset GoogleTest filter/shard/repeat/Bazel selection, CTest selection and pytest option/plugin variables, plus disabled plugin autoload. The recorder captures these settings rather than accepting missing metadata.

The exact independent campaigns are executable in [campaigns.py](campaigns.py): 1,000 Release and 200 sanitizer seeds, 10,000 operations/seed, all nine legacy pairs and the budget-aware model. Its saved summaries list each exact command and bound record. Choose a fresh directory/labels before rerunning: the original harness deliberately refuses existing corpus/evidence namespaces. Fuzz corpora are private copies (up to128 historical seeds/old target,64 deterministic new-grammar seeds); seeds and fuzzer arguments including fixed seed20261027 are in each record. Do not point fuzzers at historical corpora.

For standalone layout checks, use the exact argv in final-layout-* records with new output paths: `tiplog_layout_cc5 --instances 10000 --seed 20191230`; the worked example has its own frontend. Core failed-allocation reproducers, Python scalar/high-u64 controls, old-source red controls and dependency patch negative controls are retained under their respective evidence slices.

## Source, performance and preservation

The initial source archive plus auxiliary-source archive preserve pre-existing uncommitted source. `initial/status.txt`, `initial/diff.txt` and initial hashes describe it. The final source freeze/change inventory identifies this audit's edits without relying on HEAD alone. The actual pre-change benchmark was built from that initial archive, not selected as an API path on the changed binary. Its archive/compiler/flags/binary identities are in `evidence/layout_tools/baseline-poll-bench-identity.json`.

Both performance protocols were written before their timing. [run_performance.py](run_performance.py) and [performance_followup.py](performance_followup.py) retain original files, normalization maps, fresh process labels and host observations. They refuse existing output namespaces; choose new paths before repeating them. Every arm and non-winning result remains in PERFORMANCE.md and JSON evidence. These are shared-host diagnostics, not replacements for controlled P6/P7 historical measurements.

[verify_preservation.py](verify_preservation.py) rehashes the 4,262-file historical manifest and original 5,364-file P6 raw inventory, checking size/SHA-256/unique paths. The acceptance verifier independently rechecks these identities. No acquisition or source dataset rewrite is necessary. Original measurements and report/gate hashes remain preserved; the final source has its own acceptance.
