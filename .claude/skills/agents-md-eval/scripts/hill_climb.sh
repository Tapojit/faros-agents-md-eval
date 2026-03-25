#!/usr/bin/env bash
# hill_climb.sh — Full automated hill-climbing loop.
#
# This is the top-level orchestrator. It runs the complete eval pipeline:
#
#   0. Generate baseline AGENTS.md via `claude /init` (called ONCE, cached)
#   1. Baseline trials (Haiku, with /init AGENTS.md) → transcripts show where agent struggles
#   2. Generate improved AGENTS.md (Sonnet analyzes baseline transcripts)
#   3. Improved trials (Haiku, with generated AGENTS.md) → measure delta
#   4. Hill-climb: Sonnet analyzes improved transcripts → smaller AGENTS.md
#   5. Repeat until AGENTS.md size plateaus or pass@1 drops
#
# The baseline uses a /init-generated AGENTS.md — the standard out-of-box file
# that any user would get from running `claude /init` in the repo. The eval
# measures: "does transcript-informed hill-climbing beat /init?"
#
# Isolation:
#   Each trial agent runs cd'd into its worktree with NO --add-dir.
#   AGENTS.md and build_env.sh are pre-copied into the worktree.
#   --disable-slash-commands prevents skill/command leakage.
#   No cross-contamination between trials or between agent and evaluator.
#
# The separation of roles is deliberate:
#   - GENERATOR model (Sonnet 4.6): smart enough to analyze transcripts and produce good AGENTS.md
#   - AGENT model (Haiku 4.5): weak enough that AGENTS.md makes a visible difference
#   - EVALUATOR (this script + graders): deterministic, no LLM judgment in grading
#
# Workspace layout:
#   workspace/worktrees/  — ephemeral git worktrees (torn down after trials)
#   workspace/results/    — persistent trial artifacts (transcripts, grading, metrics)
#   workspace/agents-md/  — all AGENTS.md versions (init-baseline.md, improved-iter*.md)
#
# Usage:
#   bash hill_climb.sh <workspace> [max_iterations] [agent_model] [generator_model] [n_trials] [max_turns]
#
# Example:
#   bash hill_climb.sh /path/to/workspace 3 haiku sonnet 3

set -euo pipefail

# macOS ships without GNU timeout; use gtimeout from coreutils if available
if ! command -v timeout &>/dev/null; then
    if command -v gtimeout &>/dev/null; then
        timeout() { gtimeout "$@"; }
    else
        timeout() { shift; "$@"; }
    fi
fi

WORKSPACE="${1:?Usage: hill_climb.sh <workspace> [max_iterations] [agent_model] [generator_model] [n_trials] [max_turns]}"
MAX_ITERS="${2:-3}"
AGENT_MODEL="${3:-haiku}"
GEN_MODEL="${4:-sonnet}"
N_TRIALS="${5:-3}"
MAX_TURNS="${6:-30}"

WORKSPACE="$(cd "$WORKSPACE" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  AGENTS.md Hill-Climbing Eval                                   ║"
echo "║                                                                 ║"
echo "║  Agent model:     $AGENT_MODEL (executes build task)            "
echo "║  Generator model: $GEN_MODEL (analyzes transcripts, writes MD)  "
echo "║  Max iterations:  $MAX_ITERS                                    "
echo "║  Trials/condition: $N_TRIALS                                    "
echo "║  Workspace:       $WORKSPACE                                    "
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# Create workspace directories
mkdir -p "$WORKSPACE"/{worktrees,results,agents-md}

# ═══════════════════════════════════════════════════════════════════════
# Phase 0: Generate baseline AGENTS.md via /init (called ONCE)
# ═══════════════════════════════════════════════════════════════════════
INIT_AGENTS_MD="$WORKSPACE/agents-md/init-baseline.md"

