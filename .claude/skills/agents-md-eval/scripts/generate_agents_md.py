#!/usr/bin/env python3
"""
generate_agents_md.py — Analyze baseline transcripts and generate an AGENTS.md.

This replaces manual AGENTS.md creation. It:
1. Reads baseline transcript.jsonl files from workspace/results/ to find where agents struggled
2. Identifies wasted tool calls, errors, and exploration overhead
3. Generates an AGENTS.md via claude -p that addresses exactly those pain points
4. Optionally hill-climbs an existing AGENTS.md (makes it smaller/better)

Usage:
  # Generate initial AGENTS.md from baseline transcripts
  python3 generate_agents_md.py --workspace /path/to/workspace --iteration 1 --model sonnet

  # Hill-climb an existing AGENTS.md (make it smaller, keep what works)
  python3 generate_agents_md.py --workspace /path/to/workspace --iteration 2 --model sonnet \
      --previous-agents-md /path/to/improved-iter1.md

  # Dry run: show the analysis prompt without calling claude -p
  python3 generate_agents_md.py --workspace /path/to/workspace --iteration 1 --dry-run

Outputs:
  workspace/agents-md/improved-iter{N}.md — the generated AGENTS.md

Note: Transcripts are read from workspace/results/iteration-N/ (the central
results directory), not from workspace/worktrees/ (which may have been torn down).
"""

import json
import argparse
import subprocess
import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime


