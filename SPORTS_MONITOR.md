# Turkish sports discount monitor

An isolated Python 3.11+ scanner and Persian Telegram publisher. It only selects
running shoes: the title must identify a shoe, plus a running category or a
recognized running-shoe model. Running apparel, basketball/football shoes, and
lifestyle sneakers are excluded. Unknown models fail closed and are skipped.
Existing exchange bots and their publishing workflows are unchanged.

## Validation status and limits

The latest user-provided server scan (2026-09-27) parsed direct product data from
Barçın, Sporjinal, Sportive, and SuperStep. Sneaks Up, Koray Spor, Yalı Spor, and
adidas Türkiye returned HTTP 403. Complete eight-store production coverage is
not established. No attempt is made to bypass access controls.

### Source policy

The monitor reads only each retailer's own public pages with ordinary requests.
There is no third-party data source. The former Ayakapp fallback was removed:
the external research found no documented approved feed, and no written
permission has been provided for this project. Its terms (Section 5) require
prior written permission for copying/distribution, and it returned a Cloudflare
challenge to this server.

| Store | Status | Notes |
| --- | --- | --- |
| Barçın, Sporjinal, Sportive, SuperStep | enabled | Parsed on the 2026-09-27 server scan. |
| Sneaks Up | enabled, best-effort | robots.txt allows `/sezon-sonu-indirimi` and product pages. Server received 403. |
| adidas Türkiye | enabled, best-effort | robots.txt allows `/tr/outlet` and `/*.html` product pages. The adapter never calls the disallowed `/api/products/*/availability`. Server received 403; parser has no live fixture. |
| Koray Spor | enabled, best-effort | robots.txt allows the listing paths. Server received 403; no verified discounted running-shoe listing yet. |
| Yalı Spor | **disabled** | Membership agreement restricts automated loading/copying of site data. Never fetched until access is permitted. Re-enable in `stores.py` only after that. |

A 401/403 or a response with `cf-mitigated: challenge` marks the store
`blocked` in the scan report, including a challenge returned with HTTP 200. The
store is not retried in that scan; a block during listing, product fetching, or
finalist rechecking stops further requests to that store and excludes its
products from that scan's posts. No workaround is attempted (no proxies,
alternate identities, browser impersonation, challenge solving, private
endpoints, or third-party mirrors). Each store report has a
`status` of `ok`, `degraded`, `blocked`, or `disabled`. A deliberately disabled
store does not by itself make the scan degraded.

Only `retailer`-sourced observations from enabled stores can be published. Old
history rows from the removed fallback still load for deduplication but are
never formatted or posted. Prices and sizes are observations at scan time; a
six-hour cadence is a recheck interval, not a stock guarantee.

Full catalog coverage is bounded by `--max-pages` (100 per store) and
`--max-products` (5000 per store). Raise these after measuring server runtime.
Reaching either limit is reported as degraded, never silently reported as a
complete scan. Stores can change markup, use client-only pagination, or expose
stale data through their own caches. The monitor uses fresh requests, current
product detail stock, and finalist rechecks; availability at checkout is not
guaranteed. Scan reports identify failures and require operational attention.

The existing repository has scheduled X publishing and Python test workflows on
GitHub-hosted runners, but no established server deployment workflow or durable
runner database. A new CI workflow only runs tests. Publishing is scheduled on
the server with the included user systemd timer; SQLite is never kept in an
evictable Actions cache. This change does not automatically deploy or post.

## Deal and repost rules

- Require valid TRY prices, a product identity and explicitly available sizes.
- First require a running shoe as described above. Accept discounts >=35%.
  Accept 25–34% only if the current price is >=10% below
  the prior 30-day low, with at least three previous observations. Moderate
  discounts therefore need a warm-up period; no arbitrary brand bonuses.
- Rank by discount, absolute savings, then size availability; select up to ten
  eligible deals per scan. Re-fetch finalists before posting; skip any changed
  finalist until the next scan, and never send data older than five minutes.
- Repost for a >=5% AND >=100 TRY drop against the **last successfully posted**
  price. For restocks or size additions, require a 24-hour cooldown. Size additions
  mean >=2 new sizes, or any new size when the prior post offered <=1 size.
  Size removal alone does not cause a repost.
- Empty verified stock is a real observation. Missing/blocked pages never mean
  out of stock. Known products are revisited for restocks.
- Destination-specific deduplication: posting to the test channel doesn't consume
  a future production channel's first post.
- Group 5–10 products (default target seven), splitting below Telegram's length
  limit. A small scan or length overflow can produce a shorter final message.
  Sizes appear immediately below each model, direct product links below prices,
  and >=50% is highlighted. No bot promotion is included.

## Pull and install on the existing Linux server

These instructions use a separate checkout under your home directory, as expected
by the user service. If that directory already holds this repository, use the
existing-checkout commands instead of cloning. Do not overwrite local changes.

```bash
git clone --branch codex/turkish-sports-monitor \
  https://github.com/jjebraham/telegram-exchange-bots.git "$HOME/telegram-exchange-bots"
cd "$HOME/telegram-exchange-bots"
python3 -m venv .venv-sports
.venv-sports/bin/python -m pip install -r requirements-sports.txt
.venv-sports/bin/python -m unittest discover -s tests/sports -v
```

Existing checkout / later update:

