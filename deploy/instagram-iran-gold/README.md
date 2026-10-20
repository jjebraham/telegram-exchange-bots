# Iran gold and coin daily board

User-approved schedule: **10:00 Asia/Tehran daily (06:30 UTC)**. One 1080x1350
Feed image; the existing worker sends a Story preview 30 minutes after Feed
success. No late catch-up and no post when a check fails. Saturday's separate
economic calendar may also publish at10:00; that existing job is retained.

## Mandatory current-price checks

Every run collects all seven instruments from two separate source feeds:
TGJU and DolarChand. There is no AI-created price, manual fallback, stale-cache
fallback, partial board, or fallback to the approved example numbers.

1. Fetch TGJU's dedicated profile for each exact instrument. Require explicit
   rial currency and correct volume unit, the current-quote table and its
   source quote clock. Fetch its public dated summary record as well. Current
   price must match the latest dated record exactly; its Gregorian and Persian
   source dates must agree and equal the current Tehran date. Bind the quote
   clock to that dated record using Asia/Tehran. A page fetch time, server clock,
   or date-only old price never qualifies as a current quote timestamp.
2. Fetch DolarChand's gold page. Check its server-rendered ISO snapshot time
   against its visible time, and structured buy/sell prices against all seven
   visible instrument rows. Require its explicit toman declaration. This is
   the provider's snapshot timestamp, not a claim about each individual trade.
   The two feeds are treated as separate verifiers; the integration cannot
   establish whether every upstream contributor is independent.
3. Each source quote/snapshot must be from the current Tehran day and no more
   than30minutes old; allow at most60seconds of future clock skew. Both feeds
   must contain all seven exact assets. The complete collection expires after
   3minutes and is checked again immediately before the final Meta publish call.
4. Convert TGJU rial to toman exactly by dividing by10, with integral toman
   output; check currency/volume units, positive finite prices and conservative
   per-asset bounds calibrated for the October2026 price scale (each range spans
   less than a factor10). Both-feed x10 and /10 mistakes are rejected even on the
   first publication. These bounds need explicit review if the market moves
   outside them. No multiplying/dividing by10 to make a disagreement fit.
5. Reject crossed or >1% wide DolarChand bid/ask pairs. Compare TGJU market price
   with DolarChand midpoint: full spread/mean must be<=1% for coins and<=0.5% for
   18K/mesghal. Publish the checked TGJU price, not an invented average.
6. Check whole coins > half > quarter > gram coin, and bazaar-mesghal/18K-gram
   price ratio in4.28–4.38. This is a unit/coherence check: Iranian bazaar mesghal
   uses fineness705; 18K gram uses750. It does not claim mesghal physically
   weighs4.33grams. Reference: https://www.tgju.org/gold-chart
7. A >7% move from the last successfully published board blocks the whole post
   for manual review, even if the move might be legitimate. No automatic
   threshold widening or rebasing. First publication still requires all other
   checks and conservative bounds.

These checks reduce publication errors; agreement between websites is not an
absolute guarantee of market correctness. If sources are stale or unavailable
at10:00, the intended outcome is **no post that day**. Closed-market days may be
skipped normally. Prices are informational market quotes, not Kiani buy/sell offers.

## Changes and history

Use a separate private SQLite database:
`~/.local/state/kiani-instagram-iran-gold/gold.sqlite3`.
The existing Telegram source code, history and jobs are not modified.
Only successful Instagram gold publications advance the baseline/history.
The24h comparison requires a previous publication within1hour of24h; the1month
comparison is defined as30days with at most3hours difference. Missing verified
history displays `—`, not0% or numbers copied from an example. Expect missing
monthly changes until sufficient publication history exists. Source website
daily/monthly percentages are not reused without this history.

Private source audit records source dates, clocks, units, content hashes,
disagreements and rejection reasons. Failed current quotes never create a public
publication image or alter publication history. The footer displays the oldest
source time and explicitly labels Tehran. Vazirmatn, Kiani logo, Persian/Gregorian
dates and deterministic Pillow rendering match the approved template. No new
translation/image API is used by the scheduled job.

## Publication and deployment

One daily unique publication record plus a lock prevent duplicates. Uncertain
final API requests remain `needs_review` and are never blindly retried. Only
10:00–10:15 Tehran allows the final publish step. No broad retry schedule.

The pinned `run_gold.py` extracts eleven small files, with no full checkout or
new venv. Default mode performs a live source preflight and renders a preview
only if every check passes; there is no Meta API contact. If only freshness
checks fail, it records an explicit blocked preflight and prints the reasons.
Schema, missing-source, disagreement and other failures return a nonzero status.

`--activate` reruns the offline guard tests and requires a recent preflight from
the same runtime/assets. A preflight blocked solely for stale/date-only source
quotes may install the guarded schedule: it cannot authorize any future prices
or bypass runtime checks. This allows installation outside market hours without
presenting old quotes as current. All other preflight failures refuse activation.
Normal verified preflights must still be fresh at activation.

The installer requires UTC cron and the previously deployed PR64 Story files,
backs up launcher/config/worker/crontab and adds only the optional `iran_gold`
Story source/label. All existing daily and weekly jobs, databases and queued
Stories remain. Installation publishes nothing immediately. Public images use
`instagram-rates/iran-gold/`; verified previews use`iran-gold-preview/`.
Log: `~/kiani-instagram-iran-gold-cron.log`.

The offline suite exercises valid boards, both source parsers, stale/future
dates, missing assets, crossed pairs, rial/toman errors, inconsistent units and
ratios, source disagreement, large jumps, fabricated comparisons, duplicate
guards, expired collections and the Tehran posting window. Synthetic test data
is never accepted by the production publishing path.
