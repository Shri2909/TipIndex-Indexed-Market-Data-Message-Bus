#!/usr/bin/env bash
# Keep the managed, read-only .git directory untouched.
set -euo pipefail
tiplog_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec git --git-dir="$tiplog_root/.tiplog-git" --work-tree="$tiplog_root" "$@"
