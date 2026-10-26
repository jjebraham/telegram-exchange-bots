#!/usr/bin/env bash
set -euo pipefail
stage="$1"
if [[ "$stage" != "preview" && "$stage" != "activate" ]]; then exit 2; fi
test -n "$ALANCHANDE_DEPLOY_SSH_KEY"
test -n "$ALANCHANDE_DEPLOY_KNOWN_HOSTS"
umask 077
mkdir -p "$HOME/.ssh"
printf '%s\n' "$ALANCHANDE_DEPLOY_SSH_KEY" > "$HOME/.ssh/alanchande_deploy"
printf '%s\n' "$ALANCHANDE_DEPLOY_KNOWN_HOSTS" > "$HOME/.ssh/known_hosts"
unset ALANCHANDE_DEPLOY_SSH_KEY ALANCHANDE_DEPLOY_KNOWN_HOSTS
remote="kianirad2020@34.19.54.235"
ssh -i "$HOME/.ssh/alanchande_deploy" -o StrictHostKeyChecking=yes "$remote" \
  'mkdir -p "$HOME/alanchande-image-stage"'
scp -i "$HOME/.ssh/alanchande_deploy" -o StrictHostKeyChecking=yes \
  channel_split/market_images.py channel_split/market_report_templates.py channel_split/deploy_market_images.py channel_split/test_market_images.py \
  "$remote":alanchande-image-stage/
scp -r -i "$HOME/.ssh/alanchande_deploy" -o StrictHostKeyChecking=yes \
  channel_split/market_image_assets "$remote":alanchande-image-stage/
ssh -i "$HOME/.ssh/alanchande_deploy" -o StrictHostKeyChecking=yes "$remote" bash -se <<'REMOTE'
set -euo pipefail
cd "$HOME"
python3 -m py_compile alanchande-image-stage/market_images.py alanchande-image-stage/deploy_market_images.py
image_python="$HOME/.venvs/alanchande-images/bin/python"
test -x "$image_python" || { echo "Missing image-renderer Python venv" >&2; exit 1; }
"$image_python" -c 'import playwright.sync_api'
test -x /usr/bin/chromium || { echo "Missing /usr/bin/chromium" >&2; exit 1; }
/usr/bin/python3 alanchande-image-stage/deploy_market_images.py --upgrade-renderer --upgrade-integration
/usr/bin/python3 alanchande-image-stage/deploy_market_images.py --upgrade-renderer --upgrade-integration --apply
cd "$HOME/telegram_bot_repo/channel_split"
mkdir -p "$HOME/alanchande-image-previews"
export ALANCHANDE_IMAGE_PREVIEW_DIR="$HOME/alanchande-image-previews"
export MARKET_SAFETY_MODE=enforce
export MARKET_HISTORY_DB=market_history_production.sqlite3
for post in alanchande-usdt-exchanges alanchande-iran-fx alanchande-iran-gold alanchande-turkey-gold alanchande-fx-pulse; do
  key="${post#alanchande-}"
  key="${key%-exchanges}"
  /usr/bin/python3 publish_channels.py --post "$post" --dry-run >"$HOME/alanchande-image-previews/$key-publisher.txt"
done
for key in usdt iran-fx iran-gold turkey-gold fx-pulse; do
  test -s "$HOME/alanchande-image-previews/$key.png"
done
/usr/bin/python3 - <<'PY'
import os
import re
from pathlib import Path
from publish_channels import _load_local_env
from market_images import TITLES, telegram_send_photo
_load_local_env()
token = os.environ.get("ALANCHANDE_TELEGRAM_BOT_TOKEN")
if not token:
    raise RuntimeError("Missing token in protected server environment")
for key in ("usdt", "iran-fx", "iran-gold", "turkey-gold", "fx-pulse"):
    path = Path.home() / "alanchande-image-previews" / (key + ".png")
    snapshot = path.with_name(key + '-publisher.txt').read_text(encoding='utf-8')
    if not re.search(rf'(?m)^SAFETY {re.escape(key)}: VERIFIED\b', snapshot):
        raise RuntimeError('Live verification missing for ' + key)
    marker = '===== ALANCHANDE_CHANNEL_ID (bot: ALANCHANDE_TELEGRAM_BOT_TOKEN) =====\n'
    if snapshot.count(marker) != 1:
        raise RuntimeError('Ambiguous verified bulletin for ' + key)
    details = snapshot.split(marker, 1)[1].strip() if key == 'iran-fx' else None
    result = telegram_send_photo(token, "@alanchandetest", path, "🧪 TEST — " + TITLES[key], details_text=details)
    print("Test channel", key, "message_id", result["result"]["message_id"])
    if 'details_result' in result:
        print('Full details message_id', result['details_result']['message_id'])
PY
REMOTE
if [[ "$stage" == "activate" ]]; then
ssh -i "$HOME/.ssh/alanchande_deploy" -o StrictHostKeyChecking=yes "$remote" bash -se <<'REMOTE'
set -euo pipefail
/usr/bin/python3 - <<'PY'
from pathlib import Path
from datetime import datetime
import os
p=Path.home()/"telegram_bot_repo/channel_split/.env"
original=p.read_text(encoding="utf-8")
lines=[line for line in original.splitlines() if not line.startswith("ALANCHANDE_POST_FORMAT=")]
lines.append("ALANCHANDE_POST_FORMAT=image")
backup=p.with_name(".env.before-image-"+datetime.now().strftime("%Y%m%d-%H%M%S"))
backup.write_text(original,encoding="utf-8")
backup.chmod(0o600)
tmp=p.with_name(".env.image-next")
tmp.write_text("\n".join(lines)+"\n",encoding="utf-8")
tmp.chmod(0o600)
os.replace(tmp,p)
print("Production image mode enabled for next scheduled posts")
PY
REMOTE
fi
