# Weekly market returns in toman

Owner-approved Feed slot: **Thursday 20:00 Asia/Tehran**. The first slide compares
Bitcoin, Emami coin, one gram of 18K gold, US dollar cash and Ethereum, ranked by
unrounded seven-day percentage price returns. The native 1080x1350 renderer follows
the approved mint/green design and uses Persian/Gregorian endpoint dates, a single
linear diverging chart scale, signed Latin percentages and matching asset icons.
No fees, spreads or investment recommendations are included in the returns.

## Live sources and exact conversions

- Two authenticated Servix requests per successful daily collection: supported
  catalog and a five-code current batch (USD_RLS, BTC_USD, ETH_USD, SEKKEH_RLS,
  GOLD_18_RLS). Existing private gold-publisher key; fixed HTTPS allowlist, no
  redirects, bounded response/time budgets and sanitized errors. Keys, credentials,
  raw headers and server error bodies are never printed or copied.
- Exact English labels/units, per-instrument businessTime, fresh catalog/current
  observation/value match, availability, providers and quality are checked.
  Bitcoin/Ethereum dollar quotes must be ACCEPTED. Only the previously reviewed
  RateSurf DEGRADED/excluded-source warning pattern is permitted for fiat/gold,
  with another agreeing publisher. Direct BTC_RLS/ETH_RLS are not counted as
  independent corroboration: the owner's live source check confirms they are
  derived from ASSET_USD_TIMES_USD_RLS.
- CoinPaprika exact BTC/ETH IDs, original last_updated, positive USD prices and
  liquidity corroborate Servix. No native percent_change_7d field is used.
- DolarChand cash dollar: explicit toman, original ISO board time agrees with its
  visible clock; structured buy/sell agree with visible US Dollar row. Cash USD
  midpoint uses <=2% internal spread and <=1% cross-publisher agreement with
  Servix USD_RLS/10. This is cash USD, not USDT or a customer-adjusted quote.
- Gold/Emami reuse the deployed Alanchand/DolarChand dated visible/structured
  adapters, with Servix supplementary verification. A unique largest agreeing
  cluster of >=2 publishers per instrument, <=1% range/midpoint gap. Select an
  actual quote nearest the cluster median, never invent an averaged market price.
- Convert explicit rial values exactly by /10. Compute BTC/ETH toman as the
  selected USD asset value times the SAME snapshot's validated USD/toman value.
  This is a consistent conversion-based reference valuation, not an executable
  Iranian crypto-exchange quote. Distinct publishers may share upstream feeds.

## Matched, immutable history

Observe all five markets daily at 20:00 Tehran. Original times must be <=15min
old and belong to the current Tehran day. For scheduled history they must fall
within ten minutes before or two minutes after the common 20:00 valuation anchor;
accepted source clocks across all five markets must be within ten minutes.
The first complete verified observation of each day is frozen, hashed and never
overwritten. Retries at 20:05/20:10 are bounded; no missed-day catch-up, copied
prior closing prices or historical backfill from provider percentage fields.

Only Thursday posts. Endpoints are exactly seven days apart, with like-for-like
per-market source-time ranges matching within five minutes across weeks. Returns
are computed from retained unrounded toman prices: (end/start-1)*100. Rank before
rounding; display ROUND_HALF_UP to two decimals. Missing baseline, partial data,
ambiguous consensus or mismatched original times skips the whole comparison.
The baseline is revalidated using its historical collection time, not falsely
required to be fresh today; private evidence is recomputed before final publish.

Deployment starts collecting new history. With installation on 24 October 2026,
the first Thursday baseline is 29 October; earliest full comparison is 5 November.
These are conditional attempts, not promises that failed sources will be bypassed.

## Publisher and deployment

Pinned `run_markets.py --activate` extracts only 18 files (under 512 KiB), uses the
existing Python/calendar/fonts environment, performs a fresh all-five source
preflight, then adds one daily UTC cron entry: 16:30/35/40. No checkout, package
installation or immediate publication. Public media weekly-markets; private state
~/.local/state/kiani-instagram-weekly-markets/markets.sqlite3 and runs/* audits.

Weekly idempotence, publication lock, immutable endpoint hashes, caption/image
hashes, final Thursday window, public JPEG validation and rechecks after Meta
container preparation protect publication. Uncertain final requests stay
needs_review; crashes in preparing/publishing never cause blind duplicates.

Installer verifies UTC cron, exact confirmed Story worker hashes and installed
two-hour/200-view analytics files. It adds the optional weekly_markets category
to Story and insights registries, clones the analytics release with the SAME
collector/deletion modules, and extends the identical read-only registry in a
clone of the hourly news release (all other files verified against its pinned
Git revision). This preserves Story quota discovery when the new category arrives.
It keeps credentials, enrollment, policy, decisions, news selection/publishing
logic, history and other cron entries. Weekly comparisons are protected
non-news. Existing worker sends the image as a Story +30min after Feed success.
All affected workers are locked during the switch, with backups, concurrent-edit
checks and guarded rollback. Installation never sends publish/delete requests.

`instagram_weekly_markets.py --status` is local/read-only status. Default mode
performs a live source preflight; it does not put an arbitrary-time sample into
daily history. `--layout-preview` creates a clearly marked fictional design only,
which the scheduled publication path rejects. No automated tests are added or
run by the launcher/installer.

Primary API references:
- https://servix.cc/docs/endpoints?lang=en
- https://servix.cc/docs/supported-assets?lang=en
- https://coinpaprika.com/api
