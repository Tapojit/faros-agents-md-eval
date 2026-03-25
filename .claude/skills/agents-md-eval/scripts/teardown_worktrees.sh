#!/usr/bin/env bash
# teardown_worktrees.sh - Clean up worktrees after trials complete
#
# Usage: bash scripts/teardown_worktrees.sh <repo_dir> <worktree_iter_dir>
#
# Only removes git worktrees under workspace/worktrees/. Results under
# workspace/results/ are untouched — they persist for analysis after teardown.

set -euo pipefail

REPO_DIR="${1:?Usage: teardown_worktrees.sh <repo_dir> <worktree_iter_dir>}"
WT_ITER_DIR="${2:?}"

if [ ! -d "$WT_ITER_DIR" ]; then
    echo "[teardown] No worktree directory found at $WT_ITER_DIR"
    exit 0
fi

# POSIX-portable absolute path resolver (macOS lacks GNU realpath)
_abspath() {
    local target="$1"
    if [ -d "$target" ]; then
        (cd "$target" && pwd)
    elif [ -d "$(dirname "$target")" ]; then
        echo "$(cd "$(dirname "$target")" && pwd)/$(basename "$target")"
    else
        echo "$(pwd)/$(echo "$target" | sed 's|^\./||')"
    fi
}

for WT_DIR in "$WT_ITER_DIR"/*/; do
    [ -d "$WT_DIR" ] || continue
    TRIAL_ID=$(basename "$WT_DIR")
    echo "[teardown] Removing worktree: $TRIAL_ID"
    git -C "$REPO_DIR" worktree remove --force "$(_abspath "$WT_DIR")" 2>/dev/null || true
    rm -rf "$WT_DIR"
done

git -C "$REPO_DIR" worktree prune 2>/dev/null
echo "[teardown] Done. Results in workspace/results/ are preserved."