def analyze_transcript(transcript_path: str) -> dict:
    """Extract key signals from a transcript for AGENTS.md generation."""
    lines = Path(transcript_path).read_text().strip().split('\n')

    tool_calls = []
    tool_errors = []
    all_commands = []
    error_outputs = []
    exploration_commands = []  # ls, find, cat, head — not directly building
    build_commands = []        # configure, make, gcc — actual build steps

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if obj.get('type') == 'assistant':
            for block in obj.get('message', {}).get('content', []):
                if block.get('type') == 'tool_use':
                    tc = {
                        'name': block.get('name', ''),
                        'input': block.get('input', {}),
                    }
                    tool_calls.append(tc)

                    # Classify commands
                    if tc['name'] == 'Bash':
                        cmd = tc['input'].get('command', '')
                        all_commands.append(cmd)
                        if any(kw in cmd for kw in ['ls', 'find', 'cat ', 'head ', 'file ', 'which ', 'dpkg', 'apt list']):
                            exploration_commands.append(cmd)
                        elif any(kw in cmd for kw in ['configure', 'make', 'gcc', 'pip', 'cmake']):
                            build_commands.append(cmd)

        elif obj.get('type') == 'user':
            content = obj.get('message', {}).get('content', [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_result':
                        if block.get('is_error'):
                            tool_errors.append({
                                'tool_use_id': block.get('tool_use_id', ''),
                                'content': str(block.get('content', ''))[:500],
                            })
                        # Also capture stderr-like output from non-error results
                        content_str = str(block.get('content', ''))
                        if any(kw in content_str.lower() for kw in ['error', 'not found', 'no such file', 'fatal', 'failed']):
                            error_outputs.append(content_str[:500])

    # Get result
    result = None
    for line in lines:
        try:
            obj = json.loads(line)
            if obj.get('type') == 'result':
                result = obj
        except Exception:
            continue

    return {
        'n_tool_calls': len(tool_calls),
        'n_exploration': len(exploration_commands),
        'n_build': len(build_commands),
        'n_errors': len(tool_errors),
        'exploration_commands': exploration_commands[:20],  # Cap for prompt length
        'build_commands': build_commands[:10],
        'error_outputs': error_outputs[:10],
        'all_commands': all_commands,
        'duration_ms': result.get('duration_ms', 0) if result else 0,
        'is_error': result.get('is_error', False) if result else True,
        'passed': not (result.get('is_error', True) if result else True),
    }


def build_generation_prompt(workspace: str, analyses: list, previous_md: str = None, iteration: int = 1) -> str:
    """Build the prompt for claude -p to generate/improve an AGENTS.md."""

    # Summarize baseline struggles
    summaries = []
    for i, a in enumerate(analyses, 1):
        summary = f"""Trial {i}:
  - Tool calls: {a['n_tool_calls']} total ({a['n_exploration']} exploration, {a['n_build']} build)
  - Errors encountered: {a['n_errors']}
  - Duration: {a['duration_ms']}ms
  - Passed: {a['passed']}
  - Exploration commands (wasted effort):
    {chr(10).join('    ' + c[:120] for c in a['exploration_commands'][:8])}
  - Error outputs:
    {chr(10).join('    ' + e[:200] for e in a['error_outputs'][:5])}
  - Build commands attempted:
    {chr(10).join('    ' + c[:120] for c in a['build_commands'][:8])}"""
        summaries.append(summary)

    trial_summary = '\n\n'.join(summaries)

    # Check if build_env.sh exists
    build_env_content = ""
    build_env_path = Path(workspace) / "build_env.sh"
    if build_env_path.exists():
        build_env_content = f"""
The workspace has a build_env.sh file with this content:
```
{build_env_path.read_text().strip()}
```
This file sets environment variables needed for the build. The AGENTS.md should tell the agent about it.
"""

    if previous_md:
        # Hill-climbing: improve existing AGENTS.md
        prompt = f"""You are improving an AGENTS.md file for a coding agent. Research shows that
verbose AGENTS.md files HURT agent performance (ETH Zurich, arXiv 2602.11988).

Current AGENTS.md (iteration {iteration - 1}):
```
{previous_md}
```

Trial results from the IMPROVED condition using this AGENTS.md:
{trial_summary}

{build_env_content}

Generate an improved AGENTS.md following these constraints:
- ONLY include info the agent cannot discover from the repo itself
- NEVER include architecture overviews, directory listings, or generic best practices
- DO include: exact dep install commands, exact build/configure commands, known gotchas
- The new version must be SMALLER than the current one ({len(previous_md.split())} words)
- Target: under {max(50, len(previous_md.split()) - 20)} words
- Every line must earn its place. If removing a line wouldn't change pass@1, remove it.
- If a trial failed, figure out why from the error outputs and add the missing info
- If all trials passed, focus on removing unnecessary lines to reduce size

Output ONLY the markdown content. No explanation, no preamble, no code fences around the whole thing."""
    else:
        # Initial generation from baseline transcripts
        prompt = f"""You are generating an AGENTS.md file for a CPython repository to help a coding agent
build it from source. Research shows that verbose AGENTS.md files HURT agent performance
(ETH Zurich, arXiv 2602.11988), so keep it minimal.

Here's what happened when agents tried to build CPython with only a basic /init-generated AGENTS.md (baseline):

{trial_summary}

{build_env_content}

The agents struggled with:
1. Finding where build dependencies/headers are located (non-standard paths)
2. Knowing the right configure flags (especially --with-openssl)
3. Wasted time exploring the filesystem instead of building

Generate an AGENTS.md that gives the agent EXACTLY the information it needs to avoid
these struggles. Follow these constraints:
- ONLY include info the agent cannot discover from the repo's own README/configure
- Focus on: the build_env.sh file location, what it does, and how to source it
- Include the verify command so the agent knows what success looks like
- Target: under 120 words. Every line must earn its place.
- Do NOT include generic advice, architecture overviews, or directory listings

Output ONLY the markdown content. No explanation, no preamble, no code fences around the whole thing."""

    return prompt


def main():
    parser = argparse.ArgumentParser(description='Generate or improve AGENTS.md from transcript analysis')
    parser.add_argument('--workspace', required=True, help='Workspace root directory')
    parser.add_argument('--iteration', required=True, type=int, help='Target iteration number')
    parser.add_argument('--model', default='sonnet', help='Model to use for generation (default: sonnet)')
    parser.add_argument('--previous-agents-md', help='Path to previous AGENTS.md (for hill-climbing)')
    parser.add_argument('--baseline-iteration', type=int, default=0, help='Which iteration has baseline transcripts (default: 0)')
    parser.add_argument('--previous-iteration', type=int, help='Which iteration to analyze for hill-climbing (default: iteration-1)')
    parser.add_argument('--dry-run', action='store_true', help='Print the generation prompt without calling claude -p')
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    output_path = workspace / 'agents-md' / f'improved-iter{args.iteration}.md'
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine which iteration's transcripts to analyze
    if args.previous_agents_md:
        # Hill-climbing: analyze the PREVIOUS improved iteration
        analyze_iter = args.previous_iteration if args.previous_iteration is not None else args.iteration - 1
        condition = 'improved'
    else:
        # Initial generation: analyze baseline
        analyze_iter = args.baseline_iteration
        condition = 'baseline'

    # Transcripts live in workspace/results/ (the central results directory)
    results_iter_dir = workspace / 'results' / f'iteration-{analyze_iter}'
    if not results_iter_dir.exists():
        print(f"[error] Results directory not found: {results_iter_dir}", file=sys.stderr)
        print(f"  Transcripts are stored in workspace/results/, not workspace/worktrees/", file=sys.stderr)
        sys.exit(1)

    # Find and analyze all transcripts for this condition
    print(f"[generate] Analyzing transcripts from results/iteration-{analyze_iter} ({condition})...")
    analyses = []
    for trial_dir in sorted(results_iter_dir.iterdir()):
        transcript = trial_dir / 'transcript.jsonl'
        if transcript.exists() and trial_dir.name.startswith(condition):
            print(f"  Analyzing {trial_dir.name}...")
            analysis = analyze_transcript(str(transcript))
            analyses.append(analysis)

    if not analyses:
        print(f"[error] No transcripts found in {results_iter_dir} for condition={condition}", file=sys.stderr)
        sys.exit(1)

    print(f"[generate] Analyzed {len(analyses)} transcripts")

    # Load previous AGENTS.md for hill-climbing
    previous_md = None
    if args.previous_agents_md:
        previous_md = Path(args.previous_agents_md).read_text().strip()
        print(f"[generate] Hill-climbing from: {args.previous_agents_md} ({len(previous_md.split())} words)")

    # Build the generation prompt
    prompt = build_generation_prompt(str(workspace), analyses, previous_md, args.iteration)

    if args.dry_run:
        print("\n=== DRY RUN: Generation prompt ===\n")
        print(prompt)
        print(f"\n=== Would write to: {output_path} ===")
        return

    # Write prompt to temp file for claude -p
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    try:
        print(f"[generate] Calling claude -p (model={args.model})...")
        result = subprocess.run(
            [
                'claude', '-p',
                '--output-format', 'text',
                '--model', args.model,
                '--dangerously-skip-permissions',
                '--no-session-persistence',
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            print(f"[error] claude -p failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)

        agents_md = result.stdout.strip()

        # Strip any wrapping code fences if claude added them
        if agents_md.startswith('```'):
            lines = agents_md.split('\n')
            # Remove first and last fence lines
            if lines[0].startswith('```'):
                lines = lines[1:]
            if lines and lines[-1].startswith('```'):
                lines = lines[:-1]
            agents_md = '\n'.join(lines).strip()

        # Write output
        output_path.write_text(agents_md + '\n')
        word_count = len(agents_md.split())
        print(f"[generate] Wrote {output_path} ({word_count} words)")

        if previous_md:
            prev_words = len(previous_md.split())
            delta = word_count - prev_words
            direction = "smaller" if delta < 0 else "larger" if delta > 0 else "same size"
            print(f"[generate] Size change: {prev_words} → {word_count} words ({delta:+d}, {direction})")

    finally:
        os.unlink(prompt_file)


if __name__ == '__main__':
    main()
