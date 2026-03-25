#!/usr/bin/env python3
"""
display_metrics.py - Read workspace/results/metrics.csv and display comparison tables.

Usage:
    python3 scripts/display_metrics.py                        # latest comparison
    python3 scripts/display_metrics.py --iterations           # hill-climbing view
    python3 scripts/display_metrics.py --individual           # per-trial details
    python3 scripts/display_metrics.py --csv path/to/file.csv # custom path
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path


def load_csv(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        print(f"[error] No metrics file at {p}")
        sys.exit(1)
    with open(p) as f:
        return list(csv.DictReader(f))


def safe_float(v, default=0.0):
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def safe_int(v, default=0):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return default


def compare_conditions(rows: list[dict]):
    """Compare baseline vs improved for the latest iteration of each."""
    by_cond = defaultdict(list)
    for r in rows:
        by_cond[r["condition"]].append(r)

    print(f"\n{'='*72}")
    print(f"  Condition Comparison (pass@1 focus)")
    print(f"{'='*72}")

    col_w = 16
    conds = sorted(by_cond.keys())
    print(f"\n{'Metric':<24}" + "".join(f"{c:>{col_w}}" for c in conds))
    print("-" * (24 + col_w * len(conds)))

    for label, key, fmt in [
        ("trials", None, None),
        ("model", None, None),
        ("pass@1", None, None),
        ("avg turns", "n_turns", ".1f"),
        ("avg tool calls", "n_tool_calls", ".1f"),
        ("avg total tokens", "total_tokens", ",.0f"),
        ("avg input tokens", "input_tokens", ",.0f"),
        ("avg output tokens", "output_tokens", ",.0f"),
        ("avg wall clock (s)", "wall_clock_seconds", ".1f"),
        ("avg tokens/turn", "tokens_per_turn", ",.0f"),
        ("AGENTS.md words", "agents_md_size_words", None),
    ]:
        vals = []
        for c in conds:
            trials = by_cond[c]
            n = len(trials)
            if label == "trials":
                vals.append(f"{n:>{col_w}}")
            elif label == "model":
                model = trials[0].get("model", "?")
                # Truncate long model names to fit column
                if len(model) > col_w - 1:
                    model = model[:col_w - 1]
                vals.append(f"{model:>{col_w}}")
            elif label == "pass@1":
                passed = sum(1 for t in trials if t.get("passed", "").lower() == "true")
                vals.append(f"{passed}/{n}".rjust(col_w))
            elif label == "AGENTS.md words":
                v = safe_int(trials[0].get("agents_md_size_words", 0))
                vals.append(f"{v:>{col_w},}")
            else:
                avg = sum(safe_float(t.get(key, 0)) for t in trials) / max(n, 1)
                if fmt == ",.0f":
                    vals.append(f"{avg:>{col_w},.0f}")
                else:
                    vals.append(f"{avg:>{col_w}{fmt}}")
        print(f"{label:<24}{''.join(vals)}")
    print()


def show_iterations(rows: list[dict]):
    """Show hill-climbing progress across iterations."""
    by_iter = defaultdict(list)
    for r in rows:
        by_iter[safe_int(r.get("iteration", 0))].append(r)

    print(f"\n{'='*72}")
    print(f"  Hill-Climbing Progress Across Iterations")
    print(f"{'='*72}")

    iters = sorted(by_iter.keys())
    col_w = 14
    print(f"\n{'Metric':<22}" + "".join(f"{'iter ' + str(i):>{col_w}}" for i in iters))
    print("-" * (22 + col_w * len(iters)))

    for label, key, fmt in [
        ("condition", None, None),
        ("model", None, None),
        ("pass@1", None, None),
        ("avg tokens", "total_tokens", ",.0f"),
        ("avg turns", "n_turns", ".1f"),
        ("avg wall clock (s)", "wall_clock_seconds", ".1f"),
        ("AGENTS.md words", "agents_md_size_words", None),
    ]:
        vals = []
        for i in iters:
            trials = by_iter[i]
            n = len(trials)
            if label == "condition":
                vals.append(f"{trials[0].get('condition', '?'):>{col_w}}")
            elif label == "model":
                model = trials[0].get("model", "?")
                if len(model) > col_w - 1:
                    model = model[:col_w - 1]
                vals.append(f"{model:>{col_w}}")
            elif label == "pass@1":
                passed = sum(1 for t in trials if t.get("passed", "").lower() == "true")
                vals.append(f"{passed}/{n}".rjust(col_w))
            elif label == "AGENTS.md words":
                v = safe_int(trials[0].get("agents_md_size_words", 0))
                vals.append(f"{v:>{col_w},}")
            else:
                avg = sum(safe_float(t.get(key, 0)) for t in trials) / max(n, 1)
                if fmt == ",.0f":
                    vals.append(f"{avg:>{col_w},.0f}")
                else:
                    vals.append(f"{avg:>{col_w}{fmt}}")
        print(f"{label:<22}{''.join(vals)}")

    if len(iters) >= 2:
        first, last = by_iter[iters[0]], by_iter[iters[-1]]
        ft = sum(safe_float(t["total_tokens"]) for t in first) / max(len(first), 1)
        lt = sum(safe_float(t["total_tokens"]) for t in last) / max(len(last), 1)
        delta_pct = ((lt - ft) / ft * 100) if ft > 0 else 0
        fw = safe_int(first[0].get("agents_md_size_words", 0))
        lw = safe_int(last[0].get("agents_md_size_words", 0))
        print(f"\n  Tokens: {'DOWN' if delta_pct < 0 else 'UP'} {abs(delta_pct):.0f}% from iter {iters[0]} to {iters[-1]}")
        print(f"  AGENTS.md: {fw} -> {lw} words")
    print()


def show_individual(rows: list[dict]):
    """Show individual trial details."""
    print(f"\n{'trial_id':<24} {'iter':>4} {'pass':<6} {'model':<20} {'tokens':>10} {'turns':>6} {'time':>8}")
    print("-" * 80)
    for t in sorted(rows, key=lambda x: (safe_int(x.get("iteration", 0)), x.get("trial_id", ""))):
        status = "PASS" if t.get("passed", "").lower() == "true" else "FAIL"
        model = t.get("model", "?")
        if len(model) > 20:
            model = model[:20]
        print(
            f"{t.get('trial_id', '?'):<24} "
            f"{safe_int(t.get('iteration', 0)):>4} "
            f"{status:<6} "
            f"{model:<20} "
            f"{safe_int(t.get('total_tokens', 0)):>10,} "
            f"{safe_int(t.get('n_turns', 0)):>6} "
            f"{safe_float(t.get('wall_clock_seconds', 0)):>7.1f}s"
        )


def main():
    parser = argparse.ArgumentParser(description="Display eval metrics")
    parser.add_argument("--csv", default="workspace/results/metrics.csv")
    parser.add_argument("--iterations", action="store_true", help="Show hill-climbing progress")
    parser.add_argument("--individual", action="store_true", help="Show individual trials")
    args = parser.parse_args()

    rows = load_csv(args.csv)

    if args.iterations:
        show_iterations(rows)
    else:
        compare_conditions(rows)

    if args.individual:
        show_individual(rows)


if __name__ == "__main__":
    main()
