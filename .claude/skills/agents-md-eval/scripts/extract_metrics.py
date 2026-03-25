#!/usr/bin/env python3
"""
extract_metrics.py — Deterministic metrics extraction from claude -p JSONL transcripts.

This is the SINGLE source of truth for all trial metrics. It replaces the old
record_metrics.sh approach where the evaluator manually extracted stats from
Agent tool responses. Now: transcript.jsonl → deterministic parse → exact numbers.

Usage:
  # Human-readable summary
  python3 extract_metrics.py transcript.jsonl --summary

  # JSON output (for programmatic use)
  python3 extract_metrics.py transcript.jsonl --json

  # CSV row (for appending to metrics.csv)
  python3 extract_metrics.py transcript.jsonl --csv-row baseline-t1 baseline 0 1 true 0

  # Just the CSV header
  python3 extract_metrics.py --csv-header

  # Write timing.json to trial directory (replaces record_metrics.sh)
  python3 extract_metrics.py transcript.jsonl --write-timing /path/to/trial_dir

What it extracts from the JSONL:
  - Every assistant message (with content type: text, tool_use, thinking)
  - Every tool result (with is_error flag)
  - Per-iteration token usage from the result object
  - Total cost, duration, stop_reason from the result object
  - Model name from the init object
  - Tool call sequence (name + input preview) for transcript analysis
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone


def parse_transcript(path: str) -> dict:
    """Parse a stream-json transcript and extract all metrics deterministically."""
    text = Path(path).read_text()
    lines = [l for l in text.strip().split('\n') if l.strip()]

    init_obj = None
    result_obj = None
    tool_uses = []         # Every tool_use block from assistant messages
    tool_results = []      # Every tool_result from user messages
    text_blocks = []       # Every text block from assistant messages
    thinking_blocks = []   # Every thinking block
    assistant_msg_ids = set()  # Unique assistant message IDs (for turn counting)

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get('type')

        if msg_type == 'system' and obj.get('subtype') == 'init':
            init_obj = obj

        elif msg_type == 'assistant':
            msg = obj.get('message', {})
            msg_id = msg.get('id', '')
            if msg_id:
                assistant_msg_ids.add(msg_id)

            for block in msg.get('content', []):
                btype = block.get('type')
                if btype == 'tool_use':
                    tool_uses.append({
                        'id': block.get('id', ''),
                        'name': block.get('name', ''),
                        'input': block.get('input', {}),
                    })
                elif btype == 'text':
                    text_blocks.append(block.get('text', ''))
                elif btype == 'thinking':
                    thinking_blocks.append(block.get('thinking', ''))

        elif msg_type == 'user':
            msg = obj.get('message', {})
            content = msg.get('content', [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_result':
                        tool_results.append({
                            'tool_use_id': block.get('tool_use_id', ''),
                            'content': str(block.get('content', ''))[:500],
                            'is_error': block.get('is_error', False),
                        })

        elif msg_type == 'result':
            result_obj = obj

    if not result_obj:
        return {'error': 'No result object found in transcript', 'transcript_lines': len(lines)}

    # ── Token extraction from result object ──
    usage = result_obj.get('usage', {})
    model_usage = result_obj.get('modelUsage', {})

    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_creation = 0
    model_name = 'unknown'

    if model_usage:
        for mname, mu in model_usage.items():
            model_name = mname  # Last model wins (usually only one)
            total_input += mu.get('inputTokens', 0)
            total_output += mu.get('outputTokens', 0)
            total_cache_read += mu.get('cacheReadInputTokens', 0)
            total_cache_creation += mu.get('cacheCreationInputTokens', 0)
    else:
        total_input = usage.get('input_tokens', 0)
        total_output = usage.get('output_tokens', 0)
        total_cache_read = usage.get('cache_read_input_tokens', 0)
        total_cache_creation = usage.get('cache_creation_input_tokens', 0)

    # Override model from init if available (more reliable)
    if init_obj and init_obj.get('model'):
        model_name = init_obj['model']

    # Total tokens: all tokens that flowed through the API
    total_tokens = total_input + total_output + total_cache_read + total_cache_creation

    # Duration
    duration_ms = result_obj.get('duration_ms', 0)
    duration_api_ms = result_obj.get('duration_api_ms', 0)

    # ── Build metrics dict ──
    n_turns = result_obj.get('num_turns', len(assistant_msg_ids))
    n_tool_calls = len(tool_uses)
    n_tool_errors = sum(1 for tr in tool_results if tr.get('is_error'))

    metrics = {
        'model': model_name,
        'n_turns': n_turns,
        'n_tool_calls': n_tool_calls,
        'n_tool_results': len(tool_results),
        'n_tool_errors': n_tool_errors,
        'total_tokens': total_tokens,
        'input_tokens': total_input,
        'output_tokens': total_output,
        'cache_read_tokens': total_cache_read,
        'cache_creation_tokens': total_cache_creation,
        'duration_ms': duration_ms,
        'duration_api_ms': duration_api_ms,
        'wall_clock_seconds': round(duration_ms / 1000, 1),
        'total_cost_usd': result_obj.get('total_cost_usd', 0),
        'stop_reason': result_obj.get('stop_reason', 'unknown'),
        'is_error': result_obj.get('is_error', False),
        'transcript_lines': len(lines),
        # For analysis: full tool call sequence
        'tool_calls': [
            {'name': tu['name'], 'input_preview': str(tu['input'])[:200]}
            for tu in tool_uses
        ],
        # Derived
        'tokens_per_turn': round(total_tokens / max(n_turns, 1), 1),
    }

    return metrics


def csv_header():
    return "trial_id,condition,iteration,trial_num,passed,model,n_turns,n_tool_calls,total_tokens,input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,tokens_per_turn,duration_ms,wall_clock_seconds,total_cost_usd,agents_md_size_words,stop_reason,transcript_lines,timestamp"


def csv_row(m, trial_id, condition, iteration, trial_num, passed, agents_md_words):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return f"{trial_id},{condition},{iteration},{trial_num},{passed},{m['model']},{m['n_turns']},{m['n_tool_calls']},{m['total_tokens']},{m['input_tokens']},{m['output_tokens']},{m['cache_read_tokens']},{m['cache_creation_tokens']},{m['tokens_per_turn']},{m['duration_ms']},{m['wall_clock_seconds']},{m['total_cost_usd']},{agents_md_words},{m['stop_reason']},{m['transcript_lines']},{ts}"


def write_timing_json(m, trial_dir):
    """Write timing.json in the same schema as the old record_metrics.sh, for backward compat."""
    timing = {
        "model": m['model'],
        "n_turns": m['n_turns'],
        "n_toolcalls": m['n_tool_calls'],
        "n_total_tokens": m['total_tokens'],
        "n_input_tokens": m['input_tokens'],
        "n_output_tokens": m['output_tokens'],
        "cache_read_tokens": m['cache_read_tokens'],
        "cache_creation_tokens": m['cache_creation_tokens'],
        "duration_ms": m['duration_ms'],
        "duration_api_ms": m['duration_api_ms'],
        "wall_clock_seconds": m['wall_clock_seconds'],
        "total_cost_usd": m['total_cost_usd'],
        "tokens_per_turn": m['tokens_per_turn'],
        "n_tool_errors": m['n_tool_errors'],
        "stop_reason": m['stop_reason'],
        "transcript_lines": m['transcript_lines'],
    }
    path = Path(trial_dir) / 'timing.json'
    path.write_text(json.dumps(timing, indent=2) + '\n')
    print(f"[extract_metrics] Wrote {path}")


def main():
    parser = argparse.ArgumentParser(description='Extract metrics from claude -p JSONL transcript')
    parser.add_argument('transcript', nargs='?', help='Path to transcript.jsonl')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--csv-header', action='store_true', help='Print CSV header only')
    parser.add_argument('--csv-row', nargs=6,
                        metavar=('TRIAL_ID', 'CONDITION', 'ITERATION', 'TRIAL_NUM', 'PASSED', 'AGENTS_MD_WORDS'),
                        help='Output as a single CSV row')
    parser.add_argument('--summary', action='store_true', help='Human-readable summary')
    parser.add_argument('--write-timing', metavar='TRIAL_DIR',
                        help='Write timing.json to trial directory')
    parser.add_argument('--tool-sequence', action='store_true',
                        help='Print tool call sequence (for transcript analysis)')
    args = parser.parse_args()

    if args.csv_header:
        print(csv_header())
        return

    if not args.transcript:
        parser.error('transcript path required (unless using --csv-header)')

    metrics = parse_transcript(args.transcript)

    if 'error' in metrics:
        print(f"ERROR: {metrics['error']}", file=sys.stderr)
        sys.exit(1)

    if args.write_timing:
        write_timing_json(metrics, args.write_timing)

    if args.csv_row:
        tid, cond, it, tn, passed, mdw = args.csv_row
        print(csv_row(metrics, tid, cond, it, tn, passed, mdw))
    elif args.summary or (not args.json and not args.csv_row and not args.tool_sequence):
        print(f"Model:            {metrics['model']}")
        print(f"Turns:            {metrics['n_turns']}")
        print(f"Tool calls:       {metrics['n_tool_calls']} ({metrics['n_tool_errors']} errors)")
        print(f"Total tokens:     {metrics['total_tokens']:,}")
        print(f"  Input:          {metrics['input_tokens']:,}")
        print(f"  Output:         {metrics['output_tokens']:,}")
        print(f"  Cache read:     {metrics['cache_read_tokens']:,}")
        print(f"  Cache creation: {metrics['cache_creation_tokens']:,}")
        print(f"Duration:         {metrics['wall_clock_seconds']}s ({metrics['duration_ms']}ms)")
        print(f"API duration:     {metrics['duration_api_ms']}ms")
        print(f"Cost:             ${metrics['total_cost_usd']:.6f}")
        print(f"Stop reason:      {metrics['stop_reason']}")
        print(f"Transcript:       {metrics['transcript_lines']} lines")
        if args.tool_sequence or True:  # Always show in summary
            print(f"\nTool call sequence ({metrics['n_tool_calls']} calls):")
            for i, tc in enumerate(metrics['tool_calls'], 1):
                print(f"  {i:3d}. {tc['name']}: {tc['input_preview'][:100]}")
    elif args.json:
        print(json.dumps(metrics, indent=2))
    elif args.tool_sequence:
        for i, tc in enumerate(metrics['tool_calls'], 1):
            print(f"{i:3d}. {tc['name']}: {tc['input_preview']}")


if __name__ == '__main__':
    main()
