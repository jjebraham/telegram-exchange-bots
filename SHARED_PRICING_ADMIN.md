# Canonical TRY and shared pricing integration for the main user bot

The unified admin panel owns the retail adjustment settings. The main user bot
source is maintained outside this repository, so `main_user_runtime.py` applies
the reviewed handler changes in memory and never overwrites that source file.

## Rate behavior

The lira buy/sell display handlers read their adjusted Toman↔TRY pair from the
canonical `/api/rates/try` endpoint. If the endpoint is invalid, stale, or
unavailable, the bot displays no TRY quote. The wrapper continues to read the
admin percentages for USDT and TRY/USDT conversions:

- `user_usdt_buy_adjustment_pct`
- `user_usdt_sell_adjustment_pct`
- `user_try_to_usdt_adjustment_pct`
- `user_usdt_to_try_adjustment_pct`

The bot no longer calculates Toman↔TRY buy/sell prices locally, so those values
cannot drift from the Mini App or Kiani rate posts.

## Compatibility check before activation

Place `main_user_runtime.py`, `kiani_try_api.py`, and the existing
`main_user_pricing_client.py` beside the bot runtime. Set
`MAIN_USER_BOT_SOURCE`, `KIANI_TRY_RATES_URL`, and `PRICING_DB_PATH` in the
existing secure service environment, then run `main_user_runtime.py --check`
using the same Python environment as that service.

The check must compile all expected pricing handlers. If it fails, make no
service configuration changes; review the bot source drift first.

## Activation and rollback

This repository intentionally contains no service-manager configuration.
Activate only after review and explicit approval, following the private
deployment runbook for the existing service. Preserve its current options and
environment values. For rollback, restore the previously recorded service
command and restart only after approval. The original bot source is never
modified by this integration.

