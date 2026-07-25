#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi

export PORT="${PORT:-8090}"
export PYTHONUNBUFFERED=1
exec .venv/bin/python app.py
