#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="/home/kianirad2020/telegram_bot_repo"
SERVICE_USER="kianirad2020"
SERVICE_GROUP="kianirad2020"
PUBLIC_GROUP="www-data"

if [[ "$(id -un)" != "$SERVICE_USER" ]]; then
  echo "Run this installer as ${SERVICE_USER}; it uses sudo only for system files." >&2
  exit 1
fi
if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "Git repository not found at $REPO_DIR. Set REPO_DIR to the server checkout." >&2
  exit 1
fi

git -C "$REPO_DIR" pull --ff-only origin main
sudo apt-get update
sudo apt-get install -y python3-venv fonts-vazirmatn

python3 -m venv "$REPO_DIR/.venv-instagram-rates"
"$REPO_DIR/.venv-instagram-rates/bin/python" -m pip install --upgrade pip
"$REPO_DIR/.venv-instagram-rates/bin/pip" install -r "$REPO_DIR/requirements-instagram-rates.txt"

sudo install -d -o "$SERVICE_USER" -g "$PUBLIC_GROUP" -m 2750 /var/lib/kiani-instagram-rates/public
sudo install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 "/home/$SERVICE_USER/.local/state/kiani-instagram-rates"
sudo install -d -o root -g root -m 0755 /etc/nginx/snippets

sudo install -o root -g root -m 0644 \
  "$REPO_DIR/deploy/instagram-rates/kiani-instagram-rates.service" \
  /etc/systemd/system/kiani-instagram-rates.service
sudo install -o root -g root -m 0644 \
  "$REPO_DIR/deploy/instagram-rates/kiani-instagram-rates.timer" \
  /etc/systemd/system/kiani-instagram-rates.timer
sudo install -o root -g root -m 0644 \
  "$REPO_DIR/deploy/instagram-rates/kiani-instagram-rates.nginx.conf" \
  /etc/nginx/snippets/kiani-instagram-rates.conf

if [[ ! -f /etc/kiani-instagram-rates.env ]]; then
  sudo install -o root -g "$SERVICE_GROUP" -m 0640 \
    "$REPO_DIR/deploy/instagram-rates/kiani-instagram-rates.env.example" \
    /etc/kiani-instagram-rates.env
  echo "Created /etc/kiani-instagram-rates.env with placeholders; set the Meta values before the timer runs." >&2
else
  echo "Kept existing /etc/kiani-instagram-rates.env unchanged." >&2
fi

sudo systemctl daemon-reload

cat <<'EOF'
Installer finished. Before enabling the timer:
  1. Set the Meta app values in /etc/kiani-instagram-rates.env.
  2. Include /etc/nginx/snippets/kiani-instagram-rates.conf inside the miniapp HTTPS server block and reload Nginx.
  3. Run a preview as the service user:
       sudo -u kianirad2020 /home/kianirad2020/telegram_bot_repo/.venv-instagram-rates/bin/python /home/kianirad2020/telegram_bot_repo/instagram_daily_rates.py --dry-run
  4. Enable the daily timer:
       sudo systemctl enable --now kiani-instagram-rates.timer
EOF

