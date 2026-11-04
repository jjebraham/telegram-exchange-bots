# Kiani top 50 cryptocurrency prices

One Instagram Feed carousel daily at **16:00 Europe/Istanbul (13:00 UTC)**.
There are twelve 1080 × 1350 JPEG slides: a market-pulse cover, a decliners
slide, and ten price slides with five coins each and larger type.

The cover counts the positive, negative and unchanged 24-hour USD movements
among the top-50 coins with a reported change, and shows BTC and ETH when
available. It also displays at most five eligible gainers whose displayed change
is greater than 2%. The second slide shows at most five eligible decliners with
a displayed change below -2%. These lists use the existing top-100 universe,
classification exclusions, quote freshness and 24-hour volume above $50,000.
An empty or short list is labelled accurately rather than filled with arbitrary
coins. The caption describes the different universes and threshold.

## Upgrade the existing deployed publisher

The pinned `run_gainers.py` stages an exact release and makes a fresh twelve-slide
preview without contacting Meta. Before activation, `check_meta12.py` creates
12 temporary image containers and a carousel container to check compatibility;
it does not publish. Activation requires its recent account-specific proof. `--activate` verifies the previously deployed
PR #86 revision `4ac7df62d40ab64f5310e6be402a622ffa5eb9d6`, source hashes,
launcher, existing UTC schedule and Story registration. It requires a matching
recent preview and a separate fresh source check, and creates a backup before
activation. It posts nothing. The first slide remains the delayed Story image.
The same source-evidence expiry and daily duplicate protections apply.

## Fix for evidence expiring during Meta preparation

The 23 and 24 October server jobs collected valid Akamai prices and generated
all six slides, but their original market proofs expired while six Meta child
containers were prepared sequentially. Both rows are `failed` with no media ID;
the 24 October original expiry was 13:00:51 UTC and the job failed at 13:01:00.

- Verify public images concurrently, with at most three requests in flight.
- Prepare/wait for Meta child containers with at most three workers. Keep the
  exact slide order, all child readiness checks, parent readiness, and the single
  final publication request. SQLite writes remain on the main thread.
- Typed expiry errors allow at most **three total preparation attempts** in one
  publishing invocation, separated by two seconds. Each retry collects all
  CoinPaprika data and a fresh Akamai quote, renders twelve new uniquely named
  images, saves a separate snapshot/manifest, and creates new containers.
- No old evidence, images or containers are relabelled as fresh. The quote's
  original 90-second proofs, original expiry, <=35-second collector age at
  collection, agreement, liquidity, units and conversions are unchanged.
- Future-dated/invalid evidence and non-expiry errors are not automatically
  retried. An uncertain final publish still records `needs_review` and blocks
  automatic/manual blind retries. A date change stops next-day catch-up.
- The final full validation still runs immediately before `media_publish`.
  Expiry under persistently slow processing can still safely block publication
  after the bounded attempts; this fix does not promise a daily post regardless
  of source health.
- Timing logs identify collection/render/public-image/child/parent/final-check
  stages, original expiry, remaining seconds and failure type. Graph exception
  bodies, tokens and private transport diagnostics are not printed.

The installer preserves cron, the Story worker/configuration, credentials,
the publication database, all other publishers and the existing daily guard.
Preview and activation do not publish. After successful activation, the owner
may retry the existing daily launcher with fresh data; any already-published or
uncertain day remains protected by the same duplicate guard.

## Prices and selection

- CoinPaprika `/v1/tickers?quotes=USD` supplies prices, market capitalization,
  the provider rank, update timestamps and the USD price change over 24 hours.
- Coins are sorted by USD market capitalization, with deterministic tie breaks.
  The displayed positions 1–50 are positions after exclusions, rather than the
  provider's global ranks. The provider ranks remain in the saved snapshot.
