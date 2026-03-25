#!/usr/bin/env python3
"""
aggregate_benchmark.py - Generate benchmark.json and update history.json from metrics.csv.

Reads all trial data, computes per-iteration aggregates, calculates deltas
between baseline and best iteration.

Usage:
    python3 scripts/aggregate_benchmark.py
    python3 scripts/aggregate_benchmark.py --workspace workspace
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


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


def load_csv(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        print(f"[error] No metrics CSV at {csv_path}")
        sys.exit(1)
    with open(csv_path) as f:
        return list(csv.DictReader(f))


def aggregate_iteration(trials: list[dict]) -> dict:
    n = len(trials)
    passed = sum(1 for t in trials if t.get("passed", "").lower() == "true")
    # Collect unique models used in this iteration
    models = list({t.get("model", "unknown") for t in trials})
    return {
        "trials": n,
        "pass_rate": round(passed / max(n, 1), 2),
        "model": models[0] if len(models) == 1 else models,
        "metrics": {
            "avg_tokens": round(sum(safe_float(t.get("total_tokens", 0)) for t in trials) / max(n, 1)),
            "avg_input_tokens": round(sum(safe_float(t.get("input_tokens", 0)) for t in trials) / max(n, 1)),
            "avg_output_tokens": round(sum(safe_float(t.get("output_tokens", 0)) for t in trials) / max(n, 1)),
            "avg_turns": round(sum(safe_float(t.get("n_turns", 0)) for t in trials) / max(n, 1), 1),
            "avg_wall_clock": round(sum(safe_float(t.get("wall_clock_seconds", 0)) for t in trials) / max(n, 1), 1),
            "avg_toolcalls": round(sum(safe_float(t.get("n_tool_calls", 0)) for t in trials) / max(n, 1), 1),
        },
        "agents_md_words": safe_int(trials[0].get("agents_md_size_words", 0)),
    }


def compute_deltas(baseline: dict, best: dict) -> dict:
    deltas = {}
    deltas["pass_rate"] = f"+{best['pass_rate'] - baseline['pass_rate']:.2f}"

    for key in ["avg_tokens", "avg_turns", "avg_wall_clock"]:
        bv = baseline["metrics"].get(key, 0)
        iv = best["metrics"].get(key, 0)
        if bv > 0:
            pct = ((iv - bv) / bv) * 100
            deltas[key.replace("avg_", "")] = f"{pct:+.0f}%"
        else:
            deltas[key.replace("avg_", "")] = "N/A"

    bw = baseline.get("agents_md_words", 0)
    iw = best.get("agents_md_words", 0)
    if bw > 0:
        deltas["agents_md_words"] = f"{((iw - bw) / bw) * 100:+.0f}%"
    else:
        deltas["agents_md_words"] = "N/A"

    return deltas


def main():
    parser = argparse.ArgumentParser(description="Aggregate benchmark from metrics.csv")
    parser.add_argument("--workspace", default="workspace", help="Workspace directory")
    args = parser.parse_args()

    ws = Path(args.workspace)
    csv_path = ws / "results" / "metrics.csv"
    benchmark_path = ws / "results" / "benchmark.json"
    history_path = ws / "history.json"

    rows = load_csv(csv_path)

    # Group by iteration
    by_iter = defaultdict(list)
    for r in rows:
        by_iter[safe_int(r.get("iteration", 0))].append(r)

    # Build iteration summaries
    iterations = []
    for iter_num in sorted(by_iter.keys()):
        trials = by_iter[iter_num]
        agg = aggregate_iteration(trials)
        agg["iteration"] = iter_num
        agg["condition"] = trials[0].get("condition", "unknown")
        iterations.append(agg)

    # Compute deltas between baseline (iter 0) and best
    best_iter = max(iterations, key=lambda x: (x["pass_rate"], -x["metrics"]["avg_tokens"]))
    baseline_iter = iterations[0] if iterations else None

    deltas = {}
    if baseline_iter and best_iter and baseline_iter != best_iter:
        deltas = compute_deltas(baseline_iter, best_iter)

    # Write benchmark.json
    benchmark = {
        "task": "build-cpython-from-source",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "iterations": iterations,
        "best_iteration": best_iter["iteration"] if best_iter else None,
        "deltas": deltas,
    }

    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    with open(benchmark_path, "w") as f:
        json.dump(benchmark, f, indent=2)
    print(f"[benchmark] Written to {benchmark_path}")

    # Update history.json
    history = {"started_at": "", "repo": "cpython", "task": "build-cpython-from-source", "current_best": "", "iterations": [], "graduated_tasks": []}
    if history_path.exists():
        with open(history_path) as f:
            history = json.load(f)

    if not history.get("started_at"):
        history["started_at"] = datetime.now(timezone.utc).isoformat()

    # Rebuild iterations from benchmark data
    history["iterations"] = []
    for it in iterations:
        # Derive agents_md_file name from condition and iteration
        # baseline = no AGENTS.md (iteration 0), improved = has an AGENTS.md
        if it["condition"] == "baseline":
            md_file = None
        else:
            md_file = f"improved-iter{it['iteration']}.md"

        history["iterations"].append({
            "iteration": it["iteration"],
            "condition": it["condition"],
            "model": it.get("model", "unknown"),
            "agents_md_file": md_file,
            "agents_md_words": it["agents_md_words"],
            "pass_rate": it["pass_rate"],
            "avg_tokens": it["metrics"]["avg_tokens"],
            "avg_input_tokens": it["metrics"]["avg_input_tokens"],
            "avg_output_tokens": it["metrics"]["avg_output_tokens"],
            "avg_turns": it["metrics"]["avg_turns"],
            "avg_wall_clock": it["metrics"]["avg_wall_clock"],
            "is_current_best": it["iteration"] == best_iter["iteration"],
        })

    history["current_best"] = f"improved-iter{best_iter['iteration']}" if best_iter["iteration"] > 0 else "baseline"

    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)
    print(f"[history] Updated {history_path}")

    # Print summary
    if deltas:
        print(f"\n  Deltas (baseline -> best iter {best_iter['iteration']}):")
        for k, v in deltas.items():
            print(f"    {k}: {v}")
    print()


if __name__ == "__main__":
    main()
