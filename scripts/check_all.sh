#!/usr/bin/env bash
set -euo pipefail
tiplog_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ! -x "$tiplog_root/.venv/bin/python" ]]; then
    printf '%s\n' 'Create the project .venv using the instructions in README.md.' >&2
    exit 1
fi
export MPLCONFIGDIR="${MPLCONFIGDIR:-$tiplog_root/build/matplotlib}"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
exec "$tiplog_root/.venv/bin/python" "$tiplog_root/scripts/check_all.py"
