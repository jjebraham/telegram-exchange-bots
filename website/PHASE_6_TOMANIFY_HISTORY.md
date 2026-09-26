# Phase 6 — free Tomanify chart history

The chart can now read Tomanify's public Iran free-market snapshots from the
website's existing SQLite database. USD, EUR, AED, TRY, and CNY each use their
own Tomanify series. These observations remain separate from Telegram-verified
series; the homepage board continues to use verified publisher quotes.

## Source and timestamp meaning

Tomanify publishes a free JSON snapshot a few times per day and asks public
users to credit “Tomanify” with a link to its WordPress plugin. Its README asks
users to contact its maintainer before commercial use. This deployment assumes
the site's noncommercial use, as confirmed by the site owner.

The live feed includes only a calendar date, not a precise market-observation
time. The importer therefore keeps that date in `source_reported_date` and uses
the GitHub file-history commit timestamp as `collected_at`, explicitly as an
archive timestamp. The chart note explains this to visitors. These points show
published snapshots only; no missing values or intermediate prices are
invented. The source data is provided as-is.

## Import behavior

`api.import_tomanify_history` reads the public GitHub commit history for
`data.json`, fetches immutable versions of that file, validates each supported
rate, and writes append-only snapshots to `/var/lib/alanchande/market.sqlite3`.
It uses no API key and has a dry-run default. `--apply` writes records. The
initial history scan is capped at 1,500 file commits and the importer stops at
the newest commit already present in SQLite. Later timer runs only collect new
commits. Fetches use a small bounded worker pool.

The new systemd timer runs the importer every four hours. It uses the same
SQLite database as the public API, and its service account can write only to
that database directory. It does not access Telegram/X publisher services.

## Local checks

From `website/`:

```bash
python3 -m unittest discover -s tests -v
node --test tests/model.test.mjs
```

## Safe rollout

Deploy the website API code and static files using the existing Phase 5 rollout
process, while retaining a backup of the current `dist/` directory. Install the
new systemd unit and timer, then run a dry-run before enabling writes:

```bash
cd /home/kianirad2020/alanchande-site/website
ALANCHANDE_DB_PATH=/var/lib/alanchande/market.sqlite3 \
  .venv/bin/python -m api.import_tomanify_history
```

After confirming the summary, back up the SQLite database and import the
history:

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"
ALANCHANDE_DB_BACKUP="/var/lib/alanchande/market.sqlite3.bak-${STAMP}" \
  .venv/bin/python - <<'PY'
import os
import sqlite3

source = sqlite3.connect("/var/lib/alanchande/market.sqlite3")
backup = sqlite3.connect(os.environ["ALANCHANDE_DB_BACKUP"])
try:
    source.backup(backup)
finally:
    backup.close()
    source.close()
PY
ALANCHANDE_DB_PATH=/var/lib/alanchande/market.sqlite3 \
  .venv/bin/python -m api.import_tomanify_history --apply
```

Install and start the timer, then restart only the website API because its
read-only query now includes `source_published` observations:

```bash
sudo install -m 0644 deploy/systemd/alanchande-tomanify-import.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/alanchande-tomanify-import.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now alanchande-tomanify-import.timer
sudo systemctl restart alanchande-api.service
```

Verify `/healthz`, `/api/v1/quotes`, and `/api/v1/history` for
`fx:usd:iran-open:toman:tomanify:v1`, plus the attribution and chart timestamp
note on the public page. A rollback restores the prior static assets and API
code and disables the new timer; imported rows can remain in the append-only
database without affecting the old code.
