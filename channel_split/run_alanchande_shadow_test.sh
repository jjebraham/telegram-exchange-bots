#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
LOCK_FILE="${ALANCHANDE_SHADOW_TEST_LOCK_FILE:-/tmp/alanchande-shadow-test.lock}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "alanchande-shadow-test: missing $ENV_FILE" >&2
  exit 64
fi

# Hard fail-closed guard: this scheduler is test-only. If the destination is
# ever changed to production, this launcher must stop instead of following it.
if ! grep -qx 'ALANCHANDE_CHANNEL_ID=@alanchandetest' "$ENV_FILE"; then
  echo "alanchande-shadow-test: refusing to run because ALANCHANDE_CHANNEL_ID is not @alanchandetest" >&2
  exit 64
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "alanchande-shadow-test: another run is already active; skipping" >&2
  exit 0
fi

hour="$(TZ=Europe/Istanbul date +%H)"
case "$hour" in
  00) post="bank-comparison" ;;
  04) post="alanchande-iran-fx" ;;
  08) post="alanchande-turkey-gold" ;;
  12) post="alanchande-usdt-exchanges" ;;
  16) post="alanchande-fx-pulse" ;;
  20) post="alanchande-iran-gold" ;;
  *)
    echo "alanchande-shadow-test: hour $hour is not a configured 4-hour slot; skipping" >&2
    exit 0
    ;;
esac

cd "$SCRIPT_DIR"
export MARKET_SAFETY_MODE=shadow
export MARKET_HISTORY_DB=market_history_shadow.sqlite3

echo "alanchande-shadow-test: Istanbul hour=$hour post=$post"
exec "$PYTHON_BIN" publish_channels.py --post "$post"
