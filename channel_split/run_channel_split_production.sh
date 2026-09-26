#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
LOCK_FILE="${CHANNEL_SPLIT_PROD_LOCK_FILE:-/tmp/channel-split-production.lock}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "channel-split-production: missing $ENV_FILE" >&2
  exit 64
fi

if ! grep -qx 'ALANCHANDE_CHANNEL_ID=@alanchande_com' "$ENV_FILE"; then
  echo "channel-split-production: ALANCHANDE_CHANNEL_ID is not @alanchande_com" >&2
  exit 64
fi

if ! grep -qx 'KIANI_CHANNEL_ID=@ExchangeKiani' "$ENV_FILE"; then
  echo "channel-split-production: KIANI_CHANNEL_ID is not @ExchangeKiani" >&2
  exit 64
fi

post="${1:-}"
case "$post" in
  bank-comparison|alanchande-daily-digest|alanchande-iran-gold|alanchande-fx-pulse|alanchande-turkey-gold|alanchande-iran-fx|alanchande-usdt-exchanges|kiani-examples|kiani-examples-reverse|kiani-try|kiani-rates) ;;
  *)
    echo "channel-split-production: unsupported post: $post" >&2
    exit 64
    ;;
esac

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "channel-split-production: another publisher is active; skipping $post" >&2
  exit 0
fi

cd "$SCRIPT_DIR"
export MARKET_SAFETY_MODE=enforce
export MARKET_HISTORY_DB=market_history_production.sqlite3

echo "channel-split-production: post=$post"
exec "$PYTHON_BIN" publish_channels.py --post "$post"
