#!/usr/bin/env bash
# strip_build_hints.sh — Remove build-instruction documentation from the repo.
#
# Called ONCE after cloning, BEFORE any worktrees are created. Commits the
# deletion so every `git worktree add --detach` inherits the clean tree.
#
# Why: The eval measures AGENTS.md quality, not the agent's ability to find
# in-tree documentation. CPython's source tree contains READMEs, build guides,
# and howtos that would let an agent shortcut the task. Stripping them ensures
# both baseline and improved conditions start from identical, doc-free source.
#
# Usage:
#   bash scripts/strip_build_hints.sh <repo_dir>
#
# Idempotent: safe to run multiple times. If docs are already stripped, the
# commit is a no-op (nothing staged → nothing committed).

set -euo pipefail

REPO_DIR="${1:?Usage: strip_build_hints.sh <repo_dir>}"

if [ ! -d "$REPO_DIR/.git" ]; then
    echo "[strip] Error: $REPO_DIR is not a git repository" >&2
    exit 1
fi

echo "[strip] Stripping build-hint documentation from $REPO_DIR..."

# Count what we'll remove (for logging)
REMOVED=0

# Root-level documentation
for f in "$REPO_DIR"/README* "$REPO_DIR"/readme*; do
    [ -e "$f" ] && rm -f "$f" && REMOVED=$((REMOVED + 1)) && echo "[strip]   removed $(basename "$f")"
done

# Contributing guidelines
if [ -f "$REPO_DIR/.github/CONTRIBUTING.rst" ]; then
    rm -f "$REPO_DIR/.github/CONTRIBUTING.rst"
    REMOVED=$((REMOVED + 1))
    echo "[strip]   removed .github/CONTRIBUTING.rst"
fi

# Entire Doc/ directory (build/install guides, howtos, tutorials, etc.)
if [ -d "$REPO_DIR/Doc" ]; then
    DOC_COUNT=$(find "$REPO_DIR/Doc" -type f | wc -l | tr -d ' ')
    rm -rf "$REPO_DIR/Doc"
    REMOVED=$((REMOVED + DOC_COUNT))
    echo "[strip]   removed Doc/ ($DOC_COUNT files)"
fi

# Platform-specific build docs
for f in "$REPO_DIR/Mac/README.rst" "$REPO_DIR/PCbuild/readme.txt"; do
    [ -e "$f" ] && rm -f "$f" && REMOVED=$((REMOVED + 1)) && echo "[strip]   removed ${f#$REPO_DIR/}"
done
for f in "$REPO_DIR"/PCbuild/*.txt; do
    [ -e "$f" ] && rm -f "$f" && REMOVED=$((REMOVED + 1)) && echo "[strip]   removed ${f#$REPO_DIR/}"
done

# Tool READMEs
for f in "$REPO_DIR"/Tools/README*; do
    [ -e "$f" ] && rm -f "$f" && REMOVED=$((REMOVED + 1)) && echo "[strip]   removed ${f#$REPO_DIR/}"
done

echo "[strip] Removed $REMOVED files/directories total"

# Commit the deletion so worktrees inherit the clean state.
# git worktree add --detach checks out from HEAD, so the commit
# must exist before worktrees are created.
cd "$REPO_DIR"
if [ -n "$(git status --porcelain)" ]; then
    # Ensure git identity exists (Cowork sandboxes may not have one)
    git config user.email >/dev/null 2>&1 || git config user.email "eval@local"
    git config user.name >/dev/null 2>&1 || git config user.name "eval-harness"

    git add -A
    git commit -m "Strip build-hint documentation for eval fairness

Removes READMEs, Doc/, contributing guides, and platform-specific
build docs so trial agents cannot shortcut the build task by reading
in-tree instructions. The eval measures AGENTS.md quality only." \
        --quiet
    echo "[strip] Committed doc-stripped state to repo HEAD"
else
    echo "[strip] No changes to commit (docs already stripped)"
fi
