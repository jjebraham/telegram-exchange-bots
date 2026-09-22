#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
LOCK_FILE="${ALANCHANDE_SHADOW_TEST_LOCK_FILE:-/tmp/alanchande-shadow-test.lock}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "alanchande-shadow-post: missing $ENV_FILE" >&2
  exit 64
fi

if ! grep -qx 'ALANCHANDE_CHANNEL_ID=@alanchandetest' "$ENV_FILE"; then
  echo "alanchande-shadow-post: refusing to run because ALANCHANDE_CHANNEL_ID is not @alanchandetest" >&2
  exit 64
fi

post="${1:-}"
case "$post" in
  alanchande-usdt-exchanges|alanchande-iran-fx) ;;
  *)
    echo "alanchande-shadow-post: unsupported fast-board post: $post" >&2
    exit 64
    ;;
esac

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "alanchande-shadow-post: another shadow publisher is active; skipping $post" >&2
  exit 0
fi

cd "$SCRIPT_DIR"
export MARKET_SAFETY_MODE=shadow
export MARKET_HISTORY_DB=market_history_shadow.sqlite3

echo "alanchande-shadow-post: post=$post"
exec "$PYTHON_BIN" publish_channels.py --post "$post"
