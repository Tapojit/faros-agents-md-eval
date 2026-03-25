#!/usr/bin/env bash
# setup_worktrees.sh - Create isolated git worktrees for eval trials
#
# Usage: bash scripts/setup_worktrees.sh <repo_dir> <worktree_iter_dir> <results_iter_dir> <condition> <num_trials> [agents_md_file] [workspace_dir]
#
# Arguments:
#   repo_dir          — path to the source repo
#   worktree_iter_dir — where to create worktrees (workspace/worktrees/iteration-N)
#   results_iter_dir  — where to write metadata (workspace/results/iteration-N)
#   condition         — "baseline" or "improved"
#   num_trials        — number of worktrees to create
#   agents_md_file    — path to AGENTS.md to place in each worktree
#   workspace_dir     — workspace root (to find build_env.sh for copying into worktrees)
#
# Each worktree is a self-contained execution environment. Everything the agent
# needs is copied INTO the worktree: AGENTS.md, build_env.sh, source code.
# The agent is then cd'd into the worktree by run_trial.sh with no --add-dir,
# so it cannot access the broader workspace, other trials, or evaluator scripts.
#
# Metadata (eval_metadata.json) goes to the results directory so it persists
# after worktree teardown.
#
# Example:
#   bash scripts/setup_worktrees.sh workspace/repo workspace/worktrees/iteration-0 \
#       workspace/results/iteration-0 baseline 3 workspace/agents-md/init-baseline.md workspace

set -euo pipefail

REPO_DIR="${1:?Usage: setup_worktrees.sh <repo_dir> <worktree_iter_dir> <results_iter_dir> <condition> <num_trials> [agents_md_file] [workspace_dir]}"
WT_ITER_DIR="${2:?}"
RESULTS_ITER_DIR="${3:?}"
CONDITION="${4:?}"
NUM_TRIALS="${5:?}"
AGENTS_MD="${6:-}"
WORKSPACE_DIR="${7:-}"

mkdir -p "$WT_ITER_DIR"
mkdir -p "$RESULTS_ITER_DIR"

# POSIX-portable absolute path resolver.
# macOS lacks GNU realpath, and even Homebrew coreutils' realpath fails on
# non-existent targets — which is exactly our case here: the worktree dir
# doesn't exist yet when git-worktree-add needs the absolute path.
_abspath() {
    local target="$1"
    if [ -d "$target" ]; then
        (cd "$target" && pwd)
    elif [ -d "$(dirname "$target")" ]; then
        echo "$(cd "$(dirname "$target")" && pwd)/$(basename "$target")"
    else
        # Parent doesn't exist yet — create it, resolve, leave it for git
        mkdir -p "$(dirname "$target")"
        echo "$(cd "$(dirname "$target")" && pwd)/$(basename "$target")"
    fi
}

for i in $(seq 1 "$NUM_TRIALS"); do
    TRIAL_ID="${CONDITION}-t${i}"
    WT_DIR="${WT_ITER_DIR}/${TRIAL_ID}"
    RESULTS_TRIAL_DIR="${RESULTS_ITER_DIR}/${TRIAL_ID}"

    mkdir -p "$RESULTS_TRIAL_DIR"

    if [ -d "$WT_DIR" ]; then
        echo "[setup] Removing existing worktree: $TRIAL_ID"
        git -C "$REPO_DIR" worktree remove --force "$(_abspath "$WT_DIR")" 2>/dev/null || true
        rm -rf "$WT_DIR"
    fi

    echo "[setup] Creating worktree: $WT_DIR"
    git -C "$REPO_DIR" worktree add --detach "$(_abspath "$WT_DIR")" 2>/dev/null

    # NOTE: Build-hint docs (README*, Doc/, etc.) are stripped from the repo
    # itself by strip_build_hints.sh during /eval-init. Since worktrees are
    # created from the repo's HEAD, they inherit the clean state automatically.
    # No per-worktree stripping needed.

    # Place AGENTS.md (both baseline and improved get one — baseline uses /init-generated)
    if [ -n "$AGENTS_MD" ] && [ -f "$AGENTS_MD" ] && [ -s "$AGENTS_MD" ]; then
        cp "$AGENTS_MD" "${WT_DIR}/AGENTS.md"
        echo "[setup] Placed $(basename "$AGENTS_MD") into $TRIAL_ID"
    else
        echo "[setup] No AGENTS.md for $TRIAL_ID"
    fi

    # Copy build_env.sh into the worktree so the agent can find it locally.
    # This is part of the isolation strategy: the agent is cd'd into the worktree
    # with no --add-dir, so it can only see files inside the worktree. Anything
    # it needs from the workspace must be copied in here.
    if [ -n "$WORKSPACE_DIR" ] && [ -f "$WORKSPACE_DIR/build_env.sh" ]; then
        cp "$WORKSPACE_DIR/build_env.sh" "${WT_DIR}/build_env.sh"
        echo "[setup] Copied build_env.sh into $TRIAL_ID"
    fi

    # Write eval_metadata.json to results dir (persists after worktree teardown)
    WORDS=0
    [ -f "${WT_DIR}/AGENTS.md" ] && WORDS=$(wc -w < "${WT_DIR}/AGENTS.md" | tr -d ' ')

    # Extract iteration number from directory name
    _BASENAME=$(basename "$WT_ITER_DIR")
    ITER_NUM="${_BASENAME##*-}"
    case "$ITER_NUM" in ''|*[!0-9]*) ITER_NUM=0 ;; esac

    TASK_PROMPT="Build CPython from source in this directory. The source is already checked out. Produce a working Python interpreter. Verify it works by running: ./python -c \"import ssl; import ctypes; import sqlite3; print('BUILD OK')\""

    python3 -c "
import json, sys
json.dump({
    'trial_id': sys.argv[1],
    'condition': sys.argv[2],
    'iteration': int(sys.argv[3]),
    'trial_num': int(sys.argv[4]),
    'task_id': 'build-cpython-from-source',
    'task_prompt': sys.argv[5],
    'agents_md_file': sys.argv[6],
    'agents_md_words': int(sys.argv[7]),
    'worktree_path': sys.argv[8],
    'results_path': sys.argv[9],
    'created_at': sys.argv[10]
}, open(sys.argv[11], 'w'), indent=2)
" "$TRIAL_ID" "$CONDITION" "$ITER_NUM" "$i" "$TASK_PROMPT" \
      "$(basename "${AGENTS_MD:-none}")" "$WORDS" "$WT_DIR" \
      "$RESULTS_TRIAL_DIR" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      "${RESULTS_TRIAL_DIR}/eval_metadata.json"
done

echo "[setup] Created $NUM_TRIALS worktrees in $WT_ITER_DIR for condition=$CONDITION"
echo "[setup] Each worktree is self-contained (AGENTS.md + build_env.sh copied in)"
echo "[setup] Metadata written to $RESULTS_ITER_DIR"