- The reference excludes stablecoins and wrapped/staked copies of other coins.
  Classification uses fresh CoinPaprika stablecoin and wrapped-token tags,
  supplemented by explicit identities and name rules because these tags omit
  several major coins. Dollar/euro and gold-pegged coins are excluded. Liquid
  staking governance tokens are not excluded just because of a sector tag.
  New identities remain dynamic; the top 50 is not a fixed list from the PDF.
- **Market USDT rate:** reuse the existing Akamai collector's local snapshot at
  `~/.local/state/kiani-akamai-rates/snapshot.json`. Iranian exchange API calls
  already run through its restricted SSH transport; this Instagram job makes no
  direct exchange requests from Google. CoinPaprika USD collection is unchanged.
- Use the **median unadjusted market ask** (`buy_toman`) from the qualified
  exchanges, already normalized to Toman by the existing collector. Do not use
  Kiani customer buy/sell prices, adjustment factors, last-trade substitutes or
  a second Rial/Toman conversion. The caption identifies the contributing venues,
  describes an order-book ask median, and lists their public source websites.
- Respect the existing root-owned Akamai activation and informational-display
  flags. Its separately approved display policy permits one fresh source (or
  two under the older flag); a single-source caption explicitly says the rate
  is approximate and awaits a second source. Read the original upstream
  `minimum_sources`: support the deployed two-source policy with **both bids and
  asks agreeing within 2%**, plus the reviewed legacy five-source policy. Verify
  the corresponding `ok`/median envelope rather than hardcoding a five-source
  quorum. This reader never changes the collector's policy or `ok` value.
- Revalidate schema/transport, distinct approved venues, open markets, positive
  liquidity, uncrossed bid/ask pairs, the existing 2% spread and 8% median limits,
  original exchange timestamps or HTTP-cache-plus-observed-book-change evidence.
  Bitpin additionally needs its original market-state and recent-trade proofs.
- At collection the worker snapshot must be <=35 seconds old; original source
  proofs must be <=90 seconds old and its original `valid_until_utc` unexpired.
  Save only the required market evidence, omitting transport diagnostics/errors.
  Recompute the median and verify all source fields before rendering/publication.
  Before final publishing, original proofs/expiry must STILL be valid. Never
  renew their ages from a local file read, newer worker generation or HTTP receipt.
  Missing/unsafe/expired feed data blocks publication; there is no direct-source
  fallback, stale cached rate or change to the collector, SSH keys or services.
- The market USDT/Toman quote is **rounded to the nearest 100 Toman**, with half
  steps rounded up: 266,999 → 267,000; 268,346 → 268,300; 271,100 → 271,100.
  The rounded rate appears on every slide and is also used for conversions.
  The original unrounded market quote is retained in the saved snapshot.
- **Toman = full-precision USD × rounded market USDT/Toman.** Decimal arithmetic
  preserves the full USD source price until final display rounding. Small
  positive prices keep enough significant digits to avoid showing zero.
- All slides share the same rate and snapshot. CoinPaprika ticker timestamps
  may be at most 20 minutes old. Akamai market proofs retain their stricter
  original 90-second expiry, including immediately before final publication.
  Missing 24-hour changes show a dash. Legacy last-trade parsers remain only for
  inspecting old saved snapshots; new publication requires Akamai provenance.
- A failed classification request, stale leading price, invalid conversion or
  incomplete set prevents publication. No partial carousel is published.

## Rendering and storage

The renderer loads the existing Kiani logo and Vazirmatn fonts from
`--publisher-root`. Known identities can use pinned CC0 cryptocurrency icons;
other coins or failed icon downloads get a colored abbreviation. Unknown
Persian names use the provider's name rather than inventing a translation.
The final slide names the Telegram platform and prints
`https://t.me/kianiexchangebot`.

An independent SQLite database stores the full source snapshot, conversion
basis, slide paths, caption, runtime/asset fingerprints and publication result.
There is at most one successful post per Istanbul calendar day. A per-database
file lock prevents overlapping runs. A crash or uncertain Meta publication
blocks another attempt until the account and database have been reviewed.
Failures before the final publication request are retryable. A successful
manual post also counts as that day's post.

