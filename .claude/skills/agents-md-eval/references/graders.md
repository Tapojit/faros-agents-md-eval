# Graders

From the [Anthropic blog](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), three grader types. For this project we use code-based (deterministic) graders only.

## Code-Based Graders

Binary pass/fail on the outcome state. No ambiguity. Run via `scripts/run_graders.sh <worktree_path>`.

Current graders for CPython build task:

| ID | Type | Check | What It Proves |
|----|------|-------|---------------|
| `binary-exists` | `file_exists` | `python` in worktree root | Build produced something |
| `functional-test` | `exit_code` | `./python -c "import ssl; import ctypes; import sqlite3; print('BUILD OK')"` | Deps were correct (ssl, ffi, sqlite) |
| `test-suite-smoke` | `exit_code` | `./python -m test test_math test_string test_list -v --timeout 60` | Build is fully functional |

The grader script outputs JSON to stdout (one object per grader) and writes `grading.json` to the trial directory. Exit code 0 if all pass, 1 if any fail.

## Scoring

For build tasks: **binary**. All graders must pass for the trial to count as pass@1. No partial credit -- the binary either works or it doesn't.

For future tasks involving code quality or convention adherence, consider adding model-based (LLM-as-judge) graders. But use sparingly -- they add cost and nondeterminism. Always calibrate against human judgment first.

## Key Principle from the Blog

"Grade outcomes, not paths." Don't check that the agent ran specific commands in a specific order. Check that the result is correct. Agents find creative solutions that eval designers don't anticipate.
