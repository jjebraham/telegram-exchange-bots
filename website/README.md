# AlanChande website prototype

Phase 2/3 prototype for `alanchande.com`: a Persian RTL market dashboard and a dependency-free validated snapshot foundation.

## Local preview

```bash
python3 -m http.server 8080 --directory dist
```

Open `http://localhost:8080`.

## Snapshot validation

```bash
python3 -m unittest discover -s tests -v
```

The current interface uses sample values. The `data_foundation` package is ready for a separate verified ingestion/API service. It deliberately has no Telegram/X credentials, live provider secrets, or transaction endpoints.

## Deployment

The `dist/` directory is a static prototype. Point your own host or Cloudflare Pages/Workers deployment at `dist/`. Replace the sample cards only after the verified API contract and source permissions are complete.

