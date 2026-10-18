#!/usr/bin/env bash
# Emit one JSON document. This command does not change machine settings.
set -euo pipefail

tiplog_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ -n "${TIPLOG_PYTHON:-}" ]]; then
  tiplog_python="$TIPLOG_PYTHON"
elif [[ -x "$tiplog_root/.venv/bin/python" ]]; then
  tiplog_python="$tiplog_root/.venv/bin/python"
else
  tiplog_python="$(command -v python3)"
fi

exec "$tiplog_python" "$tiplog_root/scripts/env_capture.py" "$@"
