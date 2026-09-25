# AlanChande market website

Persian-first, RTL market dashboard for alanchande.com. The current dashboard is a visual prototype; it still labels its displayed prices as sample data.

## Local preview

```bash
python3 -m http.server 8080 --directory dist
```

## Phase 3 data foundation

The `api/` service exposes verified read-only market observations and a protected snapshot-ingestion endpoint. `api/import_verified_history.py` can incrementally copy observations already recorded after successful verified Telegram posts. It opens the publisher SQLite database read-only and stores website data separately. See [Phase 3 deployment](PHASE_3_DEPLOYMENT.md).

The API does not call upstream collectors and does not send Telegram or X posts. Current history covers only instrument families with verified publisher records. Points are not interpolated into candles. Connect all page widgets to this API and expand instrument coverage in Phase 4.

## Snapshot validation

```bash
python3 -m unittest discover -s tests -v
```

Money values stay decimal strings. No credentials, publisher tokens, customer transactions, or sample values are used as live quotes.

