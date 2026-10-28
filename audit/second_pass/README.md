# Independent second audit pass — 2026-10-26

The consolidated assessment is appended as §16 in [AUDIT_REPORT.md](../AUDIT_REPORT.md).
No production fixes have been made. Probe assertions demonstrate the current defects;
they are not acceptance tests for a repaired implementation.

- [Runtime/core review](core/findings.md): inspection scope, direct-source build commands,
  observer identity reproduction, Auto traversal counts and bounded-poll feature evidence.
- [Python review](python/findings.md): source preservation, recovery, oracle scaling/limits,
  T2 duration and validation-helper probes.
- [Layout/tools review](layout_tools/findings.md): output I/O, mixture overflow and JSON probes,
  fresh-build confirmations, additional observations and rejected hypotheses.
- [Source verification](root/source-verification.json): before/after hashes and preserved original report prefix.
- [Current closeout result](root/core-closeout.json): 9 failed checks, documented as AUD-026.
- [Full saved-output audit](root/cc4-rerun.json): 10,295,181 checks, 2 build-provenance identity failures.

Run from the repository root using the existing environment:

```sh
PYTHONPATH=py PYTHONDONTWRITEBYTECODE=1 .venv/bin/python audit/second_pass/python/probe_python_second_pass.py
PYTHONPATH=py PYTHONDONTWRITEBYTECODE=1 .venv/bin/python audit/second_pass/python/probe_oracle_scaling.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python audit/second_pass/root/probe_quiescence.py
PYTHONPATH=py PYTHONDONTWRITEBYTECODE=1 .venv/bin/python audit/second_pass/root/probe_saved_noise.py
```

The quiescence and Python input probes use temporary fixtures. The saved-noise probe
reads the current local raw-result/sidecar tree; it asserts the present mismatch.
The tools probe creates/rewrites files only in its audit evidence directory. Exact commands,
binary hashes and results are recorded in `layout_tools/fresh_release/confirmation.json`.

Fresh Release and ASan/UBSan builds used `/tmp/tiplog-second-pass/work` as a copied source
tree and `/tmp/tiplog-second-pass/{release,asan}` as build directories, with the local
hash-checked dependency archive cache. Configure/build logs are under `root/`.
Temporary build directories are not required report artifacts and may not persist.
CTest JUnit/log files record 186 passes for each fresh build. The final pytest JUnit/log
records 151 passes and no skips against the copied source and fresh Release binaries.

Earlier setup failures remain in the evidence: the first Python run lacked the expected
build path, and sanitizer feature probes failed under tracing. The final successful runs
are explicitly named `pytest-final.*`, `configure-asan-retry.log`, `build-asan-final.log`
and `ctest-asan.*`. ASan/UBSan CTest ran outside tracing with leak checking enabled.

Do not run a verifier with its default output paths merely to reproduce this audit:
some project verifiers overwrite historical result files. The closeout reproduction used:

```sh
PYTHONPATH=py PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/check_core_closeout.py \
  --output audit/second_pass/root/core-closeout.json \
  --manifest audit/second_pass/root/core-artifact-manifest.json
```

The P6 saved-output audit called `audit_session(plan, directory, 20)` from
`scripts/check_p6_experiments.py` and wrote its returned object only to this audit directory;
its CLI default would write into the original experiment directory. The audit's JSON
records the exact prepared plan and evaluation directory. No benchmark timings, full-day
conversions, extended fuzz gates or data downloads were executed in this pass.
