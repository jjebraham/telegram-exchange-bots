# Kiani Exchange rates on X

The X publisher uses the canonical retail TRY pair so its customer-facing lira
buy/sell values stay aligned with the Mini App and user bot.

## Rate sources

- `/api/rates/try` supplies admin-adjusted TRY buy/sell values.
- `/api/rates/current` supplies USDT and other cross rates, plus market status.

If the canonical TRY result is missing, stale, or invalid, the publisher does
not publish a rate post. It never substitutes TRY values from
`/api/rates/current`.

The rate labels retain the established customer direction:

- `buy_lira` → فروش لیر به شما
- `sell_lira` → خرید لیر از شما
- `buy_usdt` → فروش تتر به شما
- `sell_usdt` → خرید تتر از شما
- `lira_to_usdt` → لیر به تتر
- `usdt_to_lira` → تتر به لیر

## Schedule and state

All schedules use `Europe/Istanbul`. The existing four daily rate slots and
hourly 0.5% movement check remain unchanged. Posts are link-free. The workflow
compares the last successfully published rates and initializes a baseline
without posting when no state is available.

## Reliability and validation

Temporary HTTP errors and connection timeouts are retried. Invalid or stale
canonical TRY data fails closed.

The workflow requires the four existing X credentials to be configured in the
repository’s protected workflow settings. Do not commit credential values.

`workflow_dispatch` defaults to `dry_run=true`. The tests validate rendering,
Unicode weighted length, links, rate direction, and fail-closed behavior
without publishing to X.

Host-specific service and deployment instructions are kept in the private
operations runbook and are not part of this repository guide.

