# Weekly crypto calendar

The approved slot is **Friday 18:00 Asia/Tehran**, with a first-slide Story
30 minutes after actual successful Feed publication. UTC host cron starts Friday
14:30 UTC and retries temporary failures every 15 minutes until 19:45 Tehran.
One successful Feed per Friday week; no immediate publication during setup.

## Sources and limits

Each invocation refreshes five official source families:

- **Ethereum Foundation:** official RSS discovers up to eight recent upgrade
  announcements. Fetch each original announcement, read its deployment table,
  and cross-check the UTC clock against the Unix timestamp. The latest table
  for each fork/network supersedes older tables, including a newer TBD.
- **BNB Chain:** the ten latest `bnb-chain/bsc` GitHub releases. Only explicit
  activation/schedule/hardfork lines containing a named network and UTC clock
  qualify. Cross-check a Unix timestamp when present.
- **TRON:** the same bounded adapter against `tronprotocol/java-tron` releases.
  A published binary or a mandatory-update notice without a future activation
  clock is not a scheduled upgrade. Governance proposals without a confirmed
  future activation time are not supported in this version.
- **Plasma:** refresh the official XPL tokenomics. The reviewed monthly vesting
  terms must still match. The 25th-of-month estimate follows the mainnet launch
  anniversary; it is visibly marked estimated, not an official exact-date
  announcement. Individual vesting start dates may differ. There is no invented
  release hour, token amount, or prediction of sales. This is the only token
  unlock adapter in this version; it is not a market-wide unlock database.
- **Deribit:** query active BTC and ETH option instruments from the public API.
  Select the common, actually listed final-Friday expiry and cross-check each
  instrument's name against its expiration timestamp. No open-interest amount
  or price-direction prediction is created. The caption links the official
  contract policy; private evidence retains both API URLs and example instruments.

Mainnet and testnet have separate visible labels. No feed publication date is
reused as an activation date. The first version does not predict Bitcoin halving
dates, scrape unofficial calendars, or generate event facts with an AI model.
Additional chains/tokens require another reviewed source adapter.

Every source family must verify successfully. A healthy source with no qualifying
future dates is normal (e.g. a TRON release without an activation clock). Errors,
unexpected formats and timestamp disagreements stop publication and are recorded
privately. TLS verification is always enabled. No stale cache is published.

The window is Friday 18:00 Tehran through the next Friday 18:00, exclusive of
the end. Date-only estimates qualify only on whole intervening Tehran dates;
uncertain first/last-day estimates are excluded. Select at most six events:
Ethereum mainnet 100, other mainnet 95, month-end expiry 90, XPL estimate 80,
Ethereum testnet 65, other testnet 60. Then display chronologically. Empty weeks
are skipped; there is no filler or guarantee that every week has six events.

## Rendering, state and publishing

The existing Kiani logo, Vazirmatn fonts and pinned Persian calendar library
render deterministic 1080x1350 cards. Three events per slide, up to two slides.
Persian digits, Gregorian/Jalali dates and Tehran clocks derive from the same
event instant. Date-only estimates use civil-date conversion without displaying
an artificial time. Clock labels display hours/minutes; source seconds remain
in the private audit. This post requires no translation/image-generation API.

Private state: `~/.local/state/kiani-instagram-crypto-calendar/calendar.sqlite3`.
Previews and snapshots are persisted with runtime/assets hashes. Audits are
private `runs/*/audit.json`; only JPEGs are public. Publication records use the
existing Story adapter's schema. A unique Friday week key, publication lock and
uncertain-final-request status prevent automatic duplicate publication.

Sources must be refreshed within 20 minutes of publishing, the run must be
Friday 18:00–20:00 Tehran and exact-time events must still be in the future.
Existing rates/news/top50/economic-calendar schedules and databases are retained.
The only Story changes add the optional `crypto_calendar` kind and its label;
the existing queue, cutoff and delay rules continue to apply.

## Deployment

Extract and run `deploy/instagram-crypto-calendar/run_calendar.py` from the exact
reviewed Git revision with `--repo REPO --revision SHA`. It extracts ten small
files, no full repository checkout or new venv. The default mode refreshes live
sources and prints preview links without Meta API contact or cron changes.

Review that server output and images, then use `--activate`. Activation requires
a successful exact-runtime/assets preview within 48 hours. It requires the
already-installed economic-calendar Story revision (PR63), UTC cron and the
existing private publisher environment. It backs up changed files and cron,
installs a versioned runtime, adds this calendar source to the current Story
config and uses guarded rollback if installation fails. No existing jobs are
removed and no historical Stories are enqueued.

Log: `~/kiani-instagram-crypto-calendar-cron.log`.
Status: the installed version's `instagram_crypto_calendar.py --status`.
