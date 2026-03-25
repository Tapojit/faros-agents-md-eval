#!/usr/bin/env bash
# run_graders.sh - Run deterministic graders, write grading.json
#
# Usage: bash scripts/run_graders.sh <worktree_path> [results_dir]
#
# Arguments:
#   worktree_path — where the build happened (graders check for binaries here)
#   results_dir   — where to write grading.json (defaults to worktree_path for backward compat)
#
# Graders run inside the worktree because they need access to the built binaries.
# But grading.json is written to the results directory so it persists after
# worktree teardown.
#
# Exit code: 0 if all pass, 1 if any fail

# Note: -e intentionally omitted. Grader failures (non-zero exit) are expected
# and handled by the run_grader function; -e would abort the script on first failure.
set -uo pipefail

WT_DIR="${1:?Usage: run_graders.sh <worktree_path> [results_dir]}"
RESULTS_DIR="${2:-$WT_DIR}"

mkdir -p "$RESULTS_DIR"

RESULTS=()
ALL_PASSED=true
PASSED_COUNT=0
TOTAL_COUNT=0

# CPython's Makefile produces "python.exe" on macOS (despite not being Windows —
# it's a quirk of the build system where the .exe suffix distinguishes the actual
# binary from the "python" wrapper script). On Linux it's just "python".
# Auto-detect which one exists so graders work on both platforms.
if [ -f "${WT_DIR}/python.exe" ] && [ ! -f "${WT_DIR}/python" ]; then
    PYTHON_BIN="python.exe"
elif [ -f "${WT_DIR}/python" ]; then
    PYTHON_BIN="python"
else
    PYTHON_BIN="python"  # fallback — will fail the binary-exists grader cleanly
fi

run_grader() {
    local id="$1"
    local type="$2"
    local check="$3"
    local passed=false
    local detail=""

    TOTAL_COUNT=$((TOTAL_COUNT + 1))

    case "$type" in
        file_exists)
            if [ -f "${WT_DIR}/${check}" ]; then
                passed=true
                detail="Found: ${check}"
            else
                detail="Missing: ${check}"
            fi
            ;;
        exit_code)
            local output
            output=$(cd "$WT_DIR" && eval "$check" 2>&1) && passed=true || passed=false
            detail=$(echo "$output" | tail -5 | tr '\n' ' ' | cut -c1-200)
            ;;
    esac

    local passed_str="false"
    if [ "$passed" = true ]; then
        passed_str="true"
        PASSED_COUNT=$((PASSED_COUNT + 1))
    else
        ALL_PASSED=false
    fi

    RESULTS+=("${id}$(printf '\t')${type}$(printf '\t')${passed_str}$(printf '\t')$(echo "$detail" | tr '\n' ' ')")
}

# CPython build graders
run_grader "binary-exists" "file_exists" "$PYTHON_BIN"
run_grader "functional-test" "exit_code" "./$PYTHON_BIN -c \"import ssl; import ctypes; import sqlite3; print('BUILD OK')\""
run_grader "test-suite-smoke" "exit_code" "./$PYTHON_BIN -m test test_math test_string test_list -v --timeout 60"

# Write grading.json to results dir
ALL_PASSED_STR="false"
[ "$ALL_PASSED" = true ] && ALL_PASSED_STR="true"

printf '%s\n' "${RESULTS[@]}" | python3 -c "
import json, sys
graders = []
for line in sys.stdin:
    parts = line.strip().split('\t', 3)
    if len(parts) >= 3:
        graders.append({
            'id': parts[0],
            'type': parts[1],
            'passed': parts[2] == 'true',
            'detail': parts[3] if len(parts) > 3 else ''
        })
json.dump({
    'graders': graders,
    'summary': {
        'passed': $PASSED_COUNT,
        'failed': $((TOTAL_COUNT - PASSED_COUNT)),
        'total': $TOTAL_COUNT,
        'all_passed': '$ALL_PASSED_STR' == 'true'
    }
}, open(sys.argv[1], 'w'), indent=2)
" "${RESULTS_DIR}/grading.json"

echo "[grading] ${WT_DIR}: ${PASSED_COUNT}/${TOTAL_COUNT} passed (results → ${RESULTS_DIR}/grading.json)"

[ "$ALL_PASSED" = true ] && exit 0 || exit 1
