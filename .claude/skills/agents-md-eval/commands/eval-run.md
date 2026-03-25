Run eval trials using `claude -p` with full JSONL transcript logging. Everything is automated — worktrees, prompts, trials, grading, metrics extraction.

## Quick Path

If the user just wants to run the full pipeline:
```bash
bash "$SKILL_DIR/scripts/hill_climb.sh" workspace 3 haiku sonnet 3
```
This generates /init baseline → runs baseline → generates improved AGENTS.md → runs improved → hill-climbs. Skip to the results.

## Step-by-Step Path

### 1. Run baseline (if not already done)

The baseline uses a /init-generated AGENTS.md. Make sure it exists at `workspace/agents-md/init-baseline.md` (created by `/eval-init` or `hill_climb.sh`).

```bash
bash "$SKILL_DIR/scripts/run_eval.sh" workspace baseline 0 haiku 3 workspace/agents-md/init-baseline.md
```
This creates worktrees under `workspace/worktrees/`, writes prompts, runs 3 Haiku agents via `claude -p`, grades all trials, extracts metrics from JSONL transcripts, and appends to `metrics.csv`. All trial artifacts (transcripts, grading, timing) go to `workspace/results/iteration-0/`.

Each trial produces `transcript.jsonl` — the full record of every tool call and result.

### 2. Generate improved AGENTS.md from baseline transcripts
```bash
python3 "$SKILL_DIR/scripts/generate_agents_md.py" \
    --workspace workspace --iteration 1 --model sonnet
```
Sonnet reads the baseline transcripts from `workspace/results/iteration-0/`, identifies where Haiku struggled (wasted exploration, errors, retries), and generates a minimal AGENTS.md addressing exactly those pain points.

To preview the analysis without calling claude -p:
```bash
python3 "$SKILL_DIR/scripts/generate_agents_md.py" \
    --workspace workspace --iteration 1 --dry-run
```

### 3. Run improved trials with generated AGENTS.md
```bash
bash "$SKILL_DIR/scripts/run_eval.sh" workspace improved 1 haiku 3 \
    workspace/agents-md/improved-iter1.md
```

### 4. Compare results
```bash
python3 "$SKILL_DIR/scripts/display_metrics.py" --csv workspace/results/metrics.csv
```

### 5. Hill-climb (shrink AGENTS.md)
```bash
python3 "$SKILL_DIR/scripts/generate_agents_md.py" \
    --workspace workspace --iteration 2 --model sonnet \
    --previous-agents-md workspace/agents-md/improved-iter1.md

bash "$SKILL_DIR/scripts/run_eval.sh" workspace improved 2 haiku 3 \
    workspace/agents-md/improved-iter2.md
```

## What Each Script Does

**`run_eval.sh`** is the main workhorse. For each trial it:
1. Creates a git worktree under `workspace/worktrees/` (via `setup_worktrees.sh`)
2. Writes `prompt.txt` to `workspace/results/` — the exact prompt the agent receives
3. Runs `claude -p --output-format stream-json --verbose` → `transcript.jsonl` (in results/)
4. Grades with `run_graders.sh` → `grading.json` (in results/)
5. Extracts metrics with `extract_metrics.py` → `timing.json` + CSV row (in results/)
6. Aggregates with `aggregate_benchmark.py`

**`run_trial.sh`** is the atomic unit — one trial, one transcript. The agent is `cd`'d into the worktree with no `--add-dir`, so it can only see files inside the worktree (source code + AGENTS.md + build_env.sh). Transcript and result go to a separate results dir.

**`extract_metrics.py`** deterministically parses `transcript.jsonl`. No manual extraction. Outputs:
- `--summary` → human-readable
- `--json` → full metrics dict
- `--csv-row` → append to metrics.csv
- `--write-timing` → timing.json (backward compat)
- `--tool-sequence` → ordered list of every tool call (for transcript analysis)

**`generate_agents_md.py`** analyzes transcripts from `workspace/results/`:
- Reads all `transcript.jsonl` files from an iteration's results
- Classifies tool calls (exploration vs. build)
- Identifies errors and wasted effort
- Calls `claude -p` (Sonnet) with the analysis to generate AGENTS.md
- For hill-climbing: also receives the previous AGENTS.md and targets a smaller version

## Prompt Design

Both baseline and improved conditions get the same prompt structure — both tell the agent to read AGENTS.md. The asymmetry is in the AGENTS.md *content*:

- **Baseline:** /init-generated AGENTS.md (generic auto-generated guidance)
- **Improved:** Hill-climbed AGENTS.md (targeted guidance from transcript analysis)

## Isolation

Each trial agent is fully sandboxed:
- Agent runs `cd`'d into worktree — no `--add-dir`, no access to workspace
- `--disable-slash-commands` prevents loading orchestrator skills
- `--tools "Bash,Read,Grep"` — only tools needed for the build task
- build_env.sh is copied INTO the worktree by `setup_worktrees.sh`
- Prompts use relative paths only (`./AGENTS.md`, `./build_env.sh`)

## Important

- Trials run sequentially (CPU contention + rate limits with parallel claude -p)
- Timeout: 600 seconds per trial via `run_trial.sh`
- `$SKILL_DIR` was set during `/eval-init`
- All scripts run via `bash`/`python3` — no execute bit needed
- Worktrees are in `workspace/worktrees/`, results in `workspace/results/`
