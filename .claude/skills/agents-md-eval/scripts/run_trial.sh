#!/usr/bin/env bash
# run_trial.sh — Run a single eval trial via `claude -p` with full JSONL transcript.
#
# Usage:
#   bash run_trial.sh <worktree_path> <results_dir> <condition> <model> <prompt_file> [max_turns]
#
# Inputs:
#   worktree_path  — path to the git worktree (agent's working directory)
#   results_dir    — path to store trial artifacts (transcript, result, logs)
#   condition      — "baseline" or "improved"
#   model          — model alias (e.g. "haiku", "sonnet")
#   prompt_file    — path to a text file containing the agent's task prompt
#   max_turns      — max agentic turns before stopping (default: 30)
#
# Outputs (all written to results_dir — NOT the worktree):
#   transcript.jsonl  — full stream-json transcript (every message, tool call, tool result)
#   result.json       — final result object (usage, cost, duration, stop_reason)
#   debug.log         — debug log from claude -p
#   stderr.log        — stderr output
#
# Isolation guarantees:
#   The agent is cd'd into the worktree and has NO access to the broader workspace.
#   No --add-dir is used. build_env.sh and AGENTS.md are pre-copied into the worktree
#   by setup_worktrees.sh, so the agent finds everything it needs locally.
#   --disable-slash-commands prevents the agent from loading orchestrator skills.
#   This ensures zero cross-contamination between trials, and between agent and evaluator.

set -euo pipefail

WORKTREE="${1:?Usage: run_trial.sh <worktree_path> <results_dir> <condition> <model> <prompt_file> [max_turns]}"
RESULTS_DIR="${2:?}"
CONDITION="${3:?}"
MODEL="${4:?}"
PROMPT_FILE="${5:?}"
MAX_TURNS="${6:-30}"       # Default: 30 agentic turns (generous for a build task)

mkdir -p "$RESULTS_DIR"

# Resolve to absolute paths before cd
WORKTREE="$(cd "$WORKTREE" && pwd)"
RESULTS_DIR="$(cd "$RESULTS_DIR" && pwd)"
PROMPT_FILE="$(cd "$(dirname "$PROMPT_FILE")" && pwd)/$(basename "$PROMPT_FILE")"

TRANSCRIPT="$RESULTS_DIR/transcript.jsonl"
RESULT="$RESULTS_DIR/result.json"
DEBUG_LOG="$RESULTS_DIR/debug.log"
STDERR_LOG="$RESULTS_DIR/stderr.log"

TRIAL_ID="$(basename "$RESULTS_DIR")"

echo "[run_trial] trial=$TRIAL_ID condition=$CONDITION model=$MODEL"
echo "[run_trial] worktree=$WORKTREE"
echo "[run_trial] results_dir=$RESULTS_DIR"
echo "[run_trial] prompt_file=$PROMPT_FILE"
echo "[run_trial] max_turns=$MAX_TURNS"

# Timeout: 10 minutes (600s) as an outer safety net.
TIMEOUT_SEC=600

# macOS ships without GNU timeout; use gtimeout from coreutils if available
if ! command -v timeout &>/dev/null; then
    if command -v gtimeout &>/dev/null; then
        timeout() { gtimeout "$@"; }
    else
        echo "[run_trial] WARNING: no timeout command found — running without timeout"
        timeout() { shift; "$@"; }
    fi
fi

# ── Run claude -p with full JSONL transcript output ──
#
# Key flags:
#   --disable-slash-commands               → prevents the agent from loading skills or
#                                            commands from the orchestrator session — this
#                                            is critical for eval isolation
#   --output-format stream-json --verbose  → full JSONL transcript of every message,
#                                            tool call, tool result, and thinking block
#   --dangerously-skip-permissions         → sandbox with no internet, safe to bypass
#   --no-session-persistence               → don't save to session history
#   --tools "Bash,Read,Grep"              → agents need Bash, Read, and Grep to build
#   --max-turns                            → cap agentic turns to prevent runaway loops
#
# NO --add-dir: the agent is scoped to the worktree via cd. Everything it needs
# (AGENTS.md, build_env.sh, source code) is already in the worktree, placed there
# by setup_worktrees.sh. This prevents the agent from reading other trials' results,
# the evaluator's scripts, or the workspace-level metrics/history.
#
# The prompt is piped via stdin to avoid shell quoting issues with complex prompts.

echo "[run_trial] Starting claude -p (model=$MODEL, max_turns=$MAX_TURNS, timeout=${TIMEOUT_SEC}s)..."
echo "[run_trial] Agent is scoped to worktree only (no --add-dir)"
START_TIME=$(date +%s)

timeout "$TIMEOUT_SEC" bash -c '
  cd "$1" && cat "$2" | claude -p \
    --disable-slash-commands \
    --output-format stream-json \
    --verbose \
    --model "$3" \
    --dangerously-skip-permissions \
    --no-session-persistence \
    --tools "Bash,Read,Grep" \
    --max-turns "$4" \
    --debug-file "$5" \
    > "$6" 2>"$7"
' _ "$WORKTREE" "$PROMPT_FILE" "$MODEL" "$MAX_TURNS" "$DEBUG_LOG" "$TRANSCRIPT" "$STDERR_LOG"

EXIT_CODE=$?
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

if [ $EXIT_CODE -eq 124 ]; then
    echo "[run_trial] TIMEOUT after ${TIMEOUT_SEC}s"
elif [ $EXIT_CODE -ne 0 ]; then
    echo "[run_trial] claude -p exited with code $EXIT_CODE"
fi

# ── Extract the final result line from the transcript ──
# The result line has type=result and contains usage stats, cost, duration.
python3 -c "
import json, sys
result = None
for line in open('$TRANSCRIPT'):
    line = line.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
        if obj.get('type') == 'result':
            result = obj
    except json.JSONDecodeError:
        continue

if result:
    with open('$RESULT', 'w') as f:
        json.dump(result, f, indent=2)
    turns = result.get('num_turns', '?')
    dur = result.get('duration_ms', '?')
    cost = result.get('total_cost_usd', '?')
    err = result.get('is_error', False)
    stop = result.get('stop_reason', '?')
    print(f'[run_trial] Done: turns={turns}, duration={dur}ms, cost=\${cost}, error={err}, stop={stop}')
else:
    # No result line — trial likely timed out or crashed
    with open('$RESULT', 'w') as f:
        json.dump({
            'type': 'result',
            'subtype': 'timeout',
            'is_error': True,
            'duration_ms': $ELAPSED * 1000,
            'num_turns': 0,
            'result': 'Trial timed out or crashed',
            'total_cost_usd': 0,
            'usage': {}
        }, f, indent=2)
    print('[run_trial] WARNING: No result line in transcript (timeout or crash)')
" 2>&1

LINES=$(wc -l < "$TRANSCRIPT" 2>/dev/null || echo 0)
DEBUG_LINES=$(wc -l < "$DEBUG_LOG" 2>/dev/null || echo 0)
echo "[run_trial] Transcript: $TRANSCRIPT ($LINES lines)"
echo "[run_trial] Debug log:  $DEBUG_LOG ($DEBUG_LINES lines)"
echo "[run_trial] Stderr log: $STDERR_LOG"
