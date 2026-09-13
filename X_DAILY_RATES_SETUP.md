# Daily Kiani Exchange rates on X

This automation publishes one Kiani Exchange rate post per day from the official X account.

## Source of rates

The publisher does **not** maintain a second copy of the pricing percentages. It reads:

`https://miniapp.kiani.exchange/api/rates/current`

That endpoint is backed by the same Kiani mini-app pricing logic (`derive_rates`) and current admin settings, so the X post follows the rates shown by the production mini-app instead of drifting from it.

Rate mapping used in the post:

- `buy_lira` -> فروش لیر به شما
- `sell_lira` -> خرید لیر از شما
- `buy_usdt` -> فروش تتر به شما
- `sell_usdt` -> خرید تتر از شما
- `lira_to_usdt` -> لیر به تتر
- `usdt_to_lira` -> تتر به لیر

## Schedule

GitHub Actions runs the workflow every day at **12:00 Türkiye time** (`09:00 UTC`). A manual `workflow_dispatch` is also available. Manual runs default to dry-run mode so the generated text can be checked without spending X API credits or creating a post.

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

To preview the cheaper version without the mini-app URL:

```bash
python x_daily_rates.py --dry-run --no-link
```

The production scheduled workflow currently includes `https://miniapp.kiani.exchange` at the end of every post.
