Run the regression eval suite to protect against backsliding.

Per the [Anthropic blog](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents): "As teams hill-climb on capability evals, it's important to also run regression evals to make sure changes don't cause issues elsewhere."

## Check for graduated tasks

```bash
cat workspace/eval-suites/regression.yaml
```

If `graduated_tasks` is empty:
> "No tasks have graduated to the regression suite yet. Tasks graduate when they achieve pass@1=1.0 for 3 consecutive iterations."

Check history.json to see if any task qualifies:
```bash
cat workspace/history.json | python3 -m json.tool
```

Look for 3+ consecutive iterations with `pass_rate: 1.0`. If found, update `workspace/eval-suites/regression.yaml` with the graduated task and its baseline metrics.

## If graduated tasks exist

1. Find the latest improved AGENTS.md:
   ```bash
   ls -t workspace/agents-md/improved-iter*.md | head -1
   ```

2. For each graduated task, run trials using the same `/eval-run` workflow but into a regression-specific iteration directory:
   ```bash
   bash "$SKILL_DIR/scripts/setup_worktrees.sh" workspace/repo workspace/worktrees/regression-check workspace/results/regression-check {condition} 3 {latest_agents_md}
   ```

3. Grade and record metrics as usual.

4. Compare results against graduation baseline:

   ```
   Task: build-cpython-from-source
   Graduated at: iteration 3
   Graduation metrics: tokens=9200, turns=5, wall_clock=58s

   Current results:
     pass@1: 3/3 ✓
     avg_tokens: 9500 (vs 9200 baseline, +3%) ✓ within tolerance
     avg_turns: 5 ✓

   VERDICT: NO REGRESSION
   ```

## Regression detection rules

- **Hard regression:** pass_rate drops below 1.0 → flag immediately, revert AGENTS.md
- **Soft regression:** tokens or turns increase >50% from graduation baseline → warn, investigate
- **Acceptable variance:** metrics within ±20% of graduation baseline → normal nondeterminism

## After running

- If no regression: "Regression suite passes. Safe to continue hill-climbing."
- If regression detected: "REGRESSION in {task}. Latest AGENTS.md (iter {N}) broke something that worked at iter {graduation_iter}. Recommend reverting to `improved-iter{N-1}.md` and investigating what changed."

Clean up regression worktrees:
```bash
bash "$SKILL_DIR/scripts/teardown_worktrees.sh" workspace/repo workspace/worktrees/regression-check
```
