# AlanChande market-safety contract

Financial posts are fail-closed. A missing post is preferable to publishing a
rate that cannot be independently justified.

## Decisions

Every protected market post is evaluated as one of:

- VERIFIED — the required independent-source quorum agrees within the
  configured tolerance and all structural checks pass.
- SUSPICIOUS — the sources currently agree, but the move from the last
  accepted value is unusually large and the stronger volatility quorum is not
  available.
- BLOCKED — source quorum is insufficient, sources disagree, data is malformed
  or structurally impossible, a unit-conversion jump is detected, or another
  hard validation fails.

## Modes

MARKET_SAFETY_MODE controls publication:

- shadow — evaluate every protected post and show/audit the decision, but do
  not block test publishing. Use this while validating source coverage.
- enforce — only VERIFIED posts may be sent to Telegram.
- off — publication is not blocked. This is for diagnostics only and should
  not be used for production scheduling.

The default is shadow. Production timers must not be enabled until the required
boards can stay healthy in shadow mode and the server is explicitly switched
to enforce.

## Core rules

### Independent-source quorum

Rows are not the same as independent sources. Seven USDT exchange rows supplied
by one aggregator still count as one source family.

The safety gate requires at least two independent source families by default.
A large move versus the last accepted value requires three agreeing families
unless the market-specific rule says otherwise.

### Consensus and outliers

With three or more sources, the gate uses the median as the initial reference.
A single source outside the configured tolerance can be rejected while the
remaining independent sources continue only if quorum is still satisfied.

With only two sources, a material disagreement blocks the post because the
system cannot know which provider is wrong.

### Historical circuit breaker

Only a value from a successfully delivered VERIFIED post becomes the
last-accepted baseline.

The following never become a baseline:

- dry-runs;
- blocked posts;
- suspicious posts;
- shadow-mode posts whose safety decision was not VERIFIED;
- fetches that never reached Telegram.

A large movement from the last accepted value does not automatically mean the
market is wrong. It triggers stronger verification. If the stronger quorum
agrees, the real market move may still be published.

### Unit errors

A value approximately x10 or /10 from the last accepted value is hard-blocked.
This specifically guards against rial/toman normalization mistakes.

### Structural checks

Examples include positive finite numeric values, valid buy/sell direction,
enough two-sided USDT rows, required source rows/products, and fresh verifier
timestamps.

### No stale substitution

When live verification fails, the publisher does not republish the previous
price as if it were current.

NO CURRENT VERIFIED DATA => NO PUBLIC POST

Historical data is used only for anomaly detection and displayed 24-hour
change calculations.

## Audit database

Safety tables live in the same local SQLite database selected by
MARKET_HISTORY_DB:

- market_safety_audit — every non-dry-run safety check, decision, normalized
  source values, reference, previous accepted value, mode and published flag.
- market_safety_accepted — latest successfully published VERIFIED reference
  for each market key.
- market_safety_alert_state — deduplication/recovery state for admin alerts.

Inspect recent decisions with:

    cd /home/kianirad2020/telegram_bot_repo/channel_split
    python3 publish_channels.py --safety-status

## Admin alerts

Configure a private Telegram user/chat/channel with ALANCHANDE_ADMIN_CHAT_ID.
By default the AlanChande publisher bot sends the alert. A separate alert bot
may be supplied with ALANCHANDE_ADMIN_BOT_TOKEN.

Alert behavior:

- first BLOCKED or SUSPICIOUS decision: immediate alert;
- same unresolved reason: at most once per MARKET_SAFETY_ALERT_REPEAT_MINUTES
  (default 60);
- materially different reason: immediate new alert;
- first VERIFIED decision after an active problem: recovery alert.

Source health is monitored independently from post safety. A redundant provider
may be DEGRADED while the public post remains VERIFIED because enough other
independent providers still satisfy quorum. These source outages generate a
separate admin warning and a recovery notice when the provider returns. This
prevents a silent loss of redundancy.

Source-health checks are stored in market_source_health_audit, while
market_source_health_state keeps alert deduplication/recovery state. The
--safety-status command shows both recent post decisions and source health.

Alert delivery is independent of publication safety. Failure to deliver an
admin alert never turns a blocked rate into a publishable rate.

## Current source coverage

### Turkey FX pulse

Primary display source: Doviz/Kapalicarsi.

