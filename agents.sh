#!/usr/bin/env bash
# ⚡ AI Agents 5-Hour Window Tracker & Dashboard runner for Linux / macOS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if command -v uv >/dev/null 2>&1; then
    exec uv run --project "$SCRIPT_DIR" agents "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/agents.py" "$@"
else
    echo "Error: Neither 'uv' nor 'python3' was found in PATH." >&2
    echo "Please install uv (https://astral.sh/uv) or Python 3.11+." >&2
    exit 1
fi