```bash
cd "$HOME/telegram-exchange-bots"
git fetch origin
git switch codex/turkish-sports-monitor
git pull --ff-only origin codex/turkish-sports-monitor
.venv-sports/bin/python -m pip install -r requirements-sports.txt
```

Store credentials **outside Git**. The command below reuses the bot token already
exported in your server shell; it does not print it or put it in shell history.
If it is not exported, enter it with `read -rs -p 'Bot token: ' RUN_DISCOUNT_BOT_TOKEN`
then `export RUN_DISCOUNT_BOT_TOKEN`. Never paste it into chat or a tracked file.

```bash
install -d -m 700 "$HOME/.config/run-discount" "$HOME/.local/state/run-discount"
export RUN_DISCOUNT_CHAT_ID='@alanchandetest'
.venv-sports/bin/python - <<'PY'
import os
from pathlib import Path
token = os.environ['RUN_DISCOUNT_BOT_TOKEN']
if not token or any(c in token for c in '\r\n'):
    raise SystemExit('Missing or malformed token')
path = Path.home() / '.config/run-discount/monitor.env'
path.write_text('RUN_DISCOUNT_BOT_TOKEN=' + token + '\nRUN_DISCOUNT_CHAT_ID=@alanchandetest\n')
path.chmod(0o600)
PY
```

Read-only preview (small scan; exit 2 is expected when limited or a store is blocked):

```bash
.venv-sports/bin/python -m sports_monitor --max-pages 2 --max-products 10
```

Run one real scan/post using the dedicated persistent database:

```bash
set -a
. "$HOME/.config/run-discount/monitor.env"
set +a
.venv-sports/bin/python -m sports_monitor --publish \
  --db "$HOME/.local/state/run-discount/history.sqlite3" \
  --report "$HOME/.local/state/run-discount/latest-scan.json"
```

Successful deliveries record Telegram `message_id`, destination and outbox ID in
the report. Verify them in the channel. No message is sent when no eligible deal
is found. A degraded scan may still post verified deals from healthy stores.

## Six-hour schedule

```bash
install -d "$HOME/.config/systemd/user"
install -m 644 deploy/sports-monitor.service deploy/sports-monitor.timer \
  "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now sports-monitor.timer
sudo loginctl enable-linger "$USER"
systemctl --user list-timers sports-monitor.timer
journalctl --user -u sports-monitor.service -n 50 --no-pager
```

The timer runs at 00:17, 06:17, 12:17, 18:17 UTC (03:17, 09:17, 15:17, 21:17
Türkiye time), with up to two minutes of jitter. `Persistent=true` catches a
missed run after downtime. The service has a five-hour timeout; overlapping
processes using the same DB are prevented by an OS lock. Enable linger so the
user service runs while logged out. If the server does not support user systemd,
use the following cron entry instead (do not run both schedulers):

```cron
17 */6 * * * cd "$HOME/telegram-exchange-bots" && set -a && . "$HOME/.config/run-discount/monitor.env" && set +a && .venv-sports/bin/python -m sports_monitor --publish --db "$HOME/.local/state/run-discount/history.sqlite3" --report "$HOME/.local/state/run-discount/latest-scan.json" >> "$HOME/.local/state/run-discount/cron.log" 2>&1
```

Cron uses the server's timezone. Review reports/logs and configure your existing
server alerting to flag exit 1/2. Exit 0: healthy completed scan; 1: configuration
or runtime failure; 2: degraded/limited coverage or delivery uncertainty. Don't
ignore a repeatedly empty store. CLI `--stores` accepts `barcin sporjinal sneaks
superstep sportive koray yali adidas` for focused diagnostics; a disabled store
is reported as disabled and not fetched.

## Delivery recovery and backups

SQLite uses WAL and full synchronous writes. The outbox is reserved **before**
the HTTP POST. Confirmed Telegram success and per-product posted baselines update
in one database transaction. Definitive rejection can retry on the next scan.
Timeout, lost response, or process death after reservation is ambiguous: those
products are held from further posts until the operator checks the channel.
Telegram does not support idempotency keys; automatically retrying such POSTs
cannot guarantee duplicate prevention.

After checking the channel, reconcile using exactly one of:

```bash
# The batch was sent: replace 12 and 345 with the actual outbox/message IDs.
.venv-sports/bin/python -m sports_monitor --db "$HOME/.local/state/run-discount/history.sqlite3" --resolve-batch 12 --message-id 345
# The batch definitely was not sent: permit a fresh scan/retry.
.venv-sports/bin/python -m sports_monitor --db "$HOME/.local/state/run-discount/history.sqlite3" --resolve-batch 12 --confirmed-not-sent
```

To inspect unresolved IDs:

```bash
sqlite3 "$HOME/.local/state/run-discount/history.sqlite3" \
  "SELECT id,destination,created_at,status FROM outbox WHERE status IN ('sending','unknown');"
```

Back up the DB with SQLite's online backup command (not by copying only the main
file while WAL is active):

```bash
sqlite3 "$HOME/.local/state/run-discount/history.sqlite3" \
  ".backup '$HOME/.local/state/run-discount/history.backup.sqlite3'"
```

History is retained; monitor disk usage and secure backups. Losing the database
loses duplicate-prevention history. Keep tokens out of database backups/logs.
To stop only this monitor: `systemctl --user disable --now sports-monitor.timer`.