Independent verifier: Altinkaynak public Currency service for USD/TRY and
EUR/TRY. Verifier rows are rejected if their update timestamp exceeds
ALTINKAYNAK_MAX_AGE_MINUTES, default 90.

This board can reach VERIFIED when both source families are fresh and agree.

### Turkey gold

Primary display source: Doviz Kapalicarsi product pages.

Independent verifier: Altinkaynak public Gold service:

- PGA -> gram;
- PC -> quarter;
- PY -> half;
- PT -> full/tam.

Doviz and Altinkaynak are different retail providers, so their individual
dealer spreads are allowed to differ. The safety gate verifies their product
midpoints against each other and separately rejects a crossed or abnormally
wide spread in the Doviz quote actually displayed to users. Gram gold keeps a
tight 1.5% cross-provider midpoint limit; physical quarter/half/full coins use
a 2.5% midpoint limit because dealer premiums on physical coins are
structurally wider, while their displayed spread remains capped separately.

This board can reach VERIFIED when all required products have fresh agreeing
market-level verification and the displayed spreads pass their structural
guards.

### Turkey bank comparison

Doviz supplies the displayed rows, but each bank must be independently checked
against its own official source where available.

Current verifier coverage:

- Kapalicarsi: Altinkaynak market-level verifier;
- Is Bankasi: official Isbank rate page;
- Ziraat Bankasi: official Ziraat rate page/channel matched to the displayed row;
- Kuveyt Turk: official Kuveyt Finance Portal exchange-rates endpoint. The
  bank's own converter JavaScript consumes CurrencyCode, BuyRate and SellRate
  from this endpoint, so both displayed sides are verified independently;
- Garanti BBVA: verification is quorum-based rather than dependent on one
  fragile official web app. The official currency-converter endpoint remains
  an optional source when available. A separate external Garanti-rate family
  currently uses CanliDoviz with timestamp freshness checks. Doviz is still the
  displayed source, so Doviz plus the external family can verify the row even
  when the Garanti official app is degraded. The official source, when healthy,
  adds a third independent vote.

Third-party domains do not automatically become separate source families.
CanliDoviz is currently one conservative external family; additional sites may
be used as cross-checks without increasing quorum until upstream independence
has been established.

The complete bank board can reach VERIFIED when every displayed row has at
least two agreeing source families and all structural/historical checks pass.
For Garanti this means the displayed Doviz quote plus at least one healthy
independent Garanti-rate family. A degraded optional source generates a health
warning but does not block a row when quorum is still satisfied.

### Iran gold and coin

Primary/display source: TGJU. The collector first tries the aggregate/home table
and, if that layout is incomplete, falls back to TGJU's dedicated profile pages
for each coin, 18k gold and mesghal. Bubble values are omitted rather than
guessed when the aggregate page does not expose them.

Independent verifier family: Dolarchand public Gold & Silver page. It must
provide a parseable Last updated timestamp and all seven required Toman values:
Emami, Bahar Azadi, half, quarter, Gerami, 18K gold and mesghal. When Dolarchand
exposes separate Buy/Sell values, the verifier uses their midpoint to compare
against TGJU's single displayed market price.

RialNerkh and Arzbin are currently observational cross-checks only. Their values
are extremely close to Dolarchand, so they are not counted as additional
independent families until upstream independence has been demonstrated.

The board can reach VERIFIED when TGJU and Dolarchand are fresh and agree within
the Iran-gold tolerance. If the external family is stale, malformed, missing a
required row, or materially disagrees, the board remains BLOCKED.

### Iran USDT comparison

The hybrid board tracks source families separately and reports health for each
direct provider plus TGJU and Ramzarz:

- each direct exchange API is independent;
- TGJU is one aggregator family regardless of how many rows it supplies;
- Ramzarz is one aggregator family;
- a mixed TGJU+Ramzarz row does not invent a third family.

The public board also displays the independent-source-family count.

## Recommended rollout

1. Keep the server environment pointed at the test channel.
2. Use MARKET_SAFETY_MODE=shadow.
3. Run the full test suite.
4. Preview alanchande-daily with dry-run and inspect safety decisions.
5. Run real test-channel shadow posts so audit and admin alerts execute.
6. Add and validate remaining independent sources for bank rows and Iran gold.
7. Observe several clean shadow cycles.
8. Switch to MARKET_SAFETY_MODE=enforce.
9. Keep failure injection inside tests, never on the production channel.
10. Only then configure the production channel and timers.
