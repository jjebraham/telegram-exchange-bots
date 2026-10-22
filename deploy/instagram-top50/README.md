# Kiani top 50 cryptocurrency prices

One Instagram Feed carousel daily at **16:00 Europe/Istanbul (13:00 UTC)**.
There are six 1080 × 1350 JPEG slides: a 24-hour gainers cover followed by
the existing five price slides, with ten of the top 50 coins on each price slide.
The installed rates, economy news and crypto news jobs keep their schedules.

## Gainers cover

- The owner selected the **top 100 by market capitalization**, not just the 50
  coins in the price tables. Define that universe globally BEFORE excluding
  stablecoins and wrapped/staked duplicates, using CoinPaprika USD market caps.
- Rank eligible coins by full-precision **positive 24-hour USD price change**,
  descending. Market cap descending and coin ID break ties deterministically.
  Require USD trading volume over the same 24 hours to be **greater than 50,000**.
  Apply the existing exact-identity classification exclusions and freshness rules.
- Show at most ten. If fewer than ten qualify, display the actual count; never
  call a losing/unchanged coin a gainer. If none qualify, the cover says so and
  the usual 50-price slides remain. Missing/stale/malformed candidate data is
  excluded with a reason; an incomplete top-100 market-cap universe blocks the run.
- USD prices, Toman conversions and percentage changes come from the same
  snapshot as the five price slides. All conversions use the same market USDT
  rate rounded to the nearest 100 Toman, preserving full USD source precision.
- Save the 100-member source evidence, classifications, policy, exclusions and
  selected ranking. Recompute that ranking before rendering/publication and
  recheck selected quote/rate freshness immediately before final publication.
- This uses the existing **CoinPaprika** feed. CoinMarketCap's gainers page is
  the feature reference, not an additional data source or a promise of identical
  rankings. Both source name and the 24-hour window are labelled on the slide.
- The existing delayed Story uses the first image, so it will preview gainers
  30 minutes after a successful Feed. No new Story job or second Feed is added.
  Top 50 remains protected from the news-retention deletion policy.

## Upgrade the existing deployed publisher

Use the pinned `deploy/instagram-top50/run_gainers.py` bootstrap. Default mode
extracts nine small files without a full checkout and renders a six-slide live
preview. There is no Meta API contact. It prints the preview links.

`--activate` verifies the installed PR55 runtime/launcher, exact existing daily
16:00 Istanbul cron entry, Story source and matching six-slide preview from the
new runtime/assets within 24 hours. A separate fresh source-only validation is
required at activation. It installs an immutable versioned runtime and switches
only the top 50 launcher to that runtime, with private backup and guarded rollback.
An identical repeat is accepted; unexpected installed edits refuse activation.

The crontab, Story registration and original publication database are not
rewritten. Existing successful posts still count toward the daily duplicate
guard. No immediate publication, catch-up or historical Story occurs during
installation. No automated unit tests run as part of the upgrade.

The previous schema-2 saved snapshots remain previewable with the sample banner;
new publication requires schema 3 and exactly six slides with gainers first.

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
  is approximate and awaits a second source. The upstream FIVE-source transaction
  quorum remains unchanged; a sub-quorum snapshot stays `ok=false`.
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

It collects fresh prices and saves six slides without publishing. To publish
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
