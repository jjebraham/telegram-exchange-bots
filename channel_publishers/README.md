# AlanChande / Kiani Exchange channel publishers

This package is the test harness for splitting the two Telegram brands before touching the real channels.

## Brand split

### AlanChande
Informational/media channel only:
- market/reference FX rates
- bank vs Kapalicarsi comparisons
- gold / USDT / converters / change summaries
- no Kiani transaction spread in the informational posts

### Kiani Exchange
Transaction channel only:
- Kiani buy/sell prices
- remittance quotes
- special liquidity offers
- service notices

The channel IDs and bot tokens are environment variables. Nothing in this package is tied to the production channel IDs.

## Data source decision for bank-comparison posts

Prototype / test source:

- `kur.doviz.com` for one normalized table containing Kapalicarsi plus Turkish-bank buy/sell rates.
- The provider currently requests the currency page once, then extracts the requested institutions.
- It must remain low-frequency and cached in production. It is a web-page adapter, not an official bank API.

Preferred production upgrades when credentials/contracts are available:

- Ziraat: official API Portal (`/portal/exchangerates` family).
- Is Bankasi: official Exchange Rates API (client id/secret; bank states API use requires onboarding/contract).
- Kuveyt Turk: official API Market FX Currency Rates.
- Garanti BBVA: official public FX web page is available and updated frequently, but no equivalent unauthenticated public FX API was verified during this implementation.
- TCMB: use the official daily feed only as a reference benchmark, not as a substitute for retail bank buy/sell prices.

The code uses a provider interface so the `doviz.com` adapter can later be replaced bank-by-bank without changing the Telegram renderer.

## Initial commands

```bash
cd channel_publishers
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Preview only, no Telegram message:
python -m channel_publishers.main bank-comparison --currency USD --dry-run

# Send to the AlanChande TEST channel after bot/admin setup:
python -m channel_publishers.main bank-comparison --currency USD

# Preview a Kiani test card from JSON supplied in the env:
python -m channel_publishers.main kiani-rates --dry-run
```

## Safe rollout

1. Create two private/new Telegram test channels.
2. Add the corresponding bots as admins with permission to post messages.
3. Put only the TEST channel IDs in `.env`.
4. Run all publishers manually with `--dry-run`, then manually without `--dry-run`.
5. Let scheduled test posts run for several days.
6. Only after formatting, source freshness, retries and duplicate suppression are verified, replace the two channel IDs with the real production IDs.

Never commit Telegram bot tokens or API keys.