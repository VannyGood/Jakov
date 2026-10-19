#!/usr/bin/env bash
# Stop a Jakov started with scripts/run.sh (graceful: finishes the current update first).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f var/jakov.pid ] || ! kill -0 "$(cat var/jakov.pid)" 2>/dev/null; then
  echo "Jakov is not running."
  rm -f var/jakov.pid
  exit 0
fi
pid="$(cat var/jakov.pid)"
kill -INT "$pid"
for _ in $(seq 1 20); do
  kill -0 "$pid" 2>/dev/null || { rm -f var/jakov.pid; echo "Jakov stopped."; exit 0; }
  sleep 0.5
done
echo "Jakov didn't stop in 10 s; sending SIGTERM." >&2
kill -TERM "$pid"
rm -f var/jakov.pid
