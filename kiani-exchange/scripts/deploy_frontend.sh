#!/usr/bin/env bash
set -euo pipefail

# deploy_frontend.sh — Build both frontends and reload Nginx
# Usage: sudo bash deploy_frontend.sh
# Run from the repo root or adjust REPO_ROOT below.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"

echo "=== Frontend Deployment ==="
echo "Repo root: $REPO_ROOT"

# --- Mini App ---
echo ""
echo "--- Building mini-app ---"
cd "$FRONTEND_DIR/mini-app"
npm ci --ignore-scripts 2>/dev/null || npm install
npm run build
echo "mini-app built -> $FRONTEND_DIR/mini-app/dist"

# --- Admin Panel ---
echo ""
echo "--- Building admin-panel ---"
cd "$FRONTEND_DIR/admin-panel"
npm ci --ignore-scripts 2>/dev/null || npm install
npm run build
echo "admin-panel built -> $FRONTEND_DIR/admin-panel/dist"

# --- Install Nginx configs (if not already linked) ---
NGINX_AVAIL="/etc/nginx/sites-available"
NGINX_ENABLED="/etc/nginx/sites-enabled"

for conf in miniapp.peerexo.com.conf kianiapp.peerexo.com.conf; do
    src="$REPO_ROOT/deploy/nginx/$conf"
    if [ -f "$src" ]; then
        sudo cp "$src" "$NGINX_AVAIL/$conf"
        if [ ! -L "$NGINX_ENABLED/$conf" ]; then
            sudo ln -sf "$NGINX_AVAIL/$conf" "$NGINX_ENABLED/$conf"
        fi
        echo "Nginx config installed: $conf"
    fi
done

# --- Test & reload Nginx ---
echo ""
echo "--- Testing Nginx configuration ---"
sudo nginx -t

echo ""
echo "--- Reloading Nginx ---"
sudo systemctl reload nginx

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Verify with:"
echo "  curl -I https://miniapp.peerexo.com"
echo "  curl -I https://kianiapp.peerexo.com"
echo "  curl -s https://miniapp.peerexo.com/api/faqs | head"
echo "  curl -s https://kianiapp.peerexo.com/api/faqs | head"
