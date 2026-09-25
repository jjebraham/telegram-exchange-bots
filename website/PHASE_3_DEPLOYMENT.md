# Phase 3 — live data foundation

This release adds an isolated read-only API and a five-minute importer for history already recorded by the Telegram publishers. The importer opens the bot history database in SQLite read-only mode and only reads rows written after successful verified posts. It writes an independent AlanChande database. It does not call collectors or send Telegram/X posts. The existing dashboard remains clearly marked as sample data until Phase 4 connects every widget to the API.

The first feed covers verified Iran FX, Iran gold, Turkey bank FX, Turkey gold, and the verified USDT purchase side. The daily digest is left out because its mixed units and instrument identities need a separate mapping review. Imported chart points are actual verified post observations; the API does not interpolate missing candles.

## Install on the server

From `/home/kianirad2020/alanchande-site`:

```bash
git fetch origin
git switch --create codex/alanchande-phase3-live-data --track origin/codex/alanchande-phase3-live-data
cd website
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.txt
```

Find the production publisher history file and confirm the exact path before configuring it:

```bash
find /home/kianirad2020/telegram_bot_repo/channel_split -maxdepth 1 -type f -name '*production*.sqlite3' -print
```

Create the API environment file with that path:

```bash
mkdir -p /home/kianirad2020/.config
cat > /home/kianirad2020/.config/alanchande-api.env <<'EOF'
ALANCHANDE_DB_PATH=/var/lib/alanchande/market.sqlite3
ALANCHANDE_SOURCE_DB=/home/kianirad2020/telegram_bot_repo/channel_split/market_history_production.sqlite3
ALANCHANDE_STALE_AFTER_SECONDS=3600
EOF
chmod 600 /home/kianirad2020/.config/alanchande-api.env
```

If the `find` command showed a different production database path, edit `ALANCHANDE_SOURCE_DB` accordingly. Preview the initial import first; it reads the publisher database without changing it:

```bash
cd /home/kianirad2020/alanchande-site/website
.venv/bin/python -m api.import_verified_history
```

When the summary shows the expected snapshots and quotes, install and start the separate services:

```bash
sudo install -m 0644 deploy/systemd/alanchande-api.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/alanchande-import.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/alanchande-import.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now alanchande-api.service alanchande-import.timer
sudo systemctl start alanchande-import.service
```

## Connect Nginx

Add the contents of `deploy/nginx/alanchande-api-location.conf` inside both existing `alanchande.com` server blocks, including the HTTPS block. Keep the existing static `root` and other site configurations. Then run:

```bash
sudo nginx -t
sudo systemctl reload nginx
curl -s http://127.0.0.1:8012/healthz
curl -s -H 'Host: alanchande.com' http://127.0.0.1/api/v1/markets
```

The API starts with `waiting_for_verified_data` if the source database has not yet recorded a successful verified post. The importer runs every five minutes and brings in later verified rows. That state is expected during initial setup; it never substitutes sample prices for missing production data.

## HTTPS and Cloudflare

Cloudflare Error 526 means the origin certificate is missing or invalid. Keep the proxy enabled. Set Cloudflare SSL/TLS to **Full** temporarily, install a valid origin certificate with Certbot for `alanchande.com` and `www.alanchande.com`, then set SSL/TLS to **Full (strict)**:

```bash
sudo certbot --nginx -d alanchande.com -d www.alanchande.com
```

Certbot's HTTP validation needs public port 80 to reach this Nginx server. Afterward check `curl -I https://alanchande.com` and `curl -s https://alanchande.com/api/v1/markets`.

The ingestion endpoint accepts only a bearer token configured as `ALANCHANDE_INGEST_TOKEN`; it returns 503 until configured. The local read-only importer does not need that endpoint or a token. Do not put tokens in the repository or frontend.

