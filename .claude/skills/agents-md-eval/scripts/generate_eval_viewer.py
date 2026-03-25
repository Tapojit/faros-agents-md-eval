#!/usr/bin/env python3
"""Generate a self-contained HTML viewer for agents-md-eval results.

Reads the workspace directory, discovers iterations and trials,
embeds all result data into a standalone HTML page.

Usage:
    python3 generate_eval_viewer.py <workspace-path> [--output PATH]
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path


def find_iterations(results_dir: Path) -> list[dict]:
    """Find all iteration directories and their trials."""
    iterations = []
    if not results_dir.is_dir():
        return iterations

    for iter_dir in sorted(results_dir.iterdir()):
        if not iter_dir.is_dir() or not iter_dir.name.startswith("iteration-"):
            continue
        try:
            iter_num = int(iter_dir.name.split("-")[1])
        except (IndexError, ValueError):
            continue

        trials = []
        for trial_dir in sorted(iter_dir.iterdir()):
            if not trial_dir.is_dir():
                continue
            trial = load_trial(trial_dir)
            if trial:
                trials.append(trial)

        if trials:
            iterations.append({
                "iteration": iter_num,
                "name": iter_dir.name,
                "trials": trials,
            })

    return iterations


def load_trial(trial_dir: Path) -> dict | None:
    """Load all available data for a single trial."""
    trial_id = trial_dir.name
    data = {"trial_id": trial_id, "dir": str(trial_dir)}

    # Load eval_metadata.json
    meta_path = trial_dir / "eval_metadata.json"
    if meta_path.exists():
        try:
            data["metadata"] = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            data["metadata"] = {}
    else:
        data["metadata"] = {}

    # Load grading.json
    grading_path = trial_dir / "grading.json"
    if grading_path.exists():
        try:
            data["grading"] = json.loads(grading_path.read_text())
        except (json.JSONDecodeError, OSError):
            data["grading"] = None
    else:
        data["grading"] = None

    # Load timing.json
    timing_path = trial_dir / "timing.json"
    if timing_path.exists():
        try:
            data["timing"] = json.loads(timing_path.read_text())
        except (json.JSONDecodeError, OSError):
            data["timing"] = None
    else:
        data["timing"] = None

    # Load prompt.txt
    prompt_path = trial_dir / "prompt.txt"
    if prompt_path.exists():
        try:
            data["prompt"] = prompt_path.read_text()
        except OSError:
            data["prompt"] = ""
    else:
        data["prompt"] = ""

    # Parse transcript into conversation flow for visualization
    transcript_path = trial_dir / "transcript.jsonl"
    if transcript_path.exists():
        try:
            data["transcript_size_bytes"] = transcript_path.stat().st_size
            data["conversation"] = parse_transcript_conversation(transcript_path)
        except OSError:
            data["transcript_size_bytes"] = 0
            data["conversation"] = []
    else:
        data["transcript_size_bytes"] = 0
        data["conversation"] = []

    return data


def parse_transcript_conversation(transcript_path: Path) -> list[dict]:
    """Parse a stream-json transcript into a compact conversation flow.

    Returns a list of message dicts, each with:
      - role: "system" | "assistant" | "user" | "result"
      - blocks: list of {type, content} where type is text/tool_use/tool_result/thinking
      - For tool_use: {type: "tool_use", name, input_preview}
      - For tool_result: {type: "tool_result", tool_name, content_preview, is_error}
    """
    MAX_PREVIEW = 800  # truncate long outputs to keep HTML manageable
    conversation = []
    # Map tool_use IDs to tool names for labeling results
    tool_id_to_name = {}

    text = transcript_path.read_text()
    for line in text.strip().split('\n'):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get('type')

        if msg_type == 'system' and obj.get('subtype') == 'init':
            conversation.append({
                "role": "system",
                "blocks": [{"type": "text", "content": f"Session initialized (model: {obj.get('model', '?')})"}],
            })

        elif msg_type == 'assistant':
            msg = obj.get('message', {})
            blocks = []
            for block in msg.get('content', []):
                btype = block.get('type')
                if btype == 'text':
                    t = block.get('text', '')
                    if t.strip():
                        blocks.append({"type": "text", "content": t})
                elif btype == 'tool_use':
                    tid = block.get('id', '')
                    name = block.get('name', '?')
                    tool_id_to_name[tid] = name
                    inp = block.get('input', {})
                    # Create a readable preview of the input
                    if isinstance(inp, dict):
                        preview = json.dumps(inp, indent=2, ensure_ascii=False)
                    else:
                        preview = str(inp)
                    if len(preview) > MAX_PREVIEW:
                        preview = preview[:MAX_PREVIEW] + '\n... (truncated)'
                    blocks.append({"type": "tool_use", "name": name, "input_preview": preview})
                elif btype == 'thinking':
                    t = block.get('thinking', '')
                    if t.strip():
                        preview = t if len(t) <= MAX_PREVIEW else t[:MAX_PREVIEW] + '\n... (truncated)'
                        blocks.append({"type": "thinking", "content": preview})
            if blocks:
                conversation.append({"role": "assistant", "blocks": blocks})

        elif msg_type == 'user':
            msg = obj.get('message', {})
            content = msg.get('content', [])
            blocks = []
            if isinstance(content, str):
                blocks.append({"type": "text", "content": content})
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, str):
                        blocks.append({"type": "text", "content": block})
                    elif isinstance(block, dict):
                        btype = block.get('type', '')
                        if btype == 'tool_result':
                            tid = block.get('tool_use_id', '')
                            tool_name = tool_id_to_name.get(tid, '?')
                            is_error = block.get('is_error', False)
                            # Extract text content from tool result
                            rc = block.get('content', '')
                            if isinstance(rc, list):
                                rc = '\n'.join(
                                    b.get('text', str(b)) if isinstance(b, dict) else str(b)
                                    for b in rc
                                )
                            rc = str(rc)
                            if len(rc) > MAX_PREVIEW:
                                rc = rc[:MAX_PREVIEW] + '\n... (truncated)'
                            blocks.append({
                                "type": "tool_result",
                                "tool_name": tool_name,
                                "content_preview": rc,
                                "is_error": is_error,
                            })
                        elif btype == 'text':
                            blocks.append({"type": "text", "content": block.get('text', '')})
            if blocks:
                conversation.append({"role": "user", "blocks": blocks})

        elif msg_type == 'result':
            stop = obj.get('stop_reason', obj.get('subtype', '?'))
            cost = obj.get('total_cost_usd', 0)
            dur = obj.get('duration_ms', 0)
            turns = obj.get('num_turns', 0)
            conversation.append({
                "role": "result",
                "blocks": [{"type": "text", "content": f"Finished: stop={stop}, turns={turns}, cost=${cost:.4f}, duration={dur/1000:.1f}s"}],
            })

    return conversation


def load_agents_md_files(workspace: Path) -> dict[str, str]:
    """Load all AGENTS.md versions from workspace/agents-md/."""
    agents_md = {}
    agents_dir = workspace / "agents-md"
    if not agents_dir.is_dir():
        return agents_md
    for f in sorted(agents_dir.iterdir()):
        if f.is_file() and f.suffix == ".md":
            try:
                agents_md[f.name] = f.read_text()
            except OSError:
                agents_md[f.name] = "(Error reading file)"
    return agents_md


def load_metrics_csv(workspace: Path) -> list[dict]:
    """Load metrics.csv as a list of dicts."""
    csv_path = workspace / "results" / "metrics.csv"
    if not csv_path.exists():
        return []
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except (OSError, csv.Error):
        return []


def load_benchmark(workspace: Path) -> dict | None:
    """Load benchmark.json if it exists."""
    bp = workspace / "results" / "benchmark.json"
    if not bp.exists():
        return None
    try:
        return json.loads(bp.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def load_history(workspace: Path) -> dict | None:
    """Load history.json if it exists."""
    hp = workspace / "history.json"
    if not hp.exists():
        return None
    try:
        return json.loads(hp.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def generate_html(data: dict) -> str:
    """Generate standalone HTML with embedded data."""
    template = VIEWER_TEMPLATE
    data_json = json.dumps(data)
    return template.replace("/*__EMBEDDED_DATA__*/", f"const DATA = {data_json};")


VIEWER_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AGENTS.md Eval Results</title>
<style>
:root {
  --bg: #f8f9fa;
  --surface: #ffffff;
  --surface-2: #f1f3f5;
  --border: #dee2e6;
  --border-light: #e9ecef;
  --text: #212529;
  --text-muted: #6c757d;
  --accent: #0d6efd;
  --accent-light: #e7f1ff;
  --green: #198754;
  --green-bg: #d1e7dd;
  --red: #dc3545;
  --red-bg: #f8d7da;
  --yellow: #cc8a00;
  --yellow-bg: #fff3cd;
  --radius: 6px;
  --font-mono: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  --shadow: 0 1px 3px rgba(0,0,0,0.08);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  font-size: 14px;
}

/* Header */
.header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 14px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: var(--shadow);
}
.header h1 { font-size: 16px; font-weight: 600; color: var(--text); }
.header h1 span { color: var(--accent); }
.header-stats { display: flex; gap: 20px; font-size: 12px; color: var(--text-muted); }
.header-stats .stat-value { color: var(--text); font-weight: 600; }

/* Tabs */
.tabs {
  display: flex;
  gap: 0;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
}
.tab {
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }

/* Main */
.main { padding: 24px; max-width: 1400px; margin: 0 auto; }

/* Cards */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 16px;
  overflow: hidden;
  box-shadow: var(--shadow);
}
.card-header {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--surface-2);
}
.card-header h3 { font-size: 13px; font-weight: 600; }
.card-body { padding: 16px; }

/* Badges */
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
.badge-pass { background: var(--green-bg); color: var(--green); }
.badge-fail { background: var(--red-bg); color: var(--red); }
.badge-baseline { background: var(--surface-2); color: var(--text-muted); border: 1px solid var(--border); }
.badge-improved { background: var(--accent-light); color: var(--accent); }

/* Tables */
.metrics-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.metrics-table th {
  text-align: left;
  padding: 8px 12px;
  font-weight: 600;
  color: var(--text-muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 2px solid var(--border);
  background: var(--surface-2);
}
.metrics-table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-light);
}
.metrics-table tr:last-child td { border-bottom: none; }
.metrics-table tr:hover td { background: var(--surface-2); }
.metrics-table .num { font-family: var(--font-mono); text-align: right; font-size: 12px; }
.metrics-table .better { color: var(--green); font-weight: 600; }
.metrics-table .worse { color: var(--red); font-weight: 600; }

/* Grading */
.grader-row { display: flex; gap: 8px; align-items: center; padding: 4px 0; }
.grader-name { flex: 1; font-size: 13px; }

/* Code/MD viewer */
.md-viewer {
  background: var(--surface-2);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  padding: 14px;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  max-height: 500px;
  overflow-y: auto;
  color: var(--text);
}

/* Summary cards */
.summary-row { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.summary-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 18px;
  flex: 1;
  min-width: 160px;
  box-shadow: var(--shadow);
}
.summary-card .label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; font-weight: 500; }
.summary-card .value { font-size: 22px; font-weight: 700; font-family: var(--font-mono); color: var(--text); }
.summary-card .delta { font-size: 12px; margin-top: 2px; }

/* Tab content */
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Iteration nav */
.iter-nav { display: flex; gap: 6px; margin-bottom: 16px; flex-wrap: wrap; }
.iter-btn {
  padding: 6px 14px;
  border-radius: var(--radius);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-muted);
  transition: all 0.15s;
}
.iter-btn:hover { border-color: var(--accent); color: var(--accent); }
.iter-btn.active { background: var(--accent-light); border-color: var(--accent); color: var(--accent); font-weight: 600; }

/* No data */
.no-data { text-align: center; color: var(--text-muted); padding: 48px; font-size: 14px; }

/* ── Transcript conversation view ── */
.transcript-container {
  max-height: 600px;
  overflow-y: auto;
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  background: var(--surface-2);
  padding: 12px;
}
.msg { margin-bottom: 10px; }
.msg-header {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 4px;
  padding: 2px 0;
}
.msg-header.role-assistant { color: var(--accent); }
.msg-header.role-user { color: var(--text-muted); }
.msg-header.role-system { color: var(--yellow); }
.msg-header.role-result { color: var(--green); }

.msg-block {
  margin-bottom: 6px;
  border-radius: 4px;
  font-size: 12px;
}
.msg-text {
  padding: 8px 10px;
  background: var(--surface);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-thinking {
  padding: 8px 10px;
  background: #fef9ef;
  border: 1px solid #f0e4c8;
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-muted);
  font-style: italic;
}
.msg-tool-use {
  border: 1px solid #cfe2ff;
  border-radius: 4px;
  overflow: hidden;
}
.msg-tool-use-header {
  background: #e7f1ff;
  padding: 6px 10px;
  font-weight: 600;
  font-size: 12px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #0a58ca;
}
.msg-tool-use-header:hover { background: #d0e3ff; }
.msg-tool-use-body {
  padding: 8px 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--surface);
  display: none;
  max-height: 300px;
  overflow-y: auto;
}
.msg-tool-use-body.open { display: block; }

.msg-tool-result {
  border: 1px solid var(--border-light);
  border-radius: 4px;
  overflow: hidden;
}
.msg-tool-result.error { border-color: #f1aeb5; }
.msg-tool-result-header {
  background: var(--surface-2);
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: var(--text-muted);
}
.msg-tool-result.error .msg-tool-result-header { background: #f8d7da; color: var(--red); }
.msg-tool-result-header:hover { background: var(--border-light); }
.msg-tool-result.error .msg-tool-result-header:hover { background: #f1aeb5; }
.msg-tool-result-body {
  padding: 8px 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--surface);
  display: none;
  max-height: 300px;
  overflow-y: auto;
}
.msg-tool-result-body.open { display: block; }

.toggle-arrow { font-size: 10px; transition: transform 0.15s; }
.toggle-arrow.open { transform: rotate(90deg); }
</style>
</head>
<body>
<script>
/*__EMBEDDED_DATA__*/
</script>
<script>
(function() {
  const d = typeof DATA !== 'undefined' ? DATA : {};
  const iterations = d.iterations || [];
  const agents_md = d.agents_md || {};
  const csv_rows = d.csv_rows || [];

  function computeSummary() {
    let bT = 0, bP = 0, bTok = 0, iT = 0, iP = 0, iTok = 0;
    for (const row of csv_rows) {
      const passed = row.passed === 'true' || row.passed === true;
      const tokens = parseInt(row.n_total_tokens || row.total_tokens || '0', 10);
      if (row.condition === 'baseline') { bT++; if (passed) bP++; bTok += tokens; }
      else { iT++; if (passed) iP++; iTok += tokens; }
    }
    return {
      baselinePassRate: bT ? (bP / bT * 100).toFixed(0) : '-',
      improvedPassRate: iT ? (iP / iT * 100).toFixed(0) : '-',
      baselineAvgTokens: bT ? Math.round(bTok / bT) : '-',
      improvedAvgTokens: iT ? Math.round(iTok / iT) : '-',
      totalTrials: csv_rows.length,
      totalIterations: iterations.length,
    };
  }

  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function renderHeader(s) {
    return `<div class="header"><div><h1><span>AGENTS.md</span> Eval Results</h1></div>
      <div class="header-stats">
        <span>Iterations: <span class="stat-value">${s.totalIterations}</span></span>
        <span>Trials: <span class="stat-value">${s.totalTrials}</span></span>
        <span>Baseline pass@1: <span class="stat-value">${s.baselinePassRate}%</span></span>
        <span>Improved pass@1: <span class="stat-value">${s.improvedPassRate}%</span></span>
      </div></div>`;
  }

  function renderTabs() {
    return `<div class="tabs">
      <div class="tab active" data-tab="overview">Overview</div>
      <div class="tab" data-tab="trials">Trials</div>
      <div class="tab" data-tab="transcripts">Transcripts</div>
      <div class="tab" data-tab="agents-md">AGENTS.md Versions</div>
      <div class="tab" data-tab="metrics">Metrics CSV</div>
    </div>`;
  }

  function passBadge(g) {
    const passed = g && g.summary ? g.summary.all_passed : null;
    if (passed === true) return '<span class="badge badge-pass">PASS</span>';
    if (passed === false) return '<span class="badge badge-fail">FAIL</span>';
    return '<span class="badge" style="background:var(--yellow-bg);color:var(--yellow)">?</span>';
  }
  function condBadge(c) {
    return c === 'baseline'
      ? '<span class="badge badge-baseline">baseline</span>'
      : '<span class="badge badge-improved">improved</span>';
  }

  function renderSummaryCards(s) {
    const td = (s.baselineAvgTokens !== '-' && s.improvedAvgTokens !== '-')
      ? ((s.improvedAvgTokens - s.baselineAvgTokens) / s.baselineAvgTokens * 100).toFixed(0) : null;
    const cls = td && parseInt(td) < 0 ? 'better' : (td && parseInt(td) > 0 ? 'worse' : '');
    const tds = td ? `${parseInt(td) > 0 ? '+' : ''}${td}%` : '';
    return `<div class="summary-row">
      <div class="summary-card"><div class="label">Baseline Pass@1</div><div class="value">${s.baselinePassRate}%</div></div>
      <div class="summary-card"><div class="label">Improved Pass@1</div><div class="value" style="color:var(--green)">${s.improvedPassRate}%</div></div>
      <div class="summary-card"><div class="label">Baseline Avg Tokens</div><div class="value">${typeof s.baselineAvgTokens==='number'?s.baselineAvgTokens.toLocaleString():s.baselineAvgTokens}</div></div>
      <div class="summary-card"><div class="label">Improved Avg Tokens</div><div class="value">${typeof s.improvedAvgTokens==='number'?s.improvedAvgTokens.toLocaleString():s.improvedAvgTokens}</div>${tds?`<div class="delta ${cls}">${tds} vs baseline</div>`:''}</div>
    </div>`;
  }

  function renderOverview(s) {
    let h = renderSummaryCards(s);
    const mdNames = Object.keys(agents_md).sort();
    if (mdNames.length) {
      h += `<div class="card"><div class="card-header"><h3>AGENTS.md Size Progression</h3></div><div class="card-body">
        <table class="metrics-table"><thead><tr><th>Version</th><th class="num">Words</th><th class="num">Chars</th></tr></thead><tbody>`;
      for (const n of mdNames) {
        const t = agents_md[n], w = t.split(/\s+/).filter(Boolean).length;
        h += `<tr><td>${n}</td><td class="num">${w.toLocaleString()}</td><td class="num">${t.length.toLocaleString()}</td></tr>`;
      }
      h += '</tbody></table></div></div>';
    }
    for (const iter of iterations) {
      h += `<div class="card"><div class="card-header"><h3>${iter.name}</h3><span style="font-size:12px;color:var(--text-muted)">${iter.trials.length} trials</span></div><div class="card-body">
        <table class="metrics-table"><thead><tr><th>Trial</th><th>Condition</th><th>Passed</th><th class="num">Tokens</th><th class="num">Tool Calls</th><th class="num">Duration</th><th class="num">AGENTS.md Words</th></tr></thead><tbody>`;
      for (const t of iter.trials) {
        const m=t.metadata||{}, g=t.grading||{}, tm=t.timing||{};
        h += `<tr><td>${t.trial_id}</td><td>${condBadge(m.condition)}</td><td>${passBadge(g)}</td>
          <td class="num">${tm.n_total_tokens?parseInt(tm.n_total_tokens).toLocaleString():'-'}</td>
          <td class="num">${tm.n_tool_calls||tm.n_toolcalls||'-'}</td>
          <td class="num">${tm.duration_ms?(parseInt(tm.duration_ms)/1000).toFixed(1)+'s':'-'}</td>
          <td class="num">${m.agents_md_words||'-'}</td></tr>`;
      }
      h += '</tbody></table></div></div>';
    }
    return h;
  }

  function renderTrials() {
    if (!iterations.length) return '<div class="no-data">No trial data found</div>';
    let h = '<div class="iter-nav">';
    iterations.forEach((it,i) => { h += `<button class="iter-btn ${i===0?'active':''}" data-iter="${i}">${it.name}</button>`; });
    h += '</div>';
    iterations.forEach((iter,i) => {
      h += `<div class="iter-panel" data-iter="${i}" style="${i?'display:none':''}">`;
      for (const t of iter.trials) {
        const g=t.grading||{}, m=t.metadata||{}, tm=t.timing||{};
        h += `<div class="card"><div class="card-header"><h3>${t.trial_id} ${passBadge(g)}</h3>${condBadge(m.condition)}</div><div class="card-body">`;
        if (g.graders) {
          h += '<div style="margin-bottom:10px"><strong style="font-size:11px;color:var(--text-muted)">GRADERS</strong>';
          for (const [n,r] of Object.entries(g.graders)) h += `<div class="grader-row"><span>${r.passed?'Pass':'Fail'}</span><span class="grader-name" style="margin-left:8px">${n}</span></div>`;
          h += '</div>';
        }
        if (Object.keys(tm).length) {
          h += '<table class="metrics-table" style="margin-bottom:10px">';
          const labels = {n_turns:'Turns',n_tool_calls:'Tool Calls',n_toolcalls:'Tool Calls',n_total_tokens:'Total Tokens',total_cost_usd:'Cost (USD)',duration_ms:'Duration',n_tool_errors:'Tool Errors',stop_reason:'Stop Reason',model:'Model'};
          for (const [k,v] of Object.entries(tm)) {
            let val=v;
            if(k==='total_cost_usd'&&typeof v==='number')val='$'+v.toFixed(4);
            else if(k==='n_total_tokens'&&typeof v==='number')val=v.toLocaleString();
            else if(k==='duration_ms'&&typeof v==='number')val=(v/1000).toFixed(1)+'s';
            h += `<tr><td>${labels[k]||k}</td><td class="num">${val}</td></tr>`;
          }
          h += '</table>';
        }
        if (t.transcript_size_bytes) h += `<div style="font-size:12px;color:var(--text-muted)">Transcript: ${(t.transcript_size_bytes/1024).toFixed(1)} KB</div>`;
        h += '</div></div>';
      }
      h += '</div>';
    });
    return h;
  }

  // ── Transcript conversation renderer ──
  function renderConversationBlock(block) {
    const id = 'tb_' + Math.random().toString(36).substr(2,8);
    if (block.type === 'text') return `<div class="msg-block msg-text">${esc(block.content)}</div>`;
    if (block.type === 'thinking') return `<div class="msg-block msg-thinking">${esc(block.content)}</div>`;
    if (block.type === 'tool_use') {
      return `<div class="msg-block msg-tool-use">
        <div class="msg-tool-use-header" onclick="var b=document.getElementById('${id}'),a=this.querySelector('.toggle-arrow');b.classList.toggle('open');a.classList.toggle('open')">
          <span>Tool: ${esc(block.name)}</span><span class="toggle-arrow">&#9654;</span>
        </div>
        <div class="msg-tool-use-body" id="${id}">${esc(block.input_preview||'')}</div>
      </div>`;
    }
    if (block.type === 'tool_result') {
      const errCls = block.is_error ? ' error' : '';
      const label = block.is_error ? 'Error' : 'Result';
      return `<div class="msg-block msg-tool-result${errCls}">
        <div class="msg-tool-result-header" onclick="var b=document.getElementById('${id}'),a=this.querySelector('.toggle-arrow');b.classList.toggle('open');a.classList.toggle('open')">
          <span>${label}: ${esc(block.tool_name||'?')}</span><span class="toggle-arrow">&#9654;</span>
        </div>
        <div class="msg-tool-result-body" id="${id}">${esc(block.content_preview||'')}</div>
      </div>`;
    }
    return '';
  }

  function renderConversation(conv) {
    if (!conv || !conv.length) return '<div style="color:var(--text-muted);font-size:13px;padding:12px">No transcript data</div>';
    let h = '';
    for (const msg of conv) {
      h += `<div class="msg"><div class="msg-header role-${msg.role}">${msg.role}</div>`;
      for (const b of (msg.blocks||[])) h += renderConversationBlock(b);
      h += '</div>';
    }
    return h;
  }

  function renderTranscripts() {
    if (!iterations.length) return '<div class="no-data">No transcript data found</div>';
    // Build a flat list of all trials with conversations
    let allTrials = [];
    for (const iter of iterations) {
      for (const t of iter.trials) {
        if (t.conversation && t.conversation.length) {
          allTrials.push({...t, iterName: iter.name});
        }
      }
    }
    if (!allTrials.length) return '<div class="no-data">No transcript data available. Transcripts are parsed from transcript.jsonl files in the results directory.</div>';

    let h = '<div class="iter-nav">';
    allTrials.forEach((t,i) => {
      const g = t.grading||{};
      const passed = g.summary ? g.summary.all_passed : null;
      const dot = passed===true ? ' style="border-left:3px solid var(--green)"' : (passed===false ? ' style="border-left:3px solid var(--red)"' : '');
      h += `<button class="iter-btn ${i===0?'active':''}" data-tpanel="${i}"${dot}>${t.trial_id}</button>`;
    });
    h += '</div>';

    allTrials.forEach((t,i) => {
      const m=t.metadata||{}, g=t.grading||{};
      h += `<div class="transcript-panel" data-tpanel="${i}" style="${i?'display:none':''}">
        <div class="card"><div class="card-header"><h3>${t.trial_id} ${passBadge(g)}</h3>${condBadge(m.condition)}</div>
        <div class="card-body"><div class="transcript-container">${renderConversation(t.conversation)}</div></div></div>
      </div>`;
    });
    return h;
  }

  function renderAgentsMd() {
    const names = Object.keys(agents_md).sort();
    if (!names.length) return '<div class="no-data">No AGENTS.md files found</div>';
    let h = '';
    for (const n of names) {
      const t = agents_md[n], w = t.split(/\s+/).filter(Boolean).length;
      h += `<div class="card"><div class="card-header"><h3>${n}</h3><span style="font-size:12px;color:var(--text-muted)">${w} words</span></div>
        <div class="card-body"><div class="md-viewer">${esc(t)}</div></div></div>`;
    }
    return h;
  }

  function renderMetricsCSV() {
    if (!csv_rows.length) return '<div class="no-data">No metrics.csv found</div>';
    const cols = Object.keys(csv_rows[0]);
    let h = '<div class="card"><div class="card-header"><h3>metrics.csv</h3><span style="font-size:12px;color:var(--text-muted)">'+csv_rows.length+' rows</span></div><div class="card-body" style="overflow-x:auto">';
    h += '<table class="metrics-table"><thead><tr>';
    for (const c of cols) h += `<th>${c}</th>`;
    h += '</tr></thead><tbody>';
    for (const row of csv_rows) {
      h += '<tr>';
      for (const c of cols) { const v=row[c]||''; h += `<td class="${!isNaN(v)&&v!==''&&v!=='true'&&v!=='false'?'num':''}">${v}</td>`; }
      h += '</tr>';
    }
    h += '</tbody></table></div></div>';
    return h;
  }

  // ── Render app ──
  const s = computeSummary();
  document.body.innerHTML = renderHeader(s) + renderTabs() + `<div class="main">
    <div class="tab-content active" data-tab="overview">${renderOverview(s)}</div>
    <div class="tab-content" data-tab="trials">${renderTrials()}</div>
    <div class="tab-content" data-tab="transcripts">${renderTranscripts()}</div>
    <div class="tab-content" data-tab="agents-md">${renderAgentsMd()}</div>
    <div class="tab-content" data-tab="metrics">${renderMetricsCSV()}</div>
  </div>`;

  // Tab switching
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.querySelector('.tab-content[data-tab="'+tab.dataset.tab+'"]').classList.add('active');
    });
  });
  // Iteration nav (trials tab)
  document.querySelectorAll('.iter-btn[data-iter]').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.closest('.tab-content').querySelectorAll('.iter-btn[data-iter]').forEach(b => b.classList.remove('active'));
      btn.closest('.tab-content').querySelectorAll('.iter-panel').forEach(p => p.style.display = 'none');
      btn.classList.add('active');
      btn.closest('.tab-content').querySelector('.iter-panel[data-iter="'+btn.dataset.iter+'"]').style.display = 'block';
    });
  });
  // Transcript nav
  document.querySelectorAll('.iter-btn[data-tpanel]').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.closest('.tab-content').querySelectorAll('.iter-btn[data-tpanel]').forEach(b => b.classList.remove('active'));
      btn.closest('.tab-content').querySelectorAll('.transcript-panel').forEach(p => p.style.display = 'none');
      btn.classList.add('active');
      btn.closest('.tab-content').querySelector('.transcript-panel[data-tpanel="'+btn.dataset.tpanel+'"]').style.display = 'block';
    });
  });
})();
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Generate eval viewer HTML")
    parser.add_argument("workspace", type=Path, help="Path to workspace directory")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="Output HTML path (default: workspace/results/eval-viewer.html)")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(f"Error: {workspace} is not a directory", file=sys.stderr)
        sys.exit(1)

    results_dir = workspace / "results"
    iterations = find_iterations(results_dir)
    agents_md = load_agents_md_files(workspace)
    csv_rows = load_metrics_csv(workspace)
    benchmark = load_benchmark(workspace)
    history = load_history(workspace)

    data = {
        "iterations": iterations,
        "agents_md": agents_md,
        "csv_rows": csv_rows,
        "benchmark": benchmark,
        "history": history,
    }

    html = generate_html(data)

    output_path = args.output or (results_dir / "eval-viewer.html")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    print(f"Eval viewer written to: {output_path}")


if __name__ == "__main__":
    main()
