Generate an improved (smaller) AGENTS.md by analyzing transcripts from the previous iteration.

This is now automated via `generate_agents_md.py`. The script reads JSONL transcripts from `workspace/results/`, identifies waste and errors, and calls `claude -p` (Sonnet) to produce a more focused AGENTS.md.

## Determine iteration number

```bash
ls workspace/agents-md/
```
If `improved-iter{N}.md` exists → next iteration is N+1.

## Generate improved AGENTS.md

### Automated (preferred)

```bash
python3 "$SKILL_DIR/scripts/generate_agents_md.py" \
    --workspace workspace \
    --iteration {N+1} \
    --model sonnet \
    --previous-agents-md workspace/agents-md/improved-iter{N}.md
```

This:
1. Reads all `transcript.jsonl` files from `workspace/results/iteration-{N}`
2. Classifies tool calls (exploration vs. build) and identifies errors
3. Sends the analysis + current AGENTS.md to Sonnet with a shrink target
4. Writes the result to `workspace/agents-md/improved-iter{N+1}.md`

### Dry run (preview the analysis prompt)

```bash
python3 "$SKILL_DIR/scripts/generate_agents_md.py" \
    --workspace workspace --iteration {N+1} --dry-run \
    --previous-agents-md workspace/agents-md/improved-iter{N}.md
```

## Verify size reduction

```bash
wc -w workspace/agents-md/improved-iter*.md
```

The new file SHOULD be smaller. If it's larger, the generator drifted — re-run with a tighter target or manually trim.

## Test the improved version

```bash
bash "$SKILL_DIR/scripts/run_eval.sh" workspace improved {N+1} haiku 3 \
    workspace/agents-md/improved-iter{N+1}.md
```

Results go to `workspace/results/iteration-{N+1}/`. Worktrees go to `workspace/worktrees/iteration-{N+1}/`.

## Or run it all at once

```bash
bash "$SKILL_DIR/scripts/hill_climb.sh" workspace 3 haiku sonnet 3
```
