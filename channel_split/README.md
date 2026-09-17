# AlanChande / Kiani channel split — test rollout

This directory is the first implementation of the two-brand Telegram model:

- **AlanChande** = market information / utilities / comparisons.
- **Kiani Exchange** = Kiani's actual buy/sell and transaction rates.

No production Telegram channel ID or bot token is hard-coded. The same scripts
can be tested against two brand-new channels and later switched to production
only by changing environment variables.

## Test publishing bots

The current test rollout uses two separate Telegram bots:

- `@alanchandetestbot` — publishes AlanChande informational/test posts.
- `@kianiexchangetestbot` — publishes Kiani Exchange transactional/test posts.

Each bot should be added as an **administrator** only in its matching test
channel, with permission to post messages.

Do not commit BotFather tokens to GitHub. Keep them in environment variables or
a server-side secret/env file excluded from Git.

## Current MVP posts

### AlanChande

`bank-comparison`

Publishes USD/TRY buying/selling rates for:

- Kapalıçarşı
- Garanti BBVA
- İş Bankası
- Kuveyt Türk
- Ziraat Bankası

For the MVP all rows are read from the same public `kur.doviz.com` comparison
table to keep the values synchronized to one timestamp/source. The post clearly
attributes that source.

The source layer is deliberately isolated in `bank_compare.py`, so we can later
replace rows with official providers.

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
the provider's reuse/licensing terms. This MVP is for the two private/test
channels first.

## Test-channel setup

Create two new Telegram **channels** separately from the bots, for example:

- `AlanChande Test`
- `Kiani Exchange Test`

Then:

1. Add `@alanchandetestbot` as admin of `AlanChande Test`.
2. Add `@kianiexchangetestbot` as admin of `Kiani Exchange Test`.
3. Give each bot permission to post messages.
4. Obtain the two BotFather tokens privately on the server.
5. Use either the public channel username (`@...`) or numeric `-100...` channel
   ID as the destination value.

Export:

```bash
export ALANCHANDE_TELEGRAM_BOT_TOKEN='...'
export ALANCHANDE_CHANNEL_ID='@your_alanchande_test_channel'

export KIANI_TELEGRAM_BOT_TOKEN='...'
export KIANI_CHANNEL_ID='@your_kiani_test_channel'
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
