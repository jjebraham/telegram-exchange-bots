#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
LOCK_FILE="${ALANCHANDE_RAPID_TEST_LOCK_FILE:-/tmp/alanchande-shadow-test.lock}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "channel-split-rapid-test: missing $ENV_FILE" >&2
  exit 64
fi

if ! grep -qx 'ALANCHANDE_CHANNEL_ID=@alanchandetest' "$ENV_FILE"; then
  echo "channel-split-rapid-test: refusing to run because ALANCHANDE_CHANNEL_ID is not @alanchandetest" >&2
  exit 64
fi

if ! grep -qx 'KIANI_CHANNEL_ID=@kianiexchangetest' "$ENV_FILE"; then
  echo "channel-split-rapid-test: refusing to run because KIANI_CHANNEL_ID is not @kianiexchangetest" >&2
  exit 64
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "channel-split-rapid-test: another test publisher is active; skipping" >&2
  exit 0
fi

minute="$(TZ=Europe/Istanbul date +%M)"
slot=$(( (10#$minute / 3) % 10 ))

case "$slot" in
  0) post="bank-comparison" ;;
  1) post="kiani-try" ;;
  2) post="alanchande-iran-fx" ;;
  3) post="kiani-rates" ;;
  4) post="alanchande-turkey-gold" ;;
  5) post="kiani-examples" ;;
  6) post="alanchande-usdt-exchanges" ;;
  7) post="kiani-examples-reverse" ;;
  8) post="alanchande-fx-pulse" ;;
  9) post="alanchande-iran-gold" ;;
  *)
    echo "channel-split-rapid-test: unexpected slot $slot" >&2
    exit 70
    ;;
esac

cd "$SCRIPT_DIR"
export MARKET_SAFETY_MODE=shadow
export MARKET_HISTORY_DB=market_history_shadow.sqlite3

echo "channel-split-rapid-test: Istanbul minute=$minute slot=$slot post=$post"
exec "$PYTHON_BIN" publish_channels.py --post "$post"
