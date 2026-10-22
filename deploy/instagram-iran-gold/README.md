# Daily Iran gold board: multiple source consensus

Daily Feed: **10:00 Asia/Tehran (06:30 UTC)**. One board with seven prices;
a Story follows a successful Feed 30 minutes later. The source upgrade preserves
that schedule, the existing Story registration and the publication database.

## Providers and evidence

The runtime polls three separate publishers, not three URLs for one publisher:

- **TGJU:** dedicated instrument profiles, explicit rial/volume units, quote
  clocks, and dated summary records with matching Persian/Gregorian dates.
- **DolarChand:** visible toman buy/sell values must match structured quotes;
  its original ISO board timestamp must match the displayed board clock.
- **Alanchand:** the original Persian date, weekday and board update clock;
  exact named instrument rows in the market-price column; visible toman prices
  must equal the structured IRR offers divided by ten. The intrinsic-value and
  bubble columns are excluded. Offer expiry verifies timezone/date only and
  never serves as the update timestamp.

The last two publish board snapshot timestamps, not individual trade times.
Provider agreement reduces errors but cannot prove their upstream contributors
are independent or guarantee that any price is executable. Known TGJU mirrors
are not additional votes. Providers without verifiable timestamps/units were
not added just to increase the source count.

## Per-price consensus

For **each of seven instruments**, require at least two usable current providers.
A stale/unavailable third provider no longer vetoes the other two. A failed TGJU
instrument is isolated; its other valid instruments can still contribute.

1. Original source timestamps must belong to the current Tehran day and be no
   older than 30 minutes, with at most 60 seconds of future skew. Retrieval time
   never refreshes an old source timestamp. The whole collection expires after
   three minutes and is revalidated immediately before final publication.
2. Normalize rial/toman exactly, without guessing units or multiplying values
   to make them agree. Require positive finite numbers and existing conservative
   per-instrument bounds. DolarChand bid/ask must not cross or exceed 1% width.
3. Build pairwise agreeing clusters: full range divided by midpoint <=1% for
   coins and <=0.5% for 18K gram / bazaar mesghal. Select the unique largest
   cluster with at least two providers. Equal-size competing clusters block
   the board; a transitive chain of disagreements is not a consensus.
4. Choose the actual supporting quote nearest the cluster median, breaking
   exact ties by provider name. Do not average incompatible quotes or invent a
   market quote. Fractional midpoint quotes round half-up to integral toman.
5. Validate source-board and final-board coin ordering and gold fineness/volume
   ratios. Bazaar mesghal / 18K gram must remain in 4.28–4.38. A >7% move against
   the last successful board still requires manual review; there is no automatic
   rebasing or widening of limits.

All seven instruments are mandatory. A missing/ambiguous consensus for even one
skips the entire post. This improves availability when one provider fails; it
cannot guarantee a post if the market has no two fresh agreeing sources at 10:00.
No stale fallback, partial board, sample prices or late catch-up is introduced.

Private audits and logs retain each provider's health, original timestamp, units,
content hashes, supporters and rejected quotes. The footer/caption list the
actual contributing publishers and the oldest accepted source time. Failed or
outlier quotes do not determine that displayed time.

## History and publication

State remains `~/.local/state/kiani-instagram-iran-gold/gold.sqlite3`.
Only successful Feed publications advance price history. Missing valid 24-hour
or 30-day publication comparisons show an em dash. The daily duplicate guard,
publication lock, uncertain-publish review state and final 10:00–10:15 Tehran
window are retained. Gold remains protected from news-retention deletion.
No translation, AI image or price-generation API is introduced.

## Guarded upgrade from confirmed PR65

`run_gold.py` extracts ten small files from the pinned revision, without a full
checkout or new virtual environment. Default mode performs public source reads
and renders only a fully verified board. It does not contact Meta or change jobs.

`--activate` calls `upgrade_sources.py`. It requires the confirmed gold launcher,
installed source hashes, existing UTC gold cron, Story registration, a verified
preview from the exact runtime/assets within 24 hours, and a NEW fully valid live
consensus at activation. A stale or disagreeing preflight cannot authorize the
upgrade. It parses source syntax without automatically executing unit tests.

Only the versioned gold runtime, gold launcher and gold activation metadata are
written. Crontab and Story configuration are checked for concurrent changes and
never rewritten. A private backup and guarded rollback cover the launcher and
metadata. Original publication rows and all other publishers are preserved.
Installation publishes nothing immediately.

Log: `~/kiani-instagram-iran-gold-cron.log`.
Audits: `~/.local/state/kiani-instagram-iran-gold/runs/`.
Images: `instagram-rates/iran-gold/`; previews: `iran-gold-preview/`.
