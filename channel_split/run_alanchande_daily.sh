#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LOCK_FILE="${ALANCHANDE_DAILY_LOCK_FILE:-/tmp/alanchande-daily.lock}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "alanchande-daily: another run is already active; skipping" >&2
  exit 0
fi

cd "$SCRIPT_DIR"
exec "$PYTHON_BIN" publish_channels.py --post alanchande-daily
