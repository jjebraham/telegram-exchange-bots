# Weekly global-market risk dashboard — free-data edition

Owner-selected slot: **Sunday 18:00 Asia/Tehran (14:30 UTC)**. One successful six-slide Feed per reporting week, then one cover Story through the existing worker, 30 minutes after success. Bounded publication attempts at 18:00, 18:05 and 18:10; no late catch-up. This is a separate protected non-news series.

## Approved changes from the example

The owner chose free sources and explicitly approved a clearly labelled alternative basket. It contains **seven** indicators, not the example's seven plus credit spread. Brent is EIA Europe Brent **spot**, dollar is the Fed's **nominal broad dollar** index, and financial stress is **STLFSI4**. They are not ICE Brent futures, DXY or high-yield OAS. S&P 500 is omitted: the FRED series notice requires prior written permission for reproduction. No subscription, secret or permission is invented. VIX and STLFSI4 retain source attribution.

There is **no proprietary 0–100 Kiani score, crisis probability, automatic crisis diagnosis, investment recommendation or price-derived causal narrative**. The final slide describes whether the published STLFSI4 observation is above/below its historical zero average. This is not a guarantee of safety or a live assessment of all markets.

## Inputs and verification

| Input | Exact definition | Checked delivery routes | Maximum lag from report Friday |
|---|---|---|---|
| Gold | USD/troy ounce, captured near Friday 17:00 New York | Servix GOLD_OUNCE_USD + Alanchand/DolarChand | Same Friday |
| Bitcoin | BTC/USD, captured in the same fixed window | Servix BTC_USD + CoinPaprika btc-bitcoin USD | Same Friday |
| Brent | EIA Europe Brent spot FOB USD/barrel | EIA daily table + FRED DCOILBRENTEU | 7 calendar days |
| VIX | Cboe cash VIX daily close | Cboe historical CSV + FRED VIXCLS | 4 days |
| Dollar | Fed nominal broad dollar, Jan 2006=100 | Fed H.10 daily historical table + FRED DTWEXBGS | 10 days |
| Ten-year yield | Fed H.15 daily 10-year constant-maturity yield on investment basis, percent | Fed H.15 RIFLGFCY10_N.B CSV + FRED DGS10 | 4 days |
| Financial stress | St. Louis Fed STLFSI4, weekly ending Friday | FRED table + FRED CSV, four-decimal agreement | 14 days |

Official series have one originating calculation. Mirrors are delivery checks, not independent index calculations. **STLFSI4 uses two formats from the same publisher**, an internal consistency check rather than independent corroboration; the caption says this explicitly. Yield verification uses the same H.15 definition in both routes, not a different Treasury curve or intraday note quote. Disagreement blocks the latest common date instead of being averaged or hidden with an older agreeing observation. Original methods/dates remain in the audit. H.15 uses the published preformatted constant-maturity package; if the Fed retires that delivery route it must be replaced by a qualified equivalent, not silently bypassed.

The latest mutually available date is selected separately for each official series. Every displayed change compares that date to **exactly seven days earlier**. Dates and source lags are disclosed on slides and caption. These are not synchronized Friday-close market returns. A missing seven-day observation (including a holiday), excessive release lag, malformed response or latest common-date conflict holds the whole post. No forward fill, made-up history or fabricated timestamp.

Gold/BTC require a unique agreeing cluster, Servix plus at least one publisher, maximum 0.5% spread and ten-minute source-time skew. Their original timestamps must be within the reviewed Friday 17:00 New York reference window. Capture attempts at 17:00, 17:05 and 17:10; the timezone handles US DST. Later current quotes never backfill a historical close. Captured endpoints are immutable. This policy is separate from the existing daily Iran-gold freshness policy.

If installed on 25 October 2026, the first possible capture is 30 October, the first paired capture is 6 November, and the **earliest full post is Sunday 8 November**, provided all sources qualify. Missing data can delay that date. No old screenshot or illustrative number enters production.

## Preview and install

