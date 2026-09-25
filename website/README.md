# AlanChande market website

Persian-first, RTL market dashboard for alanchande.com. The homepage now reads
verified observations from the local AlanChande API. It never displays sample
prices as production rates.

## Local development

```bash
python3 -m http.server 8080 --directory dist
```

## Phase 3 data foundation

The `api/` service exposes verified read-only market observations and a protected snapshot-ingestion endpoint. `api/import_verified_history.py` can incrementally copy observations already recorded after successful verified Telegram posts. It opens the publisher SQLite database read-only and stores website data separately. See [Phase 3 deployment](PHASE_3_DEPLOYMENT.md).

The API does not call upstream collectors and does not send Telegram or X posts.
The Phase 4 importer also maps the verified daily digest's explicit units
(Iran FX and gold in toman, XAU and crypto in USD). An optional fresh
`ALANCHANDE_HAWALA_SNAPSHOT` imports the seven Kiani hawala rates exported
after a successful Telegram delivery. Kiani's TRY customer buy/sell and
calculator prices have no equivalent verified history export in this feed yet,
so the website does not infer them from market rates. Chart points are actual
observations; gaps are not filled.

See [Phase 4 deployment](PHASE_4_DEPLOYMENT.md). The frontend needs the API
reachable at `/api/v1/quotes` and `/api/v1/history` on the same domain.

## First trust and UI release

The current working tree includes the first Phase 5 release candidate. The
dashboard now presents a headline board, explicit rate meanings, mobile-safe
tables, relative freshness and expiry labels, and charts that break across
long gaps. Daily digest crypto rows are marked as daily digest data so they
appear in the digest view with the FX and gold rows. The publisher database
remains outside the frontend and is still read only to the website importer.

Before serving this checkout, run the Python and Node checks below, then use
the deployment notes in `PHASE_5_FIRST_RELEASE.md`. The release only changes
the website checkout; it does not restart Telegram or X publishers.

## Snapshot validation

```bash
python3 -m unittest discover -s tests -v
node --test tests/model.test.mjs
```

Money values stay decimal strings. No credentials, publisher tokens, customer transactions, or sample values are used as live quotes.


