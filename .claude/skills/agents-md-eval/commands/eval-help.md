Quick reference for agents-md-eval commands.

## Commands

| Command | Purpose |
|---------|---------|
| `/eval-init` | Set up repo, deps, generate /init baseline AGENTS.md |
| `/eval-run condition=X iteration=N` | Run trials, grade, record metrics |
| `/eval-metrics` | Display comparison tables from CSV |
| `/agents-md-improve iteration=N` | Analyze transcripts, generate smaller AGENTS.md |
| `/eval-regress` | Run regression suite on graduated tasks |
| `/eval-help` | This help text |

## Typical workflow

1. `/eval-init` — one-time setup (creates workspace, installs deps, generates /init baseline AGENTS.md)
2. `/eval-run condition=baseline iteration=0` — establish baseline (with /init AGENTS.md)
3. `/eval-run condition=improved iteration=1` — test the hill-climbed AGENTS.md
4. `/eval-metrics` — compare baseline vs improved
5. `/agents-md-improve` — analyze transcripts, generate a smaller AGENTS.md
6. `/eval-run condition=improved iteration=2` — test the improvement
7. `/eval-regress` — check for regressions
8. Repeat 5–7, incrementing iteration number each time

## Key files

- `workspace/results/metrics.csv` — all trial data (import into slides)
- `workspace/results/benchmark.json` — pre-computed deltas
- `workspace/results/iteration-N/` — per-trial transcripts, grading, timing
- `workspace/history.json` — iteration progression
- `workspace/agents-md/init-baseline.md` — /init-generated baseline AGENTS.md
- `workspace/agents-md/improved-iter*.md` — hill-climbed AGENTS.md versions
- `workspace/worktrees/` — ephemeral execution environments (can be torn down)
