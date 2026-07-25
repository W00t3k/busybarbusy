#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "Creating Python virtual environment..."
  python3 -m venv .venv
fi

export PYTHONUNBUFFERED=1
export PORT="${PORT:-8090}"

echo "Starting Busy RSS at http://localhost:${PORT}"
exec .venv/bin/python app.py
