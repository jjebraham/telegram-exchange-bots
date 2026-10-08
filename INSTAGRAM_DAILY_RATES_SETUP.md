# Daily Instagram rate banner

This job renders the light Vazirmatn rate card from the production Kiani rates and publishes it once per day at **11:10 Europe/Istanbul**. The server timer runs the job; it does not depend on a local computer staying online.

## Rate source

The banner uses the running backend's `GET /api/rates/current` response for raw `USDT_IRR` and `USDT_TRY` values. It then reads `pricing_settings.db` in read-only mode and applies the same six percentage adjustments and fallback percentages as the Telegram bot. If the API or database is unavailable, the job exits without posting.

Default server locations match the deployment paths documented in this repository:

- Checkout: `/home/kianirad2020/telegram_bot_repo`
- Rates API: `http://127.0.0.1:8000/api/rates/current`
- Shared percentage database: `/home/kianirad2020/send_changes/pricing_settings.db`

The rate endpoint, database path, and media paths can be overridden in `/etc/kiani-instagram-rates.env`.

## Image and Instagram mode

- `INSTAGRAM_PUBLISH_MODE=story` creates the requested **1080×1920 (9:16)** banner.
- `INSTAGRAM_PUBLISH_MODE=feed` creates a **1080×1350 (4:5)** image for the profile feed.

Instagram's publishing API only supports Story publishing for Business accounts. Both Business and Creator professional accounts can publish feed content. The account currently being checked as “Professional” may be either subtype; confirm it is Business before leaving the job in Story mode. Set `INSTAGRAM_PUBLISH_MODE=feed` for a Creator account. See [Meta's Instagram API documentation](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api).

Meta fetches media from a public HTTPS URL. The generated JPEGs are written to `/var/lib/kiani-instagram-rates/public`, and the included Nginx snippet serves them at `/instagram-rates/`. The Meta API token is sent only in an Authorization header and is never written to the banner URL or logs.

## First server setup

After this change is merged, log in to the server as `kianirad2020` and run:

```bash
cd /home/kianirad2020/telegram_bot_repo
git pull --ff-only origin main
bash deploy/instagram-rates/install_server.sh
```

The installer pulls the latest `main`, creates a separate Python environment, installs the renderer and Vazirmatn font, and adds the systemd timer/service and Nginx location snippet. It preserves an existing `/etc/kiani-instagram-rates.env` file and leaves the timer disabled until the Meta and Nginx settings are ready.

Edit `/etc/kiani-instagram-rates.env` and fill in:

- `INSTAGRAM_GRAPH_API_VERSION` — the Graph API version enabled for the Meta app.
- `INSTAGRAM_USER_ID` — the Instagram professional account ID.
- `INSTAGRAM_ACCESS_TOKEN` — a long-lived token with publishing permission.
- `INSTAGRAM_PUBLIC_MEDIA_BASE_URL` — the public HTTPS URL served by this Nginx host.
- `INSTAGRAM_PUBLISH_MODE` — `story` or `feed`.

The included Meta Facebook Login setup expects an Instagram professional account connected to a Facebook Page, and the app permissions `pages_show_list`, `instagram_basic`, `instagram_content_publish`, and `pages_read_engagement`. `INSTAGRAM_GRAPH_BASE_URL` can be set to `https://graph.instagram.com` when using Meta's Instagram Login flow and its corresponding token/permissions.

In the existing HTTPS Nginx server block for `miniapp.kiani.exchange`, add:

```nginx
include /etc/nginx/snippets/kiani-instagram-rates.conf;
```

Then validate/reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

After the preview looks right and the Nginx image URL is public, start the schedule:

```bash
sudo systemctl enable --now kiani-instagram-rates.timer
```

## Preview and operations

Preview without publishing:

```bash
/home/kianirad2020/telegram_bot_repo/.venv-instagram-rates/bin/python \
  /home/kianirad2020/telegram_bot_repo/instagram_daily_rates.py --dry-run
```

The preview prints the rates and output path. Open the JPEG from `/var/lib/kiani-instagram-rates/public` to review it.

Check the schedule and recent logs:

```bash
systemctl list-timers kiani-instagram-rates.timer
sudo journalctl -u kiani-instagram-rates.service -n 100 --no-pager
```

After a future code update, pull it on the server and restart the timer:

```bash
cd /home/kianirad2020/telegram_bot_repo
git pull --ff-only origin main
sudo systemctl restart kiani-instagram-rates.timer
```

The publisher stores the last successful Istanbul posting date and skips duplicate runs for that day. `--force` is available for an intentional same-day repost. The normal systemd service never uses it.

