#!/usr/bin/env bash
# Prefer managed metadata; support ordinary clones and linked worktrees too.
set -euo pipefail
tiplog_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ -d "$tiplog_root/.tiplog-git" ]]; then
  # Keep the managed, read-only .git directory untouched.
  exec git --git-dir="$tiplog_root/.tiplog-git" --work-tree="$tiplog_root" "$@"
elif [[ -e "$tiplog_root/.git" ]]; then
  # Explicit metadata also resolves linked-worktree .git pointer files.
  exec git --git-dir="$tiplog_root/.git" --work-tree="$tiplog_root" "$@"
fi
printf 'No Git metadata found in %s (.tiplog-git or .git).\n' "$tiplog_root" >&2
exit 128
