# Deployment Guide

## Architecture

| Component | URL / Port | How it runs |
|-----------|-----------|-------------|
| Backend API | `http://127.0.0.1:8000` | Supervisor (`kiani_api`) |
| Mini App | `https://miniapp.peerexo.com` | Nginx serves `mini-app/dist/` |
| Admin Panel | `https://kianiapp.peerexo.com` | Nginx serves `admin-panel/dist/` |

Both frontend subdomains proxy `/api/*` to the FastAPI backend via Nginx.
SSL is handled by certbot (Let's Encrypt).

## Prerequisites

- Node.js 20+
- Nginx
- certbot certificates for both subdomains
- Supervisor (for the backend API only)

## Quick Deploy

Run the deploy script from the repo root:

```bash
cd /home/kianirad2020/telegram_bot_repo/kiani-exchange
sudo bash scripts/deploy_frontend.sh
```

This will:
1. `npm install` + `npm run build` for both frontends
2. Copy Nginx configs to `/etc/nginx/sites-available/`
3. Symlink to `/etc/nginx/sites-enabled/`
4. Test and reload Nginx

## Manual Steps

### 1. Build Frontends

```bash
# Mini App
cd kiani-exchange/frontend/mini-app
npm install
npm run build    # Output: dist/

# Admin Panel
cd kiani-exchange/frontend/admin-panel
npm install
npm run build    # Output: dist/
```

### 2. Install Nginx Configs

```bash
sudo cp kiani-exchange/deploy/nginx/miniapp.peerexo.com.conf /etc/nginx/sites-available/
sudo cp kiani-exchange/deploy/nginx/kianiapp.peerexo.com.conf /etc/nginx/sites-available/

sudo ln -sf /etc/nginx/sites-available/miniapp.peerexo.com.conf /etc/nginx/sites-enabled/
sudo ln -sf /etc/nginx/sites-available/kianiapp.peerexo.com.conf /etc/nginx/sites-enabled/

sudo nginx -t && sudo systemctl reload nginx
```

### 3. Verify

```bash
curl -I https://miniapp.peerexo.com
curl -I https://kianiapp.peerexo.com
curl -s https://miniapp.peerexo.com/api/faqs | head
curl -s https://kianiapp.peerexo.com/api/faqs | head
```

## Supervisor

Only the backend API runs under Supervisor. Frontend Supervisor processes
(`kiani_miniapp`, `kiani_adminpanel`) are **no longer needed** — stop and remove
them if they are still running:

```bash
sudo supervisorctl stop kiani_miniapp kiani_adminpanel 2>/dev/null
sudo rm -f /etc/supervisor/conf.d/kiani_miniapp.conf
sudo rm -f /etc/supervisor/conf.d/kiani_adminpanel.conf
sudo supervisorctl reread && sudo supervisorctl update
```

## Troubleshooting

**Nginx 502 on /api routes:**
- Check that the FastAPI backend is running: `sudo supervisorctl status kiani_api`
- Verify port 8000 is listening: `ss -tlnp | grep 8000`

**Stale frontend after deploy:**
- Hard refresh (Ctrl+Shift+R) — `index.html` is served with `no-cache`
- Hashed asset filenames ensure browsers fetch new JS/CSS automatically

**Build errors:**
```bash
rm -rf node_modules
npm install
npm run build
```
