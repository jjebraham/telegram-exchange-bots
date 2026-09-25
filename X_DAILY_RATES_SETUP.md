> Current posting policy: every fixed post and movement alert is link-free and ends with «حواله روی خط واتسپ». The four daily times and hourly 0.5% movement checks below are unchanged. The `standard` manual mode replaces `linked`; legacy CLI link arguments cannot enable links. Install Node.js and run `npm ci --prefix x_text` before running the Python publisher. Every send is checked with the pinned official twitter-text validator and rejected if invalid or over 280 weighted characters. The older linked examples below describe historical behavior only.
# Kiani Exchange rates on X

This automation publishes Kiani Exchange rate updates from the official X account while avoiding repetitive hourly spam.

## Source of rates

The publisher reads:

`https://miniapp.kiani.exchange/api/rates/current`

The mini-app remains the source of truth for customer-facing rates and admin percentage/manual-rate settings.

Rate mapping used in regular posts:

- `buy_lira` -> 🇹🇷 فروش لیر به شما
- `sell_lira` -> 🇹🇷 خرید لیر از شما
- `buy_usdt` -> 🪙 فروش تتر به شما
- `sell_usdt` -> 🪙 خرید تتر از شما
- `lira_to_usdt` -> 💲 لیر به تتر
- `usdt_to_lira` -> 💲 تتر به لیر

Whole-number rates use thousands separators, for example `4,910` and `236,370`.

## Posting strategy

All schedules use `Europe/Istanbul`.

- **09:12** — morning rate post, link-free.
- **12:07** — main daily post with `https://wa.me/905411603664` and `https://miniapp.kiani.exchange`.
- **15:12** — afternoon rate update, link-free.
- **18:12** — evening rate update, link-free.
- **08:37–22:37, hourly** — check for significant movement. No X post is created unless at least one main customer-facing TRY/Toman rate has moved by **0.5% or more** versus the last successfully published rates.

The hourly alert is also link-free. The fixed link-free posts use different time-of-day headings so the account does not publish identical copy repeatedly.

## Alert state

The workflow stores the last successfully published rate snapshot in the GitHub Actions cache (`.x-rate-state/latest.json`). Scheduled rate posts and successful alerts update that state. Hourly checks compare against this last published snapshot.

If no state exists yet, an hourly alert check initializes the baseline without publishing anything.

## Reliability

The rates endpoint depends on upstream market feeds. The publisher retries temporary HTTP `429`, `500`, `502`, `503`, `504`, timeout, and connection failures up to five times before failing the run. Structurally invalid rate data is never published.

## X app configuration

The X developer app must have **Read and write** permission. GitHub Actions requires these repository secrets:

- `X_API_KEY`
- `X_API_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`

Do not commit these values to the repository.

## Manual runs

`workflow_dispatch` supports three modes:

- `linked` — the standard post with WhatsApp and mini-app links.
- `link_free` — a rate update without any URL.
- `alert_check` — compare current rates with the last published snapshot and only post when the 0.5% threshold is reached.

Manual runs default to `dry_run=true` for safety.

Local examples:

```bash
# Preview linked post
python x_daily_rates.py --dry-run

# Preview a completely link-free post
python x_daily_rates.py --dry-run --no-links --variant afternoon

# Check for a significant movement using a local state file
python x_daily_rates.py --mode alert --dry-run --state-file .x-rate-state/latest.json
```
