Display and analyze metrics from completed eval trials.

## Comparison table (baseline vs improved)
```bash
python3 "$SKILL_DIR/scripts/display_metrics.py" --csv workspace/results/metrics.csv
```

## Hill-climbing progress across all iterations
```bash
python3 "$SKILL_DIR/scripts/display_metrics.py" --csv workspace/results/metrics.csv --iterations
```

## Individual trial details
```bash
python3 "$SKILL_DIR/scripts/display_metrics.py" --csv workspace/results/metrics.csv --individual
```

## Full benchmark with deltas
```bash
python3 "$SKILL_DIR/scripts/aggregate_benchmark.py" --workspace workspace
cat workspace/results/benchmark.json | python3 -m json.tool
```

## After displaying, provide brief analysis (3-4 sentences max)

Focus on:
1. pass@1 difference between conditions
2. Token delta (absolute and %) — cost can be computed from model + token counts if needed
3. Turns delta (fewer = agent knew where to go)
4. AGENTS.md word count trend across iterations (should be shrinking)
5. Whether any task qualifies for graduation (100% for 3 consecutive iters)

The tables speak for themselves. Don't restate every number.

## For presentation prep

The files are ready for direct import:
- `workspace/results/metrics.csv` -- flat data for any tool (includes model name for downstream cost computation)
- `workspace/results/benchmark.json` -- pre-computed deltas for slide headlines
- `workspace/history.json` -- iteration progression for the hill-climbing chart

See [references/presentation-data.md](references/presentation-data.md) for how these map to specific slides.
