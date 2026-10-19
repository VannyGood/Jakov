#!/usr/bin/env bash
# Run Jakov locally: creates the venv on first use, applies migrations, starts polling.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -e ".[dev]"
fi
if [ ! -f .env ]; then
  echo "No .env found. Copy .env.example to .env and fill in BOT_TOKEN and ADMIN_IDS." >&2
  exit 1
fi
exec .venv/bin/python -m jakov
