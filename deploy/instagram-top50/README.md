# Kiani top 50 cryptocurrency prices

One Instagram Feed carousel daily at **16:00 Europe/Istanbul (13:00 UTC)**.
There are five 1080 × 1350 JPEG slides, with ten coins on each slide.
The installed rates, economy news and crypto news jobs keep their schedules.

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
- **Market USDT rate:** the public Wallex `USDTTMN` pair's `stats.lastPrice`,
  already denominated in **Toman per USDT**. It is not divided by ten and no
  adjusted customer buy/sell quote is used. An unavailable quote aborts the job.
- The market USDT/Toman quote is **rounded to the nearest 100 Toman**, with half
  steps rounded up: 266,999 → 267,000; 268,346 → 268,300; 271,100 → 271,100.
  The rounded rate appears on every slide and is also used for conversions.
  The original unrounded market quote is retained in the saved snapshot.
- **Toman = full-precision USD × rounded market USDT/Toman.** Decimal arithmetic
  preserves the full USD source price until final display rounding. Small
  positive prices keep enough significant digits to avoid showing zero.
- All slides share the same rate and snapshot. Ticker update timestamps may be
  at most 20 minutes old; the observed market quote may be at most five minutes
  old at publication. This is the age of the API observation: Wallex's response
  does not provide a timestamp for the particular last trade. The last trade
  can differ from a bid/ask quote. Missing 24-hour changes show a dash.
- A failed classification request, stale leading price, invalid conversion or
  incomplete set prevents publication. No partial carousel is published.

## Rendering and storage

The renderer loads the existing Kiani logo and Vazirmatn fonts from
`--publisher-root`. Known identities can use pinned CC0 cryptocurrency icons;
other coins or failed icon downloads get a colored abbreviation. Unknown
Persian names use the provider's name rather than inventing a translation.
Slide five names the Telegram platform and prints
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

It collects fresh prices and saves five slides without publishing. To publish
a fresh manual carousel, run the same command with `--publish`. Keep the default
database so schedule activation can find the successful manual publication.
The public directory must serve JPEGs at
`https://peerexo.com/instagram-rates/top50/`.

## Activate after reviewing the manual carousel

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
[Wallex market API](https://docs.wallex.ir/#api-Market-getMarkets).
