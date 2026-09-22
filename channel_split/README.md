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
- `alanchande-iran-fx` — Iran open-market currency board (25 currencies), normalized from TGJU rial values to toman. During the current shadow rollout it intentionally remains safety-BLOCKED until an independent second verifier family is added.
- `alanchande-iran-gold` — Iranian coin/gold prices, converted from rial to toman.
- `alanchande-usdt-exchanges` — production 7-exchange hybrid USDT board. It combines direct exchange APIs where available with TGJU/Ramzarz fallbacks per exchange.
- `alanchande-usdt-direct` — direct-source-only USDT comparison for diagnostics.
- `alanchande-usdt-tgju` — legacy TGJU comparison for diagnostics/fallback validation.
- `alanchande-markets` — resilient bundle of Turkey gold, Iran gold/coins and the 7-exchange USDT board. One failed market source does not block the healthy posts.
- `alanchande-fx-pulse` — compact Kapalıçarşı USD/TL + EUR/TL midpoint board with ~24-hour changes.
- `alanchande-daily` — resilient daily AlanChande package: USD bank comparison, Iran open-market FX, Turkey FX pulse, Turkey gold, Iran gold/coins and 7-exchange USDT.

The USD/EUR comparison source layer is isolated in `bank_compare.py`.
Turkish gold is isolated in `gold_prices.py`. Iran gold/coin is isolated in
`iran_gold.py`.

The production USDT board is isolated in `hybrid_usdt_compare.py`. It targets
Wallex, Nobitex, Ramzinex, Bitpin, AbanTether, Tabdeal and Exir. Direct exchange
quotes are preferred per row; TGJU and Ramzarz are used as fallbacks when a
direct source is unavailable. The board requires at least five surviving
exchanges, rejects crossed customer-facing bid/ask pairs, applies an 8% median
outlier guard, and reports how many rows came from direct versus fallback
sources.

The older `direct_usdt_compare.py`, `primary_usdt.py` and TGJU-only commands
remain available for diagnostics and source validation, but
`alanchande-usdt-exchanges` and `alanchande-markets` use the hybrid board.

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

## Financial-rate safety gate

Production financial posts must pass the fail-closed market-safety layer before
Telegram delivery. The implementation, source-coverage matrix, alert behavior,
audit rules, and shadow-to-enforce rollout are documented in
[channel_split/SAFETY.md](SAFETY.md).

Keep the test rollout in:

    MARKET_SAFETY_MODE=shadow

until independent verifier coverage and shadow logs are clean. Production
scheduling should use:

    MARKET_SAFETY_MODE=enforce

and must not be enabled merely because a source is reachable.

Recent non-dry-run safety decisions can be inspected with:

    python3 publish_channels.py --safety-status

## Staggered shadow-test scheduler

The test rollout separates fast IRR-denominated boards from slower market
boards so volatile toman/rial markets can be observed without dumping unrelated
posts together.

Fast boards:

- every hour at :10 Istanbul — Iran USDT comparison
- every two hours at :30 — Iran open-market FX (25 currencies)

Slower boards:

- 00:50 Istanbul — USD/TRY bank comparison
- 06:50 — Turkey gold
- 12:50 — Turkey FX pulse
- 18:50 — Iran gold/coin

All shadow launchers hard-check that `channel_split/.env` still contains exactly:

    ALANCHANDE_CHANNEL_ID=@alanchandetest

and force `MARKET_SAFETY_MODE=shadow` plus
`MARKET_HISTORY_DB=market_history_shadow.sqlite3`. If the destination changes,
the test schedulers refuse to run.

The fast boards and slow rotation share the same lock, so two shadow publishers
cannot run concurrently.

The Iran open-market FX board currently has only TGJU as a verifier family.
That is intentional during shadow observation: it will still appear in the test
channel, but safety will report `BLOCKED` and the private admin alert group
should receive the corresponding alert. Do not enable this board in production
enforce mode until an independent second verifier is added and validated.

Production cadence is not locked to the test cadence. The test schedule is
deliberately frequent so we can measure intraday movement and later decide
whether to publish every hour, every two hours, or only on significant changes.

## Production cut-over

The publisher auto-loads `channel_split/.env` on the server. Do not commit that
file or any real BotFather token.

Before cut-over, run the full test suite and preview the complete daily bundle:

```bash
cd /home/kianirad2020/telegram_bot_repo
python3 -m unittest discover -s tests -p 'test_channel_split_*.py' -v

cd channel_split
python3 publish_channels.py --post alanchande-daily --dry-run
```

After test-channel validation, replace only the test secrets/destinations with
the production values:

```bash
ALANCHANDE_TELEGRAM_BOT_TOKEN=<production AlanChande publisher token>
ALANCHANDE_CHANNEL_ID=@alanchande_com

KIANI_TELEGRAM_BOT_TOKEN=<production Kiani publisher token>
KIANI_CHANNEL_ID=@ExchangeKiani
```

and ensure each production publisher bot is an admin of its matching channel.

For the first production run, send the daily bundle manually once and inspect
all resulting posts before enabling any scheduler:

```bash
python3 publish_channels.py --post alanchande-daily
```

Successful non-dry-run market posts record local SQLite history only after
Telegram delivery. Bank/FX, Turkey gold and Iran gold therefore gain genuine
`Δ24H` values on later daily runs. The history lookup accepts snapshots roughly
18–30 hours old and chooses the one closest to 24 hours.

Do not run multiple copies of the daily publisher concurrently. Use the
repository launcher `run_alanchande_daily.sh` from cron/systemd once the final
posting time has been chosen.

## Next implementation steps

- verify third-party market-data reuse/licensing terms before sustained production redistribution;
- replace aggregator bank rows with official adapters where stable APIs/endpoints and reuse terms permit it;
- add significant-change alerts instead of repetitive ticker spam;
- extend stored history into 7-day chart data;
- decide the final production posting time, then enable the scheduler;
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
python3 publish_channels.py --post alanchande-usdt-direct --dry-run
python3 publish_channels.py --post alanchande-usdt-tgju --dry-run

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

The production USDT board now uses the seven-exchange hybrid strategy described
above: direct data is preferred per exchange row and TGJU/Ramzarz fill unavailable
rows. The direct-only and TGJU-only commands remain diagnostic tools. Before
production-scale redistribution, verify each provider's reuse/licensing terms and
continue monitoring API/schema changes.

## Daily production launcher

`run_alanchande_daily.sh` is a thin production-safe wrapper around
`publish_channels.py --post alanchande-daily`. It uses `flock` to prevent
overlapping runs, changes to the correct repository directory itself, and leaves
stdout/stderr available to cron/systemd logging.

Manual preview remains:

```bash
python3 publish_channels.py --post alanchande-daily --dry-run
```

Manual production execution through the lock-protected launcher:

```bash
/bin/bash run_alanchande_daily.sh
```

A systemd oneshot service is included at:

```text
deploy/systemd/alanchande-daily.service
```

Install and validate the service only after the production `.env` has been
reviewed:

```bash
sudo install -o root -g root -m 0644 \
  deploy/systemd/alanchande-daily.service \
  /etc/systemd/system/alanchande-daily.service

sudo systemctl daemon-reload
sudo systemctl cat alanchande-daily.service
```

Do not enable a timer yet. The scheduler itself should only be created/enabled
after the exact daily posting time has been confirmed.
