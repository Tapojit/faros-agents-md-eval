# Programmatic AGENTS.md Generation

**An eval-driven approach to creating better AGENTS.md files using transcript-driven hill-climbing.**

|  | Baseline (/init) | Improved (hill-climbed) | Delta |
|--|-------------------|------------------------|-------|
| **pass@1** | 5/5 | 5/5 | — |
| **avg turns** | 12.6 | 4.8 | **↓ 62%** |
| **avg wall clock** | 80.7s | 37.7s | **↓ 53%** |
| **avg tokens** | 392,747 | 344,411 | **↓ 12%** |

> **[Download the slide deck →](results/faros-presentation.pptx)** · **[Open the interactive eval viewer →](https://tapojit.github.io/faros-agents-md-eval/results/eval-viewer.html)** (live — explore full transcripts, tool call sequences, and per-trial metrics)

---

## Table of Contents

- [The Problem](#the-problem)
- [Defining "Better"](#defining-better)
- [Approach 1: Naive Generation (Discarded)](#approach-1-naive-generation-discarded)
- [Approach 2: Transcript-Driven Hill-Climbing (Final)](#approach-2-transcript-driven-hill-climbing-final)
- [Architecture: Three Roles](#architecture-three-roles)
- [Evaluation Framework](#evaluation-framework)
- [Results](#results)
- [The Final AGENTS.md](#the-final-agentsmd)
- [Approach 3: Skills + Plugins (Outperforms)](#approach-3-skills--plugins-outperforms)
- [Tradeoffs](#tradeoffs)
- [Future Work](#future-work)
- [Reproducing](#reproducing)
- [References](#references)

---

## The Problem

An AGENTS.md file is a "README for machines" — a markdown document at the root of a repository that tells AI coding agents how to work within the codebase. Most agents auto-generate a basic version via `/init`.

But research shows this often **hurts** performance:

> **ETH Zurich (arXiv 2602.11988):** Verbose auto-generated AGENTS.md files increase cost by 20%+ while reducing success rates. Agents follow instructions obediently — even when the instructions are unnecessary or wrong for the task at hand.

The problem is that auto-generated files optimize for **coverage** (mention everything) rather than **outcomes** (help the agent succeed). They reproduce information already available in the repo, add architectural overviews agents can't use, and pad context windows with generic best practices.

**Goal:** Programmatically create a "better" version — one that measurably improves agent performance.

---

## Defining "Better"

"Better" is not subjective. I defined a metric hierarchy and built an eval harness to measure it:

| Priority | Metric | Why |
|----------|--------|-----|
| **P0** | **pass@1** | Did the agent succeed on first try? Non-negotiable. |
| **P1** | **turns** | Fewer turns = agent knew what to do. Most direct signal of guidance quality. |
| **P1** | **wall clock** | User-facing latency. Directly impacts UX. |
| **P2** | **total tokens** | Cost proxy. Fewer tokens = cheaper per task. |
| **P2** | **AGENTS.md size** | Context overhead. Smaller = more room for user context. |

**Key tradeoff observed:** Cost stayed flat (~$0.09/trial in both conditions) while turns dropped 62%. The improved AGENTS.md doesn't save money directly — it saves *time*. For outcome-based pricing, fewer turns at the same pass rate means higher throughput per dollar.

---

## Approach 1: Naive Generation (Discarded)

### What I tried

Generate an AGENTS.md by pointing a strong model at the CPython repo without modifying anything. The model reads the codebase and writes build instructions based on what it finds. Simple — no worktrees, no transcripts, no grading pipeline.

### Why it failed

The repo was full of build hints: `README.rst`, `Doc/`, `.github/CONTRIBUTING.rst`, `PCbuild/readme.txt`, `Mac/README.rst`.

The agent just **parroted in-tree docs** into the AGENTS.md. A weak agent could find those same docs itself, so the AGENTS.md added zero value. The file was verbose (~2,000 words) and full of information already discoverable from the repository.

### Lesson learned

> Strip all discoverable hints first, then generate instructions for what remains non-obvious.

This insight led directly to the doc-stripping step in Approach 2: `strip_build_hints.sh` removes 556 files (README, Doc/, CONTRIBUTING, etc.) and commits the deletion so every eval worktree inherits the clean state.

---

## Approach 2: Transcript-Driven Hill-Climbing (Final)

The core idea: **use eval metrics as the objective function** and hill-climb the AGENTS.md generator. Each iteration produces a smaller, more focused file. Improvements are measured, not assumed.

### The Loop

```
1. INIT      → Generate baseline AGENTS.md via `claude /init`
2. BASELINE  → Run agents (Haiku) with baseline AGENTS.md → get transcripts
3. ANALYZE   → Sonnet reads transcripts, identifies where agents struggled
4. GENERATE  → Sonnet produces targeted AGENTS.md addressing specific failures
5. GRADE     → Deterministic graders: binary exists? imports work? tests pass?
6. COMPARE   → Metrics table: pass@1, tokens, tool calls, wall clock, cost
7. SHRINK    → Sonnet analyzes improved transcripts → even smaller AGENTS.md
8. REPEAT    → Until AGENTS.md size plateaus or pass@1 drops
```

### Key Design Decisions

**Weak agent (Haiku 4.5).** The whole point is measuring whether AGENTS.md helps an agent that *needs* the help. Haiku is more likely to struggle without guidance, which makes the AGENTS.md delta visible in the data. If Sonnet passes 100% regardless, the eval is useless. Haiku is the lower bound — if AGENTS.md helps Haiku, it helps everything.

**Strong generator (Sonnet 4.6).** The AGENTS.md generator needs to read transcripts, identify failure patterns, and write precise instructions. This requires stronger reasoning than the build task itself.

**Doc stripping.** `strip_build_hints.sh` removes all in-tree documentation (README, Doc/, CONTRIBUTING, etc.) from the repo and commits the deletion. Every worktree inherits this clean state. The eval measures AGENTS.md quality, not the agent's ability to find built-in docs.

**JSONL transcripts.** All agent trials run via `claude -p --output-format stream-json --verbose`, producing a full JSONL transcript of every message, tool call, tool result, and thinking block. Transcripts are the source of truth — same transcript produces the same metrics, always. This also enables the generator to analyze exactly where agents failed.

**Shrink each iteration.** Research shows verbose AGENTS.md files hurt performance. Each hill-climbing iteration targets a smaller file. The final AGENTS.md is 55 words — every line addresses a specific failure mode observed in transcripts.

**AGENTS.md is never hand-written.** It's always generated — either by `/init` (baseline) or by Sonnet from transcript analysis (improved). This ensures the approach is reproducible and programmatic.

---

## Architecture: Three Roles

Conflating these roles is the #1 source of eval contamination.

| Role | Model | Job | Must NOT |
|------|-------|-----|----------|
| **Evaluator** | Scripts (bash, Python) | Orchestrate trials, run graders, extract metrics from JSONL transcripts | Execute the build task or leak context to agents |
| **Agent** | Haiku 4.5 (weak) | Execute the build task cold inside an isolated worktree | See evaluator context, prior trial results, or other trials |
| **Generator** | Sonnet 4.6 (strong) | Analyze transcripts, identify failures, produce targeted AGENTS.md | Execute the build task itself |

### Isolation Guarantees

Each trial agent is fully sandboxed:

- **Git worktrees:** Each trial runs in its own worktree — a full, independent copy of the repo
- **No `--add-dir`:** The agent is `cd`'d into the worktree. It cannot see the workspace, other trials, evaluator scripts, or metrics
- **`--disable-slash-commands`:** Prevents the agent from loading skills or commands from the orchestrator
- **Self-contained:** `setup_worktrees.sh` copies AGENTS.md and `build_env.sh` INTO each worktree — no workspace-level paths in prompts
- **Doc stripping:** In-tree docs removed and committed once; every worktree inherits the clean state
- **`--no-session-persistence`:** Trial sessions don't save to history, preventing cross-session leakage

---

## Evaluation Framework

### Deterministic Graders

Following the Anthropic evals principle: **grade outcomes, not paths.**

| Grader | Check | Type |
|--------|-------|------|
| `binary-exists` | `./python` or `./python.exe` exists in worktree | `file_exists` |
| `functional-test` | `./python -c "import ssl; import ctypes; import sqlite3; print('BUILD OK')"` | `exit_code` |
| `test-suite-smoke` | `./python -m test test_math test_string test_list -v --timeout 60` | `exit_code` |

All three must pass for `pass@1 = true`. No partial credit.

### Metrics from JSONL Transcripts

All metrics are extracted deterministically by `extract_metrics.py`:

| Metric | Source | Purpose |
|--------|--------|---------|
| `pass@1` | grading.json | Binary success — did the agent complete the task? |
| `total_tokens` | modelUsage in result | Cost proxy (input + output + cache) |
| `n_tool_calls` | count of tool_use blocks | Efficiency — fewer = agent knew what to do |
| `n_turns` | result.num_turns | Conversation length |
| `duration_ms` | result.duration_ms | Wall clock time |
| `total_cost_usd` | result.total_cost_usd | Direct cost from API |
| `n_tool_errors` | count of is_error results | Error rate / resilience |

---

## Results

**5 trials per condition · all passed · Haiku 4.5 · CPython v3.12.0**

| Metric | Baseline (/init, 30 words) | Improved (hill-climbed, 55 words) | Delta |
|--------|---------------------------|----------------------------------|-------|
| pass@1 | 5/5 | 5/5 | — |
| avg turns | 12.6 | 4.8 | ↓ 62% |
| avg tool calls | 14.4 | 11.6 | ↓ 19% |
| avg total tokens | 392,747 | 344,411 | ↓ 12% |
| avg wall clock | 80.7s | 37.7s | ↓ 53% |
| avg cost | $0.090 | $0.092 | ~flat |
| AGENTS.md size | 30 words | 55 words | +25 words |

### Per-Trial Variance

```
Baseline turns:  2,  11,  14,  15,  21   (high variance — agent sometimes guesses right)
Improved turns:  1,   4,   4,   6,   9   (tighter distribution — consistent guidance)
```

The baseline has extreme variance (σ = 6.7 turns) because without targeted guidance, the agent sometimes gets lucky and sometimes burns 21 turns exploring. The improved AGENTS.md tightens this distribution (σ = 2.9 turns) — it provides consistent guidance regardless of the agent's random exploration path.

**Statistical caveat:** n=5 per condition. The direction is clear, but with more compute budget I'd run 50 trials and compute bootstrap confidence intervals with a Mann-Whitney U test for significance.

> **[Open the interactive eval viewer →](https://tapojit.github.io/faros-agents-md-eval/results/eval-viewer.html)** to explore full transcripts, tool call sequences, and per-trial metrics.

All raw data: [`results/metrics.csv`](results/metrics.csv) · [`results/benchmark.json`](results/benchmark.json) · [`results/history.json`](results/history.json)

---

## The Final AGENTS.md

**55 words.** Generated by Sonnet 4.6 from baseline transcript analysis — never hand-written.

```markdown
## Build CPython from Source

**Prerequisites are already installed.** Source `build_env.sh` before every build
command — it sets `CPPFLAGS`, `LDFLAGS`, and `CPYTHON_CONFIGURE_EXTRA` (includes
`--with-openssl`) for Homebrew-installed deps.

source ./build_env.sh
./configure $CPYTHON_CONFIGURE_EXTRA
make -j$(sysctl -n hw.ncpu)

Verify: ./python.exe -c "import ssl, sqlite3, readline; print('OK')"

The built interpreter is ./python.exe (not ./python).
```

### Why Each Line Exists

Every line addresses a specific failure mode observed in baseline transcripts:

| Line | Failure it prevents |
|------|-------------------|
| "Source `build_env.sh`" | Baseline agents waste 3–5 turns hunting for dependency locations and header paths |
| `$CPYTHON_CONFIGURE_EXTRA` | Baseline agents guess wrong `--with-openssl` path, causing import failures |
| `make -j$(sysctl -n hw.ncpu)` | Eliminates single-threaded builds that 2x wall clock time |
| "`python.exe` not `python`" | macOS CPython build quirk: agents spend 3–5 turns debugging "binary not found" |

The full AGENTS.md files are in [`agents-md/`](agents-md/):
- [`init-baseline.md`](agents-md/init-baseline.md) — the /init-generated baseline (30 words)
- [`improved-iter1.md`](agents-md/improved-iter1.md) — the hill-climbed winner (55 words)

---

## Approach 3: Skills + Plugins (Outperforms)

While the hill-climbing eval proves that a better AGENTS.md helps, I believe **AGENTS.md as a format is a stepping stone, not the destination.**

| | AGENTS.md | Skills + Plugins |
|--|-----------|-----------------|
| **Structure** | Single monolithic file at repo root | Modular, composable units |
| **Execution** | Agent reads top-to-bottom, follows steps | Skills trigger independently based on task context |
| **Context loading** | All-or-nothing — entire file consumed every turn | Selective — only loads what's relevant |
| **Scaffolding** | Heavy: worktrees, transcript logging, graders, hill-climbing | Built-in: triggering, progressive disclosure, bundled scripts |
| **Sharing** | Copy-paste between repos | Versioned, installable, composable |

In practice, I used Anthropic's [`claude-md-management`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/claude-md-management) plugin — it auto-audits and improves CLAUDE.md files using structured templates and quality scoring, with a dual skill/command pattern that captures session learnings. No heavy eval harness needed.

This eval harness itself is packaged as a skill (not an AGENTS.md). It's 13 scripts, 6 commands, 4 reference docs — loaded only when needed, zero context cost otherwise. The same eval-driven approach that improves AGENTS.md should be applied to skills, plugins, and structured agent context. That's where the real leverage is.

---

## Tradeoffs

| Decision | Tradeoff |
|----------|----------|
| **Weak agent (Haiku) for testing** | Makes the AGENTS.md delta visible, but may not reflect real-world usage with Sonnet or Opus where the baseline already passes |
| **Single task (CPython build)** | Unknown if the approach generalizes to other repos or task types (test, lint, refactor) |
| **Deterministic graders only** | Can't evaluate code quality, style, or convention adherence — only binary pass/fail |
| **Doc stripping for fair eval** | Agents in production *will* have access to those docs; stripping creates a controlled experiment but diverges from real conditions |
| **100% baseline pass rate** | Both conditions pass 5/5, so the eval measures *efficiency*, not *capability*. A harder task where the baseline fails would show a starker pass@1 delta |

---

## Future Work

- **Multi-task eval suites.** Test AGENTS.md across build, test, lint, and refactor tasks to prove generalization beyond a single build task.
- **Skills+plugins hybrid.** Combine AGENTS.md for repo-level context with skills for task-specific workflows. Measure whether the hybrid outperforms either alone.
- **Model-based graders.** Add LLM-as-judge for code quality and transcript efficiency alongside deterministic pass/fail checks. Keep grading deterministic for pass@1; use LLM judge for richer signal.
- **Cross-repo transfer.** Can an AGENTS.md approach trained on CPython help with Node.js or Rust? Test whether the *process* transfers even if the *content* doesn't.
- **Per-section ablation.** Remove one line at a time from the AGENTS.md and re-run trials. Which lines actually matter? This could drive further shrinking.

---

## Reproducing

### Prerequisites

- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` command available)
- Python 3.9+
- Git
- GNU coreutils (`brew install coreutils` on macOS — needed for `timeout`)

### Quick Start

```bash
# Clone this repo
git clone https://github.com/yourusername/faros-agents-md-eval.git
cd faros-agents-md-eval

# The eval harness is a Claude Code skill — point SKILL_DIR at it
SKILL_DIR=".claude/skills/agents-md-eval"

# Run the full pipeline (3 iterations, 3 trials each, ~45 min)
bash "$SKILL_DIR/scripts/hill_climb.sh" workspace 3 haiku sonnet 3
```

Or step by step using the slash commands:

```
/eval-init            # Clone CPython, install deps, generate /init baseline
/eval-run baseline    # Run baseline trials (Haiku, with /init AGENTS.md)
/eval-run improved    # Generate improved AGENTS.md + run improved trials
/eval-metrics         # Display comparison tables
/agents-md-improve    # Hill-climb: shrink AGENTS.md, re-test
```

### Repo Structure

```
faros-agents-md-eval/
├── README.md                    # This file
├── .claude/skills/agents-md-eval/
│   ├── SKILL.md                 # Eval harness design doc
│   ├── commands/                # 6 slash commands
│   ├── eval-suites/             # Task definitions (YAML)
│   ├── references/              # Schema docs, grader docs
│   └── scripts/                 # 13 scripts (bash + Python)
├── results/
│   ├── metrics.csv              # All trial data
│   ├── benchmark.json           # Aggregated stats + deltas
│   ├── history.json             # Iteration progression
│   ├── eval-viewer.html         # Interactive transcript viewer
│   ├── faros-presentation.pptx  # Slide deck
│   └── iteration-*/             # Per-trial artifacts
└── agents-md/
    ├── init-baseline.md          # /init-generated (30 words)
    └── improved-iter1.md         # Hill-climbed winner (55 words)
```

---

## References

- **ETH Zurich: Evaluating AGENTS.md** — [arXiv 2602.11988](https://arxiv.org/abs/2602.11988). Verbose AGENTS.md files hurt performance; minimal is better.
- **Anthropic: Demystifying Evals for AI Agents** — [Blog post](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents). Tasks, trials, graders, transcripts — the eval framework vocabulary.
- **Anthropic: Skill Authoring Best Practices** — [Documentation](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices). Progressive disclosure, description optimization, script bundling.
- **Anthropic: claude-md-management plugin** — [GitHub](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/claude-md-management). Auto-audits CLAUDE.md quality + captures session learnings.
- **GitHub: How to Write Great agents.md** — [Blog post](https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/). Lessons from 2,500+ repositories.
- **Impact of AGENTS.md on Efficiency** — [arXiv 2601.20404](https://arxiv.org/html/2601.20404v1). 16.58% lower median runtime with AGENTS.md presence.

---

*Built by [Tapojit Debnath](mailto:tapojitdebnath@gmail.com) for the Faros AI take-home assignment.*