if [ -f "$INIT_AGENTS_MD" ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  PHASE 0: Using existing /init baseline AGENTS.md"
    echo "  File: $INIT_AGENTS_MD ($(wc -w < "$INIT_AGENTS_MD" | tr -d ' ') words)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  PHASE 0: Generating baseline AGENTS.md via /init"
    echo "  This is the out-of-box AGENTS.md — called once and cached."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Use a temporary worktree so /init doesn't pollute the main repo.
    # The worktree gives claude a clean copy to scan.
    INIT_WT="$WORKSPACE/worktrees/init-baseline"
    if [ -d "$INIT_WT" ]; then
        git -C "$WORKSPACE/repo" worktree remove --force "$INIT_WT" 2>/dev/null || true
        rm -rf "$INIT_WT"
    fi
    git -C "$WORKSPACE/repo" worktree add --detach "$INIT_WT" 2>/dev/null

    echo "[phase 0] Running 'claude /init' in temporary worktree..."
    echo "[phase 0] worktree=$INIT_WT"

    # Run claude -p in the worktree directory. The prompt mirrors what /init does:
    # scan the repo and generate an AGENTS.md. We use --no-session-persistence
    # so this doesn't leak into any session history.
    #
    # This is called ONCE and cached at agents-md/init-baseline.md.
    # Subsequent runs of hill_climb.sh reuse the cached file.
    INIT_RESULT=$(cd "$INIT_WT" && timeout 180 claude -p \
        --model "$GEN_MODEL" \
        --dangerously-skip-permissions \
        --no-session-persistence \
        --tools "Bash,Read,Write,Grep" \
        --output-format text \
        "You are initializing this repository for AI agent use. Scan the codebase — its structure, build system, dependencies, and common development tasks — then generate an AGENTS.md file and write it to ./AGENTS.md. This file should help a coding agent work with the repo efficiently. Focus on what's non-obvious: build deps, configure flags, environment setup, common pitfalls." \
        2>/dev/null) || {
        echo "[phase 0] WARNING: claude /init timed out or failed"
    }

    # Grab the generated AGENTS.md
    if [ -f "$INIT_WT/AGENTS.md" ]; then
        cp "$INIT_WT/AGENTS.md" "$INIT_AGENTS_MD"
        INIT_WORDS=$(wc -w < "$INIT_AGENTS_MD" | tr -d ' ')
        echo "[phase 0] Generated init-baseline.md ($INIT_WORDS words)"
    else
        echo "[phase 0] WARNING: /init did not produce an AGENTS.md"
        echo "[phase 0] Creating a minimal fallback baseline..."
        cat > "$INIT_AGENTS_MD" <<'FALLBACK'
# AGENTS.md

## Building CPython from source

1. Install build dependencies
2. Run ./configure
3. Run make
4. Verify with: ./python -c "import ssl; import ctypes; import sqlite3; print('BUILD OK')"
FALLBACK
    fi

    # Clean up the init worktree — it was temporary
    git -C "$WORKSPACE/repo" worktree remove --force "$INIT_WT" 2>/dev/null || true
    rm -rf "$INIT_WT"
fi
echo ""

# ═══════════════════════════════════════════════════════════════════════
# Phase 1: BASELINE (iteration-0, with /init AGENTS.md)
# ═══════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  PHASE 1: Baseline (iteration-0, /init AGENTS.md)"
echo "  Agent: $AGENT_MODEL | AGENTS.md: init-baseline.md"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

bash "$SCRIPT_DIR/run_eval.sh" "$WORKSPACE" baseline 0 "$AGENT_MODEL" "$N_TRIALS" "$INIT_AGENTS_MD" "$MAX_TURNS"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Baseline complete. Now generating first improved AGENTS.md from transcripts."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ═══════════════════════════════════════════════════════════════════════
# Phase 2+: HILL-CLIMBING LOOP
# ═══════════════════════════════════════════════════════════════════════
PREV_AGENTS_MD=""
for ITER in $(seq 1 "$MAX_ITERS"); do
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  PHASE 2: Hill-Climb Iteration $ITER / $MAX_ITERS"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    AGENTS_MD_PATH="$WORKSPACE/agents-md/improved-iter${ITER}.md"

    # ── Generate AGENTS.md ──
    echo ""
    echo "[iteration $ITER] Generating AGENTS.md via $GEN_MODEL..."

    if [ "$ITER" -eq 1 ]; then
        # First iteration: analyze BASELINE transcripts to generate initial AGENTS.md
        python3 "$SCRIPT_DIR/generate_agents_md.py" \
            --workspace "$WORKSPACE" \
            --iteration "$ITER" \
            --model "$GEN_MODEL" \
            --baseline-iteration 0
    else
        # Subsequent iterations: hill-climb from previous AGENTS.md
        python3 "$SCRIPT_DIR/generate_agents_md.py" \
            --workspace "$WORKSPACE" \
            --iteration "$ITER" \
            --model "$GEN_MODEL" \
            --previous-agents-md "$PREV_AGENTS_MD" \
            --previous-iteration $((ITER - 1))
    fi

    if [ ! -f "$AGENTS_MD_PATH" ]; then
        echo "[error] AGENTS.md generation failed for iteration $ITER" >&2
        exit 1
    fi

    WORD_COUNT=$(wc -w < "$AGENTS_MD_PATH" | tr -d ' ')
    echo "[iteration $ITER] Generated AGENTS.md: $AGENTS_MD_PATH ($WORD_COUNT words)"
    echo ""
    echo "── AGENTS.md content ──"
    cat "$AGENTS_MD_PATH"
    echo ""
    echo "── end ──"

    # ── Run improved trials ──
    echo ""
    echo "[iteration $ITER] Running improved trials with AGENTS.md..."
    bash "$SCRIPT_DIR/run_eval.sh" "$WORKSPACE" improved "$ITER" "$AGENT_MODEL" "$N_TRIALS" "$AGENTS_MD_PATH" "$MAX_TURNS"

    PREV_AGENTS_MD="$AGENTS_MD_PATH"

    # ── Check for plateau ──
    if [ "$WORD_COUNT" -lt 50 ]; then
        echo ""
        echo "[iteration $ITER] AGENTS.md is at $WORD_COUNT words — approaching minimum viable size."
        echo "  Consider stopping here unless pass@1 is still improving."
    fi

    echo ""
done

# ═══════════════════════════════════════════════════════════════════════
# Final Summary
# ═══════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════
# Generate Eval Viewer
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "[viewer] Generating eval viewer..."
VIEWER_OUTPUT="$WORKSPACE/results/eval-viewer.html"
python3 "$SCRIPT_DIR/generate_eval_viewer.py" "$WORKSPACE" --output "$VIEWER_OUTPUT" 2>&1 || echo "[warning] viewer generation failed"

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  Hill-Climbing Complete                                         ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "Iterations run: $MAX_ITERS"
echo "Baseline AGENTS.md: $INIT_AGENTS_MD (/init-generated, cached)"
echo "Final AGENTS.md: $PREV_AGENTS_MD (hill-climbed)"
echo ""
echo "All transcripts: $WORKSPACE/results/iteration-*/*/transcript.jsonl"
echo "All metrics:     $WORKSPACE/results/metrics.csv"
echo "Eval viewer:     $VIEWER_OUTPUT"
echo ""
python3 "$SCRIPT_DIR/display_metrics.py" --csv "$WORKSPACE/results/metrics.csv" 2>&1 || true