Preview is the default. `--publish` is an explicit action. A saved
`--sample-json` snapshot always shows the sample banner and cannot be published.

## Manual preview on Selenium

Use a detached checkout of the exact reviewed PR commit, load the existing
Instagram environment, and run:

```bash
umask 022
mkdir -p /var/www/peerexo.com/public/instagram-rates/top50
"$HOME/kiani-instagram-venv/bin/python" -u \
  "$WORK/instagram_top50_prices.py" \
  --publisher-root "$HOME/kiani-instagram-publisher"
```

It collects fresh prices and saves twelve slides without publishing. To publish
a fresh manual carousel, run the same command with `--publish`. Keep the default
database so schedule activation can find the successful manual publication.
The public directory must serve JPEGs at
`https://peerexo.com/instagram-rates/top50/`.

## Legacy first-install helpers

For an already scheduled account, use `run_gainers.py` above. The original
first-install/manual-publication helpers below are retained for reference.

Run `activate_top50_cron.py` from the exact reviewed commit using:

```bash
/usr/bin/python3 "$SETUP" --repo "$REPO" --revision "$EXPECTED" \
  --approved-media-id "$MEDIA_ID" --at 16:00
```

The helper requires a matching successful manual post, checks the shared assets
have not changed, installs a permanent publisher directory, and adds a managed
daily cron block. It verifies the existing server uses UTC and that cron is
active. It preserves other cron jobs, backs up replaced files and the crontab,
and rolls back its changes if installation fails. It never publishes while
activating the schedule. No additional API key or translation service is needed.

When publication and deployment have already been approved, the shorter
`publish_and_activate.py` helper runs one fresh publication from an exact
detached checkout, then finds its matching successful media ID and invokes the
same activation checks. Load the existing Instagram environment first:

```bash
/usr/bin/python3 "$WORK/deploy/instagram-top50/publish_and_activate.py" \
  --repo "$REPO" --revision "$EXPECTED" --at 16:00
```

The helper checks that the runtime and installer files match the pinned Git
revision. Publication failure stops activation. Existing daily duplicate
protection remains in effect; uncertain results are not retried blindly.

Publisher path: `~/kiani-instagram-top50-publisher/instagram_top50_prices.py`.
Wrapper: `~/publish-kiani-instagram-top50.sh`.
Database: `~/.local/state/kiani-instagram-top50/top50.sqlite3`.
Log: `~/kiani-instagram-top50-cron.log`.

View recent publication history without fetching or posting:

```bash
"$HOME/kiani-instagram-venv/bin/python" \
  "$HOME/kiani-instagram-top50-publisher/instagram_top50_prices.py" --status
```

Data documentation:
[CoinPaprika tickers](https://docs.coinpaprika.com/api-reference/tickers/get-tickers-for-all-active-coins),
[CoinPaprika classifications](https://docs.coinpaprika.com/api-reference/tags/get-tag-by-id),
[Wallex market API](https://docs.wallex.ir/#api-Market-getMarkets),
[Exir ticker API](https://apidocs.exir.io/),
[Exir's IRT/Toman denomination](https://www.exir.io/),
[Nobitex recent trades](https://github.com/nobitex/docs-api/blob/master/source/includes/_market_data.md),
[Nobitex Rial API units](https://github.com/nobitex/docs-api/blob/master/source/includes/_market_trade.md).

## Provider connection failures

The publisher reports the failing public host and endpoint, with a DNS, timeout,
TLS or HTTP error category. Proxy addresses and credentials are not logged.
Run a read-only check with the same Python interpreter as the live publisher:

```bash
"$HOME/kiani-instagram-venv/bin/python" "$WORK/crypto_top50_data.py" --check-sources
```

This checks the two classification endpoints, USD tickers and the existing
local Akamai feed without publishing, changing the database or activating cron.
It does not make direct Iranian exchange requests. It reports the actual
contributing source count, unadjusted median ask and original feed expiry.
Keep `set -e` inside the displayed subshell block: running it directly in an
interactive SSH shell causes a failed command to close that shell.
