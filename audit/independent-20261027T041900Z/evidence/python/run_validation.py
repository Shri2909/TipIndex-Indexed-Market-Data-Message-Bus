"""Reproduce this sub-audit's Python/script suite with source and log identities."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
DESTINATION = Path(__file__).resolve().parent


def identity(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sources():
    paths = {path for directory in ('py', 'scripts', 'tests/scripts')
             for path in (ROOT/directory).rglob('*') if path.is_file()
             and path.suffix in ('.py', '.c', '.ini', '.txt')
             and not {'__pycache__', '.pytest_cache'}.intersection(path.parts)}
    return {path.relative_to(ROOT).as_posix(): identity(path) for path in sorted(paths)}


command = [str(ROOT/'.venv/bin/python'), '-m', 'pytest', '-c', 'py/pytest.ini',
           '-p', 'no:cacheprovider', 'py/tests', 'tests/scripts',
           '--basetemp=/tmp/tiplog-independent-python-final',
           '--junitxml='+str(DESTINATION/'final-python-junit.xml')]
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT/'py'),
                   MPLCONFIGDIR='/tmp/tiplog-independent-mpl-final', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
before = sources()
record = dict(argv=command, cwd=str(ROOT), started_utc=datetime.now(timezone.utc).isoformat(),
              interpreter=sys.version, platform=platform.platform(), sources_before=before,
              environment={name: environment[name] for name in
                           ('PYTHONDONTWRITEBYTECODE', 'PYTHONPATH', 'MPLCONFIGDIR', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD')})
start = time.monotonic()
log = DESTINATION/'final-python-pytest.log'
with log.open('w') as stream:
    result = subprocess.run(command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
after = sources()
record.update(exit_code=result.returncode, elapsed_seconds=time.monotonic()-start, sources_after=after,
              source_unchanged=before == after, log_sha256=identity(log),
              junit_sha256=identity(DESTINATION/'final-python-junit.xml'))
record['status'] = 'passed' if result.returncode == 0 and before == after else 'failed'
(DESTINATION/'final-python-validation.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps({key: record[key] for key in ('status', 'exit_code', 'source_unchanged', 'elapsed_seconds')}))
raise SystemExit(0 if record['status'] == 'passed' else 1)