Use a reviewed commit from this PR. Fetch that exact PR head, compare its SHA, and extract only `deploy/instagram-risk/run_risk.py`. Then use the existing publisher user and Python:

1. `python3 RUN --repo "$HOME/telegram_bot_repo" --revision SHA --layout-preview`: six conspicuously fictional design slides, no Meta contact. Review the returned public image links.
2. `python3 RUN --repo "$HOME/telegram_bot_repo" --revision SHA`: live source and current spot-format/quality probe, no Meta contact. Current quotes are never historical baselines. The private Servix key is reused locally; no key prompt, rotation or echo.
3. `python3 RUN --repo "$HOME/telegram_bot_repo" --revision SHA --activate`: repeats the source preflight, then installs only after fresh proof and matching layout/assets proof. Installation publishes/deletes nothing.

No package installation, repository checkout, new test suite or credential change. The installer requires the confirmed PR75 analytics and PR77 readable-news versions, validates exact existing files and metadata, clones them with the new category only, preserves the 64px renderer and all policy state, adds the Story source, creates a private backup and appends a delimited cron block. Changed configuration is protected by worker locks, concurrent-change checks and guarded rollback. Existing rates, gold/metals, gainers/top50, calendars, weekly returns, queued Stories and retention decisions are preserved.

## Runtime and operational checks

- Worker: `~/publish-kiani-instagram-risk.sh status`
- Log: `~/kiani-instagram-risk-cron.log`
- State: `~/.local/state/kiani-instagram-risk-thermometer/`
- Private audits: `runs/*/source.json`, `preflight.json`, `capture.json`, `manifest.json`, and bounded original response bodies.
- Publication DB: `risk.sqlite3`, compatible `instagram_news_publications` records. Parent carousel ID, not child IDs, enters analytics and Story discovery. The strict crypto/economy-only deletion rule does not apply to this kind.
- Each source response is bounded at 2 MB, fixed HTTPS targets only, no redirects, key only to two Servix endpoints. Private evidence is hashed and reparsed; public JPEGs have content hashes. No keys, response payloads or Meta error bodies are printed.
- Live quota/account/usage checks reuse the existing core and pending-Story reservations. Six carousel children plus one parent publish are one Feed publication, then one Story; API calls still consume their own usage budget.
- Final source, image, account, time-window and quota checks precede publication. A timed-out/uncertain final request becomes `needs_review`, which blocks blind retries. No automatic deletion, replacement posting or historical enrollment.

## Readiness evidence and remaining deployment work

The developer machine successfully fetched and parsed all public routes. Matched examples as of 25 October: Brent 20 Oct 115.22 (prior 13 Oct 125.78), broad dollar 16 Oct 121.4048 (prior 9 Oct 121.6023), VIX 22 Oct 19.03 (prior 15 Oct 16.46), ten-year yield 22 Oct 4.96% (prior 15 Oct 5.10%), STLFSI4 16 Oct -0.6328 (prior 9 Oct -0.7205). These are read-only qualification results, not publication candidates or gold/BTC history.

Syntax and six-slide visual rendering were checked. No automated tests were added or run. **Selenium connectivity, authenticated gold/BTC preflight, installation, first Friday captures, actual Feed publication and subsequent Story delivery remain unconfirmed until their server outputs are reviewed.** No production activation is implied by this PR.

Primary definitions and source terms:

- https://www.eia.gov/dnav/pet/hist/RBRTED.htm
- https://fred.stlouisfed.org/series/DCOILBRENTEU
- https://www.federalreserve.gov/releases/h10/summary/
- https://fred.stlouisfed.org/series/DTWEXBGS
- https://www.cboe.com/tradable-products/vix/vix-historical-data
- https://fred.stlouisfed.org/series/VIXCLS
- https://www.federalreserve.gov/datadownload/Choose.aspx?rel=H15
- https://fred.stlouisfed.org/series/DGS10
- https://fred.stlouisfed.org/series/STLFSI4
- https://fred.stlouisfed.org/series/SP500
- https://fred.stlouisfed.org/series/BAMLH0A0HYM2
- https://servix.cc/docs/supported-assets
