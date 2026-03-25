#!/usr/bin/env bash
# run_eval.sh — End-to-end eval runner for a single condition.
#
# Does everything: creates worktrees → writes prompt files → runs trials via
# claude -p → grades → extracts metrics → appends to CSV → aggregates.
#
# Worktrees (ephemeral execution environments) live under workspace/worktrees/.
# Results (persistent artifacts) live under workspace/results/.
# This separation means worktrees can be torn down without losing any data.
#
# Isolation: Each trial agent is cd'd into its worktree with NO --add-dir.
# Everything the agent needs (AGENTS.md, build_env.sh, source code) is
# pre-copied into the worktree by setup_worktrees.sh. The agent cannot
# access the broader workspace, other trials, evaluator scripts, or metrics.
#
# Usage:
#   bash run_eval.sh <workspace> <condition> <iteration> <model> <n_trials> [agents_md_path] [max_turns]
#
# Arguments:
#   workspace       — workspace root (contains repo/, agents-md/, worktrees/, results/, build_env.sh)
#   condition       — "baseline" or "improved"
#   iteration       — iteration number (0 for baseline, 1+ for improved)
#   model           — model alias ("haiku", "sonnet")
#   n_trials        — number of trials to run (typically 3)
#   agents_md_path  — path to AGENTS.md file (used for both baseline and improved)
#   max_turns       — max agentic turns (default: 30)
#
# Outputs (per trial, in workspace/results/iteration-{N}/{condition}-t{i}/):
#   transcript.jsonl   — full JSONL transcript (source of truth)
#   result.json        — final result object from claude -p
#   grading.json       — deterministic grader results
#   timing.json        — extracted metrics (derived from transcript.jsonl)
#   eval_metadata.json — trial metadata
#   prompt.txt         — the exact prompt sent to the agent
#
# Outputs (workspace-level):
#   results/metrics.csv    — appended with one row per trial
#   results/benchmark.json — regenerated aggregate stats
#   history.json           — updated with iteration summary

set -euo pipefail

WORKSPACE="${1:?Usage: run_eval.sh <workspace> <condition> <iteration> <model> <n_trials> [agents_md_path] [max_turns]}"
CONDITION="${2:?}"
ITERATION="${3:?}"
MODEL="${4:?}"
N_TRIALS="${5:?}"
AGENTS_MD_PATH="${6:-}"
MAX_TURNS="${7:-30}"

# Resolve paths
WORKSPACE="$(cd "$WORKSPACE" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Worktrees are ephemeral, results are persistent
WT_ITER_DIR="$WORKSPACE/worktrees/iteration-${ITERATION}"
RESULTS_ITER_DIR="$WORKSPACE/results/iteration-${ITERATION}"

echo "================================================================"
echo "  run_eval.sh"
echo "  condition=$CONDITION  iteration=$ITERATION  model=$MODEL  trials=$N_TRIALS"
echo "  workspace=$WORKSPACE"
echo "  worktrees=$WT_ITER_DIR"
echo "  results=$RESULTS_ITER_DIR"
[ -n "$AGENTS_MD_PATH" ] && echo "  agents_md=$AGENTS_MD_PATH"
echo "================================================================"

# ── Validate ──
if [ -n "$AGENTS_MD_PATH" ] && [ ! -f "$AGENTS_MD_PATH" ]; then
    echo "[error] AGENTS.md not found: $AGENTS_MD_PATH" >&2
    exit 1
fi
if [ ! -d "$WORKSPACE/repo" ]; then
    echo "[error] Repo not found at $WORKSPACE/repo. Run /eval-init first." >&2
    exit 1
fi

# ── Step 1: Create worktrees ──
echo ""
echo "[step 1] Creating $N_TRIALS isolated worktrees..."
if [ -d "$WT_ITER_DIR" ]; then
    echo "[step 1] Cleaning up existing worktrees..."
    bash "$SCRIPT_DIR/teardown_worktrees.sh" "$WORKSPACE/repo" "$WT_ITER_DIR" 2>&1 || true
    rm -rf "$WT_ITER_DIR"
fi

# Clean up existing results for this iteration (fresh run)
rm -rf "$RESULTS_ITER_DIR"
mkdir -p "$RESULTS_ITER_DIR"

# Pass workspace dir so setup_worktrees.sh can copy build_env.sh into each worktree
bash "$SCRIPT_DIR/setup_worktrees.sh" "$WORKSPACE/repo" "$WT_ITER_DIR" "$RESULTS_ITER_DIR" "$CONDITION" "$N_TRIALS" "$AGENTS_MD_PATH" "$WORKSPACE"

# ── Step 2: Write prompt files ──
echo ""
echo "[step 2] Writing prompt files..."
AGENTS_MD_WORDS=0
if [ -n "$AGENTS_MD_PATH" ]; then
    AGENTS_MD_WORDS=$(wc -w < "$AGENTS_MD_PATH" | tr -d ' ')
fi
PLATFORM_INFO="$(uname -s) $(uname -m)"

for i in $(seq 1 "$N_TRIALS"); do
    TRIAL_DIR="$WT_ITER_DIR/${CONDITION}-t${i}"
    RESULTS_TRIAL_DIR="$RESULTS_ITER_DIR/${CONDITION}-t${i}"
    mkdir -p "$RESULTS_TRIAL_DIR"
    PROMPT_FILE="$RESULTS_TRIAL_DIR/prompt.txt"

    # Prompts use ONLY worktree-relative paths. The agent is cd'd into the
    # worktree by run_trial.sh, so "./AGENTS.md" and "./build_env.sh" resolve
    # correctly. No workspace-level paths are leaked to the agent.
    cat > "$PROMPT_FILE" <<PROMPT
