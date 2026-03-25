# Presentation Data

All metrics are stored in `workspace/results/metrics.csv` for direct import into slides. Benchmark summaries in `workspace/results/benchmark.json`.

## Slide Mapping

| Slide | Data Source | Query |
|-------|------------|-------|
| Baseline vs Improved table | metrics.csv | Group by `condition`, avg each metric |
| Hill-climbing progress | metrics.csv | Filter `condition=improved`, group by `iteration` |
| AGENTS.md shrinks as quality improves | history.json | Plot `agents_md_words` vs `pass_rate` per iteration |
| Token efficiency | metrics.csv | For passed trials: avg `n_total_tokens`. For failed: wasted tokens total. Model recorded per row for cost computation. |
| Transcript walkthrough | results/transcripts/ | Pick best failure (baseline) and best success (final improved) |

## Deltas to Highlight

The `benchmark.json` `deltas` section has pre-computed percentage changes between baseline and best iteration. Lead with these in the presentation:
- "Pass@1: 0% -> 100%"
- "Tokens: -78%"
- "Turns: -72%"
- "AGENTS.md size: -85%"

Cost can be computed from `model` + `n_input_tokens` + `n_output_tokens` using current pricing. The CSV records all three so this is straightforward to do at presentation time.
