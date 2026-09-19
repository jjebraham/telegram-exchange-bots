# AlanChande / Kiani channel split — test rollout

This directory is the first implementation of the two-brand Telegram model:

- **AlanChande** = market information / utilities / comparisons.
- **Kiani Exchange** = Kiani's actual buy/sell and transaction rates.

No production Telegram channel ID or bot token is hard-coded. The same scripts
are tested against dedicated test channels first and later switched to production
only by changing environment variables.

## Test publishing bots and channels

The current test rollout uses two separate Telegram bots and two matching test
channels:

- `@alanchandetestbot` → publishes to `@alanchandetest`
- `@kianiexchangetestbot` → publishes to `@kianiexchangetest`

Each bot must be added as an **administrator** only in its matching test channel,
with permission to post messages.

Do not commit BotFather tokens to GitHub. Keep them in environment variables or
a server-side secret/env file excluded from Git.

## Current MVP posts

### AlanChande

Available post names:

- `bank-comparison` — USD/TRY bank/Kapalıçarşı comparison.
- `eur-bank-comparison` — EUR/TRY bank/Kapalıçarşı comparison.
- `bank-comparisons` — sends both USD and EUR comparisons.
- `alanchande-converter` — Toman → TRY practical examples.
- `alanchande-snapshot` — compact market snapshot.
- `alanchande-daily-change` — intraday USD/EUR movement from local SQLite history.
- `alanchande-turkey-gold` — Turkish Kapalıçarşı gold products.
- `alanchande-iran-gold` — Iranian coin/gold prices + coin bubbles, converted from rial to toman.
- `alanchande-usdt-exchanges` — USDT sell prices across selected Iranian exchanges.
- `alanchande-markets` — sends the Turkish-gold, Iran-gold and Iran-USDT boards together.

The USD/EUR comparison source layer is isolated in `bank_compare.py`.
Turkish gold is isolated in `gold_prices.py`. Iran gold/coin is isolated in
`iran_gold.py`, and the Iranian-exchange USDT board is isolated in
`iran_usdt.py`.

The USDT comparison intentionally fails closed when too few preferred exchanges
survive freshness/outlier checks. It filters older source-date rows, rows more
than 90 minutes behind the freshest same-day quote, and sell-price outliers more
than 12% away from the median.

### Kiani Exchange

`kiani-rates`

Reads Kiani's existing public source of truth:

`https://miniapp.kiani.exchange/api/rates/current`

and publishes TRY + USDT buy/sell rates to the Kiani test channel.

## Bank-source research / preferred long-term source

1. **Ziraat Bankası** — preferred official API. Ziraat's Developer Portal lists
   Exchange Rates APIs (`/portal/treasure/exchangerates/query`, query-by-code,
   v2). Production integration should use this once developer credentials are
   available.
2. **İş Bankası** — official public FX page exposes live Instant Banking
   buy/sell rates. We can add a bank-specific official adapter after validating
   a stable machine-readable endpoint behind the page.
3. **Garanti BBVA** — official public live FX page exposes bank buy/sell rates.
   We should likewise locate/validate its stable underlying endpoint before
   depending on it directly.
4. **Kuveyt Türk** — official Finance Portal exposes live USD/EUR and metal
   buy/sell prices. A bank-specific adapter can replace the aggregator row.
5. **Kapalıçarşı** — there is no single official bank-like API. For the first
   release we use the Kapalıçarşı quote from the same comparison source. We can
   later evaluate licensed vendors (Altınkaynak/Harem/other market-data APIs)
   if their terms and reliability are suitable.

Important: before republishing any third-party data at production scale, verify
the provider's reuse/licensing terms. This MVP is for the two test channels first.

## Test-channel setup

1. Add `@alanchandetestbot` as admin of `@alanchandetest`.
2. Add `@kianiexchangetestbot` as admin of `@kianiexchangetest`.
3. Give each bot permission to post messages.
4. Obtain the two BotFather tokens privately on the server.

Export:

```bash
export ALANCHANDE_TELEGRAM_BOT_TOKEN='...'
export ALANCHANDE_CHANNEL_ID='@alanchandetest'

export KIANI_TELEGRAM_BOT_TOKEN='...'
export KIANI_CHANNEL_ID='@kianiexchangetest'
```

Then from this directory:

```bash
python3 publish_channels.py --post bank-comparison --dry-run
python3 publish_channels.py --post kiani-rates --dry-run
```

After checking the text output:

```bash
python3 publish_channels.py --post bank-comparison
python3 publish_channels.py --post kiani-rates
```

Or both:

```bash
python3 publish_channels.py --post all
```

## Production cut-over

After several days of test posting and source/error monitoring, no code change
is required. Replace the test secrets/destinations with the production values:

```bash
ALANCHANDE_TELEGRAM_BOT_TOKEN=<production AlanChande publisher token>
ALANCHANDE_CHANNEL_ID=@alanchande_com

KIANI_TELEGRAM_BOT_TOKEN=<production Kiani publisher token>
KIANI_CHANNEL_ID=@ExchangeKiani
```

and ensure each production publisher bot is an admin of its matching channel.

## Next implementation steps

- add timestamps/staleness checks to bank comparison data;
- add EUR/TRY comparison after USD is stable;
- add morning/evening AlanChande market summary;
- add Toman→TRY / TRY→Toman human-friendly converters;
- add gold + USDT market/reference prices to AlanChande;
- add significant-change alerts instead of repetitive ticker spam;
- add state/history for day change, daily range and 7-day chart data;
- add scheduled posting only after dry-run/test channels are clean;
- replace aggregator bank rows with official adapters where stable APIs/endpoints
  and reuse terms permit it.


## New market-board test commands

From `channel_split/`:

```bash
# Run parser/unit tests first.
python3 -m unittest discover -s ../tests -p 'test_channel_split_*.py'

# Preview each new board without sending.
python3 publish_channels.py --post alanchande-turkey-gold --dry-run
python3 publish_channels.py --post alanchande-iran-gold --dry-run
python3 publish_channels.py --post alanchande-usdt-exchanges --dry-run

# Preview all three new boards.
python3 publish_channels.py --post alanchande-markets --dry-run
```

If the dry-run output is correct:

```bash
python3 publish_channels.py --post alanchande-turkey-gold
python3 publish_channels.py --post alanchande-iran-gold
python3 publish_channels.py --post alanchande-usdt-exchanges
```

Or send all three:

```bash
python3 publish_channels.py --post alanchande-markets
```

The Iran-market MVP uses public TGJU pages for test-channel validation. Before
production-scale redistribution, verify source reuse/licensing terms and monitor
the parser for upstream HTML changes.
