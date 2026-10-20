# Weekly economic calendar

One scheduled Instagram Feed post every **Saturday at 10:00 Asia/Tehran**.
The installed host uses UTC; the exact cron entry is Saturday **06:30 UTC**.
The existing delayed Story worker sends the first slide 30 minutes after actual
successful Feed publication (normally around 10:30 Tehran).

## Content and sources

- Covers the seven days from Saturday 10:00 Tehran to the following Saturday
  10:00, exclusive of that ending instant.
- Refreshes the official calendars at every invocation; there is no stale cache,
  model-created schedule, inferred release result, or market forecast.
- US CPI, PPI, employment, employment cost and JOLTS: the official
  [BLS iCalendar](https://www.bls.gov/schedule/news_release/bls.ics), with official
  monthly list pages as an alternate format. The source time is Eastern Time.
- US PCE and GDP: the official [BEA release schedule](https://www.bea.gov/news/schedule).
- Fed decisions: the relevant official Federal Reserve monthly calendars, reading
  the decision row's actual date and time (not the press-conference/minutes row).
- ECB decisions: [meeting calendar](https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html)
  paired with the [official 14:15 notice](https://www.ecb.europa.eu/press/govcdec/mopo/html/index.en.html).
  The source time is interpreted with Europe/Berlin on each event date.
- BoE decisions: [confirmed meeting dates](https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates)
  paired with the [official noon announcement notice](https://www.bankofengland.co.uk/monetary-policy).
- Every reviewed source family must verify successfully. Missing, blocked,
  malformed, date-only or floating-time information stops publication and records
  source health privately. Normal TLS verification remains enabled.
- Select up to six events by fixed editorial priority: CPI/Fed 100, ECB 95,
  BoE/PCE 90, US jobs 85, PPI 75, GDP 70, employment cost 65, JOLTS 60. Display
  selected events chronologically. Extra eligible events are recorded in the
  audit. Empty weeks are skipped explicitly, without manufactured filler.

All source clocks use IANA zones (America/New_York, Europe/Berlin, Europe/London)
before conversion to Asia/Tehran. This handles different daylight-saving change
dates. Persian and Gregorian labels derive from the same Tehran event instant.
The installed pinned Persian calendar library, Vazirmatn fonts, Kiani vector logo
and a deterministic Pillow layout implement the approved preview. There is no
scheduled image-generation or translation API charge for this post.

One to three events occupy each 1080×1350 slide; four to six use a two-slide
carousel. The first slide is the delayed Story preview. The caption links each
event's official calendar and states that this is a selected list.

## State and publication

Private state: `~/.local/state/kiani-instagram-economic-calendar/`.
The SQLite database contains reviewed previews and a unique Saturday week record.
Public JPEGs: `/var/www/peerexo.com/public/instagram-rates/economic-calendar/`.
Preview JPEGs use a separate `economic-calendar-preview/` directory and badge.
Private source evidence and health remain in `runs/*/audit.json`.

The existing official Meta helper publishes one image or a two-image carousel.
Only Saturday 10:00–12:00 Tehran permits publication, with sources checked within
20 minutes and all listed events still in the future. A persistent publication
lock and unique week key prevent duplicates. Ambiguous final requests and
interrupted attempts require review; no blind automatic republishing occurs.

The Story worker change only adds the optional `calendar` source and label.
Existing four-source configurations remain compatible. Installation appends the
new database path to the existing config, preserving its other keys and queue.
The calendar uses the existing publication-record schema adapter. No direct
queue insertion or new Story scheduler is introduced.

## Deployment

Run `run_calendar.py --repo REPO --revision REVIEWED_SHA` extracted from the exact
reviewed Git revision. It extracts eight small files and uses the existing venv;
no full worktree, new environment or package install is required. The default
mode refreshes the next Saturday's calendar and renders a live preview without
contacting Instagram or changing cron. Review the printed image links first.

Repeat with `--activate` to install. Activation requires a successful preview
within 48 hours from the same runtime and fonts/logo. It verifies UTC cron,
the existing Story config/queue and hashes of the reviewed Story files, backs up
all changed files and crontab, installs a versioned runtime, and preserves all
other jobs. Concurrent changes stop installation; guarded rollback retains
external edits. Installation never publishes an immediate Feed or Story.

Schedule log: `~/kiani-instagram-calendar-cron.log`. Latest publication records:
`~/kiani-instagram-economic-calendar-releases/SHA/instagram_economic_calendar.py --status`.
If any source is unavailable on the server, inspect its printed source-health
result before activation. Local network availability is not proof of server
access. No browser security challenge or access control is bypassed.
