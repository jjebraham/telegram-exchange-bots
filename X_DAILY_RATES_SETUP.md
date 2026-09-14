# Daily Kiani Exchange rates on X

This automation publishes one Kiani Exchange rate post per day from the official X account.

## Source of rates

The publisher does **not** maintain a second copy of the pricing percentages. It reads:

`https://miniapp.kiani.exchange/api/rates/current`

That endpoint is backed by the same Kiani mini-app pricing logic (`derive_rates`) and current admin settings, so the X post follows the rates shown by the production mini-app instead of drifting from it.

Rate mapping used in the post:

- `buy_lira` -> 🇹🇷 فروش لیر به شما
- `sell_lira` -> 🇹🇷 خرید لیر از شما
- `buy_usdt` -> 🪙 فروش تتر به شما
- `sell_usdt` -> 🪙 خرید تتر از شما
- `lira_to_usdt` -> 💲 لیر به تتر
- `usdt_to_lira` -> 💲 تتر به لیر

Whole-number rates are formatted with thousands separators, for example `4,910` and `236,370`. The contact line links directly to WhatsApp at `https://wa.me/905411603664`, and the production post also includes `https://miniapp.kiani.exchange`.

The publisher retries transient rate-source failures (HTTP 429/5xx, timeouts, connection errors) up to five times with a short delay. It does not publish stale or incomplete rates.

## Schedule

GitHub Actions runs the workflow every day at **12:07 Türkiye time** using the explicit `Europe/Istanbul` timezone. The non-zero minute avoids the top-of-hour period where scheduled GitHub Actions jobs can experience heavier queueing. A manual `workflow_dispatch` is also available. Manual runs default to dry-run mode so the generated text can be checked without creating a post.

## X app configuration

The X developer app must have **Read and write** permission. Generate/regenerate OAuth 1.0a user Access Token credentials after enabling write permission.

Add these GitHub Actions repository secrets:

- `X_API_KEY`
- `X_API_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`

Do not commit any of these values to the repository.

## Manual preview

Run locally without publishing:

```bash
python x_daily_rates.py --dry-run
```

To omit only the mini-app URL from a preview:

```bash
python x_daily_rates.py --dry-run --no-link
```

The WhatsApp URL remains in the post even when `--no-link` is used. The production scheduled workflow includes both the WhatsApp link and `https://miniapp.kiani.exchange`.
