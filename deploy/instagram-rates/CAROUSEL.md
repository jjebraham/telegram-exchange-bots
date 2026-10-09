# Daily Kiani Instagram carousel

The existing Selenium job remains `30 8 * * *` (UTC), which is 11:30 Istanbul.
Enable `INSTAGRAM_FEED_FORMAT=carousel` to change only its Feed output. The Story
still uses one 1080×1920 rate card. Each Feed slide is a JPEG at 1080×1350.

## Slides and sources

1. Kiani customer rate card in the approved Feed design, fetched directly from `KIANI_RATES_URL`.
2. Iranian exchange USDT comparison, including asks, bids, averages, best prices,
   and available 24-hour/monthly changes.
3–5. Iran free-market FX split into three readable pages of at most nine rows.
6. Hawala customer quotes from the exact successful Telegram delivery export.
7. Kiani TRY customer buy/sell quotes and existing coordination contacts.

The cover and final TRY card share one API response. No percentage adjustments
are reapplied to those already calculated customer quotes. Market and exchange
prices are labelled as informational and can differ from Kiani's customer rates.

The Feed design uses RTL tables, bold prices, bundled country flags and icons,
and a progress bar that fills from the right. Page numbers remain at bottom left.
The supplied Kiani Exchange monogram appears large on the cover and beside the
brand name on every other slide. Its bundled SVG is drawn directly with Pillow.
Vazirmatn Bold and a Twemoji atlas are bundled; rendering needs no asset downloads
or new Python dependencies. Artwork attribution is included in the caption and
`assets/instagram/README.md`. The brown sample ribbon appears only in previews.

The market tables come from the installed Telegram publisher, using its
`--export-json` action. The action fetches current sources, uses the production
safety/history database through a consistent SQLite backup, and returns only
assessed/verified content. Even collector schema initialization is isolated from
production history. It sends no
Telegram messages. This upgrade does not change Telegram or mini-app code.

Missing/unverified market sections are omitted with a log entry. A completely
unavailable market collection still permits the two Kiani customer quote slides
when the customer API is available. Customer API failure blocks publication.
Missing changes appear as `—`; no past/sample prices are substituted.
Market table exports must be no older than five minutes when publication begins.

Hawala requires `INSTAGRAM_HAWALA_SNAPSHOT` pointing to the existing export with:

```json
{"source":"kiani-hawala","generated_at":"2026-10-09T08:25:00+00:00",
 "rates":{"USD":262600,"EUR":294500,"GBP":347400,"CAD":184600,
          "AUD":182800,"SEK":26300,"TRY":5330}}
```

These are schema examples, not current prices. The live file must come from the
successful Hawala Telegram publisher and be no older than 15 minutes. A future
11:45 Telegram delivery cannot supply the 11:30 carousel; use an existing fresh
earlier export or arrange a read-only Hawala calculation before that time.
The running Selenium Hawala process has its export configured at
`/home/kianirad2020/.local/state/kiani-x/hawala.json`. Its actual generation time
and availability at the 11:30 slot still need a server check.

## Preview before activating

Fetch PR 51 into a separate checkout; keep the production checkout's local
customer-rate patch and existing env/state files until the new preview is reviewed.
Use the existing Instagram virtual environment for rendering. The Telegram source
export runs with `/usr/bin/python3`, which has the production collector dependencies.

```bash
(
set -e
REPO="$HOME/telegram_bot_repo"
git -C "$REPO" fetch origin pull/51/head
WORK=$(mktemp -d /tmp/kiani-instagram-carousel.XXXXXX)
git -C "$REPO" worktree add --detach "$WORK" FETCH_HEAD

set -a
. "$HOME/.kiani-instagram.env"
set +a

INSTAGRAM_PUBLISH_MODE=feed \
INSTAGRAM_TELEGRAM_REPO="$REPO" \
  "$HOME/kiani-instagram-venv/bin/python" \
  "$WORK/instagram_daily_rates.py" --dry-run --carousel \
  --output /tmp/kiani-instagram-carousel-preview

printf 'Review checkout: %s\n' "$WORK"
)
```

This fetches live rates and renders locally. It does not create Instagram
containers or publish anything. The displayed JPEG paths and adjacent manifest
list the included sections. Do not copy the whole `.env` into chat.

For design-only previews without access to live sources:

```bash
"$HOME/kiani-instagram-venv/bin/python" \
  "$WORK/instagram_daily_rates.py" --sample-preview \
  --output /tmp/kiani-instagram-carousel-sample
```

Sample images have a visible Persian sample label. `--sample-preview --publish`
is rejected. The sample fixture is never used by a live run.

## Activate after reviewing the live preview

Install only the publisher files into the existing standalone publisher checkout;
keep its token, per-mode daily state files, wrapper, nginx paths and cron schedule.
Make a private backup of the publisher and env first. Copy `instagram_daily_rates.py`
and `instagram_carousel.py` from the reviewed checkout, plus
`fonts/Vazirmatn-Bold.ttf`, `fonts/OFL.txt`, and the complete `assets/instagram/`
directory. Keep the existing `fonts/Vazirmatn-Regular.ttf`. The current Pillow/Arabic
dependencies are sufficient; no backend or bot restart is needed. Missing design
assets produce a clear error instead of a partial carousel.

Add the following non-secret settings to `~/.kiani-instagram.env`:

```bash
INSTAGRAM_FEED_FORMAT=carousel
INSTAGRAM_TELEGRAM_REPO=/home/kianirad2020/telegram_bot_repo
INSTAGRAM_TELEGRAM_PYTHON=/usr/bin/python3
INSTAGRAM_MARKET_HISTORY_DB=/home/kianirad2020/telegram_bot_repo/channel_split/market_history_production.sqlite3
INSTAGRAM_HAWALA_SNAPSHOT=/home/kianirad2020/.local/state/kiani-x/hawala.json
```

Keep the env private with mode 0600. The existing wrapper already overrides the
image directory, public URL and daily state file for each mode. The new Feed
setting has no effect on its Story run. It is read on the next scheduled run;
cron does not need a restart. Normal daily duplicate protection remains enabled,
and a per-state-file lock prevents concurrent manual/cron publication.

The publish flow creates one child container per image, then a `CAROUSEL` parent
and publishes the parent once. JPEG URLs are checked before creating any container;
every container must report `FINISHED`. Daily state is saved only after success.
All slides keep the same 4:5 ratio. This implementation accepts 2–10 images.

Inspect `~/kiani-instagram-cron.log` after the first scheduled carousel. A manual
`publish` run today skips a Feed already published today. Use `--force` only when
another Feed publication is intentional, with the Feed's proper state file.

## Rollback

Set `INSTAGRAM_FEED_FORMAT=single` in the env to restore the one-image Feed on the
next run. The Story schedule and existing daily duplicate state stay in place.

Validation so far: sample render and visual review of all seven layouts, plus
syntax compilation. The real assessed exports, public carousel URLs and Meta
publication need a Selenium preview and first live run; no live carousel was
published during development.
