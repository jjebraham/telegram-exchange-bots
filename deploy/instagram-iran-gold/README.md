# Iran gold: Servix supplementary verification

Daily Feed remains **10:00 Asia/Tehran (06:30 UTC)**, with its existing delayed
Story 30 minutes after successful publication. All seven prices remain mandatory.
At least two current agreeing publishers must support every displayed price.

## Servix's role

TGJU, DolarChand and Alanchand retain their existing parsing and evidence rules.
Servix adds one authenticated corroborating service, not a claim that its upstream
contributors are independent. Servix alone cannot authorize a price or post.

Two fixed HTTPS GETs use an X-API-Key header: /api/v1/assets/supported for original
observations and quality, and /api/v1/assets?codes=... for seven exact instruments.
No unbounded retries consume quota. The key is prompted privately once, verified,
then saved publisher-owned mode0600 at
~/.local/state/kiani-instagram-iran-gold/servix-api-key.
It is not placed in commands, URLs, logs, the repository or the existing Instagram
environment file. An existing private key is reused. Redirects never receive the
key. Reads are bounded; raw headers and error bodies are never logged.

### Exact observation checks

Each accepted Servix item requires:

- Exact code and explicit RLS unit; divide by ten exactly for toman.
- Available, supported, not stale, and the declared SERVIX provider identity.
- Catalog and price values/times from the same observation. A refresh between
  reads excludes that item; old quality is not attached to a new quote.
- Original timezone-aware businessTime, current Tehran day, age <=30 minutes,
  future skew <=60 seconds. HTTP/insert/catalog/source clocks never refresh it.
- Positive ordered sides; value = midPrice = (buyPrice + sellPrice)/2. Missing
  sides stay missing. Internal bid/ask spread <=1%, applying the same conservative
  pair guard already used for DolarChand.
- ACCEPTED without warnings, or the specifically reviewed RateSurf DEGRADED
  warning reporting excluded stale/outlier sources. Unknown warnings and hard
  failures are rejected. Reviewed warnings still need another agreeing publisher
  and remain visible in private audits.
- Existing price bounds, coin hierarchy and gold fineness/volume checks.

Servix always supplies its midpoint, never an ask chosen to force agreement.
Its observed gram coin had a 2.5974% spread and is excluded individually. Its
other six items can still corroborate; gram needs other agreeing publishers.
All seven final prices remain mandatory; there is no partial Instagram board.

Preserve a unique largest original-provider consensus when available; add Servix
only if it agrees with that entire cluster. A supplementary quote cannot veto
an otherwise valid original consensus. When the original providers have no unique
consensus, use the unique largest agreeing cluster across all providers: >=2
publishers, range/midpoint <=1% coins or <=0.5% gold. Equal competing clusters
block the post. Servix supports a cluster
but is never the displayed price source: select an actual supporting primary
publisher nearest the cluster median. Do not manufacture a price. A >7% move
from the last successful board still requires review.

Collections expire after three minutes and are revalidated before container
creation and final publication. Footer/caption attribute contributing services.
Underlying upstream independence and executable liquidity are not asserted.

## Install and test

The pinned runner extracts twelve small files, runs the authorized offline tests,
optionally configures the key, and collects/renders a verified live preview.
Servix must actually corroborate at least two prices for preflight and activation.
The original sources agreeing cannot disguise an untested Servix installation.

Use --setup-servix --activate. The installer checks the exact confirmed PR68
release 9c2cb58426f2c91d1b6868c732d3529b054325d9, owned file hashes, launcher,
active UTC cron, Story registration and publication database. It requires an exact
runtime/assets preview plus a NEW valid live consensus. Locks, private backups,
concurrent-edit checks and guarded rollback remain. Only the immutable gold
release, launcher and activation metadata change. Crontab, Story config, existing
Instagram credentials and publication rows are not rewritten. A later Servix
outage does not veto a valid primary consensus.

## Owner-requested one-time post

The owner requested testing and posting after the upgrade on 23 October 2026.
The extra --publish-now-on 2026-10-23 option is scoped to that current Tehran date.
It runs after preview and activation, collects fresh prices again, and does not
publish the earlier preview image.

This bypasses only the 10:00-10:15 clock window. It retains the publication lock,
once-per-day guard, source ages, collection expiry, all-seven consensus, baseline
jump check, original history, final revalidation and uncertain-publish review.
An already successful gold post today is not duplicated. Wrong date or an
unreviewed active release fails. Authorization date/mode are recorded privately.

No one-time flag is put in cron. Tomorrow stays 10:00 Tehran. No automatic late
catch-up or replacements. Gold and Stories remain protected from news deletion.
A successful Feed is discovered by the unchanged Story worker for +30 minutes.

Logs: ~/kiani-instagram-iran-gold-cron.log
Private audits/history: ~/.local/state/kiani-instagram-iran-gold/

