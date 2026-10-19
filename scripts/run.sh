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
mkdir -p var
if [ -f var/jakov.pid ] && kill -0 "$(cat var/jakov.pid)" 2>/dev/null; then
  echo "Jakov is already running (pid $(cat var/jakov.pid)). Stop it with ./scripts/stop.sh" >&2
  exit 1
fi
echo $$ > var/jakov.pid
# exec keeps the same PID, so var/jakov.pid points at the bot itself.
exec .venv/bin/python -m jakov
