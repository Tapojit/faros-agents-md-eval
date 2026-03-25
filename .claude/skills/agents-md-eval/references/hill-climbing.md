# Hill-Climbing Loop

The AGENTS.md improves iteratively. Each iteration produces a SMALLER, more targeted file.

## The Automated Loop

`hill_climb.sh` runs the full pipeline:

```
0. INIT: Generate baseline AGENTS.md via `claude /init` on the repo
1. BASELINE: Run Haiku agents with /init AGENTS.md → get transcripts
2. GENERATE: Sonnet analyzes baseline transcripts → first improved AGENTS.md
3. IMPROVED: Run Haiku agents with improved AGENTS.md → get transcripts
4. GRADE: Deterministic graders
5. SHRINK: Sonnet analyzes improved transcripts + previous AGENTS.md → smaller version
6. REPEAT: Until size plateaus or pass@1 drops
```

## How AGENTS.md Generation Works

`generate_agents_md.py` does the following:

1. **Read transcripts** from the target iteration's results directory (`workspace/results/iteration-N/*/transcript.jsonl`)
2. **Classify tool calls** into exploration (ls, find, cat) vs. build (configure, make)
3. **Identify errors** from tool_result blocks with is_error=true or error keywords
4. **Build an analysis prompt** summarizing what agents struggled with
5. **Call claude -p (Sonnet)** with the analysis to generate the AGENTS.md
6. **For hill-climbing**: also include the previous AGENTS.md and a word count target

The generation prompt template is embedded in `generate_agents_md.py`. Key constraints:
- ONLY info the agent cannot discover from the repo
- NEVER architecture overviews, directory listings, or generic advice
- DO include: exact deps, exact build commands, known gotchas
- Target: under 120 words initially, shrink by ~20 words per iteration
- Every line must earn its place

## What "Better" Means

| Metric | Direction | Why |
|--------|-----------|-----|
| pass@1 | UP | Agent succeeds more often |
| total_tokens | DOWN | Less wasted context (cost follows) |
| n_tool_calls | DOWN | Agent knows what to do |
| wall_clock_seconds | DOWN | Faster completion |
| total_cost_usd | DOWN | Direct cost savings |
| agents_md_size_words | DOWN | Less is more |

## Graduation Criteria

A task graduates to regression when:
- pass@1 = 1.0 (all trials pass)
- For 3 consecutive iterations
- Baseline metrics recorded in history.json and regression.yaml

## Reversion

If a new AGENTS.md causes pass@1 to drop below the previous iteration, revert to the previous version. The hill-climb should be monotonically improving or stable.