You are being evaluated on a coding task. Your job is to complete it as efficiently as possible.

TASK: Build CPython from source in this directory. The source is already checked out. Produce a working Python interpreter. Verify it works by running: ./python -c "import ssl; import ctypes; import sqlite3; print('BUILD OK')"

IMPORTANT:
- You are on $PLATFORM_INFO
- There IS an AGENTS.md file at ./AGENTS.md — READ IT FIRST and follow its instructions before doing anything else.
- There may be a ./build_env.sh file that contains environment setup needed for the build. Source it if it exists.
- Work ONLY inside the current directory.
PROMPT
    echo "  Wrote $PROMPT_FILE"
done

# ── Step 3: Run trials sequentially ──
# Sequential because: (a) parallel builds contend for CPU, (b) parallel claude -p
# instances may hit rate limits, (c) easier to debug failures.
echo ""
echo "[step 3] Running $N_TRIALS trials (sequential, isolated)..."
for i in $(seq 1 "$N_TRIALS"); do
    TRIAL_DIR="$WT_ITER_DIR/${CONDITION}-t${i}"
    RESULTS_TRIAL_DIR="$RESULTS_ITER_DIR/${CONDITION}-t${i}"
    PROMPT_FILE="$RESULTS_TRIAL_DIR/prompt.txt"
    TRIAL_ID="${CONDITION}-t${i}"

    echo ""
    echo "────────────────────────────────────────"
    echo "  Trial $i/$N_TRIALS: $TRIAL_ID"
    echo "────────────────────────────────────────"

    bash "$SCRIPT_DIR/run_trial.sh" "$TRIAL_DIR" "$RESULTS_TRIAL_DIR" "$CONDITION" "$MODEL" "$PROMPT_FILE" "$MAX_TURNS"
done

# ── Step 4: Grade all trials ──
# Graders run inside the worktree (they need the built binaries) but write
# grading.json to the results directory.
echo ""
echo "[step 4] Grading all trials..."
for i in $(seq 1 "$N_TRIALS"); do
    TRIAL_DIR="$WT_ITER_DIR/${CONDITION}-t${i}"
    RESULTS_TRIAL_DIR="$RESULTS_ITER_DIR/${CONDITION}-t${i}"
    bash "$SCRIPT_DIR/run_graders.sh" "$TRIAL_DIR" "$RESULTS_TRIAL_DIR"
done

# ── Step 5: Extract metrics and append to CSV ──
echo ""
echo "[step 5] Extracting metrics from transcripts..."
CSV="$WORKSPACE/results/metrics.csv"

# Write CSV header if file doesn't exist
if [ ! -f "$CSV" ]; then
    python3 "$SCRIPT_DIR/extract_metrics.py" --csv-header > "$CSV"
fi

for i in $(seq 1 "$N_TRIALS"); do
    RESULTS_TRIAL_DIR="$RESULTS_ITER_DIR/${CONDITION}-t${i}"
    TRIAL_ID="${CONDITION}-t${i}"
    TRANSCRIPT="$RESULTS_TRIAL_DIR/transcript.jsonl"

    if [ ! -f "$TRANSCRIPT" ]; then
        echo "[warning] No transcript for $TRIAL_ID — skipping"
        continue
    fi

    # Determine pass/fail from grading.json
    PASSED="false"
    if [ -f "$RESULTS_TRIAL_DIR/grading.json" ]; then
        PASSED=$(python3 -c "import json; g=json.load(open('$RESULTS_TRIAL_DIR/grading.json')); print('true' if g['summary']['all_passed'] else 'false')")
    fi

    # Write timing.json to results dir
    python3 "$SCRIPT_DIR/extract_metrics.py" "$TRANSCRIPT" --write-timing "$RESULTS_TRIAL_DIR"

    # Append CSV row
    python3 "$SCRIPT_DIR/extract_metrics.py" "$TRANSCRIPT" \
        --csv-row "$TRIAL_ID" "$CONDITION" "$ITERATION" "$i" "$PASSED" "$AGENTS_MD_WORDS" >> "$CSV"

    echo "[metrics] $TRIAL_ID: passed=$PASSED (from transcript.jsonl)"
done

# ── Step 6: Aggregate and display ──
echo ""
echo "[step 6] Aggregating results..."
python3 "$SCRIPT_DIR/aggregate_benchmark.py" --workspace "$WORKSPACE" 2>&1 || echo "[warning] aggregate failed"

echo ""
echo "[step 6] Results:"
python3 "$SCRIPT_DIR/display_metrics.py" --csv "$CSV" 2>&1 || echo "[warning] display failed"

# ── Step 7: Generate eval viewer ──
echo ""
echo "[step 7] Generating eval viewer..."
VIEWER_OUTPUT="$WORKSPACE/results/eval-viewer.html"
python3 "$SCRIPT_DIR/generate_eval_viewer.py" "$WORKSPACE" --output "$VIEWER_OUTPUT" 2>&1 || echo "[warning] viewer generation failed"

echo ""
echo "================================================================"
echo "  run_eval.sh complete"
echo "  Transcripts: $RESULTS_ITER_DIR/*/transcript.jsonl"
echo "  Metrics CSV: $CSV"
echo "  Eval Viewer: $VIEWER_OUTPUT"
echo "================================================================"
