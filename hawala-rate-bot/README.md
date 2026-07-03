# Kiani Hawala Rate Bot

Standalone Telegram rate poster, intentionally isolated from the existing production bot.

Schedule: once per hour at minute 45, from 09:00 through 21:59 Asia/Tehran time.

Sources:
- Nobitex USDT/RLS primary
- Wallex USDT/RLS fallback
- Gate.io USDT/USD primary
- Kraken USDT/USD fallback
- CurrencyAPI USD fiat crosses with a six-hour cache

Pricing:
- TRY uses a 0.94 payout factor
- Other configured currencies use a 0.98 payout factor
- Results are rounded to the nearest 100 Toman with ROUND_HALF_EVEN

Required environment variables:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHANNEL_ID
- CURRENCYAPI_KEYS

Optional environment variables:
- ADMIN_CHAT_ID
- WALLEX_API_KEY
- PROXY_URL
- HAWALA_BASE_DIR
- DRY_RUN
- HAWALA_CTA

Copy .env.example to .env locally. Never commit .env.

Install dependencies from requirements.txt, compile hawala_bot.py, test with DRY_RUN=true, and then run it under your preferred process manager.
