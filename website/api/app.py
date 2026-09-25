"""Public read-only market API and authenticated snapshot ingestion endpoint."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hmac
import os

from fastapi import FastAPI, Header, HTTPException, Query, Request

from data_foundation.snapshot import SnapshotError
from api import store

app = FastAPI(title="AlanChande Market API", version="1.0.0")


@app.on_event("startup")
def startup() -> None:
    store.initialize()


@app.get("/healthz")
def health() -> dict:
    return store.health()


@app.get("/api/v1/markets")
def markets() -> dict:
    return {"schema_version": "1", "markets": store.available_markets()}


@app.get("/api/v1/quotes")
def quotes(instrument_ids: str | None = None) -> dict:
    requested = [part.strip() for part in (instrument_ids or "").split(",") if part.strip()]
    if len(requested) > 100:
        raise HTTPException(status_code=422, detail="at most 100 instrument IDs are allowed")
    ttl = int(os.environ.get("ALANCHANDE_STALE_AFTER_SECONDS", "3600"))
    values = store.latest_quotes(requested or None, stale_after_seconds=max(60, ttl))
    returned_ids = {quote["instrument_id"] for quote in values}
    missing_requested = bool(requested and set(requested) - returned_ids)
    return {
        "schema_version": "1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "partial": not values or missing_requested or any(q.get("freshness_status") != "fresh" for q in values),
        "quotes": values,
    }


@app.get("/api/v1/instruments/{instrument_id}")
def instrument(instrument_id: str) -> dict:
    values = store.latest_quotes([instrument_id])
    if not values:
        raise HTTPException(status_code=404, detail="instrument has no verified observations")
    quote = values[0]
    return {
        "instrument_id": instrument_id,
        "display_name_fa": quote.get("display_name_fa", instrument_id),
        "category": quote.get("category", "other"),
        "base_asset": quote["base_asset"],
        "quote_currency": quote["quote_currency"],
        "unit": quote["unit"],
        "series": sorted({q["series_id"] for q in values}),
    }


@app.get("/api/v1/history")
def quote_history(
    series_id: str,
    start: datetime = Query(alias="from"),
    end: datetime = Query(alias="to"),
    limit: int = Query(default=2000, ge=1, le=2000),
) -> dict:
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise HTTPException(status_code=422, detail="from/to must be ordered timezone-aware timestamps")
    if end - start > timedelta(days=366 * 5):
        raise HTTPException(status_code=422, detail="history range is limited to five years")
    return store.history(series_id, start, end, limit)


@app.post("/api/v1/ingest")
async def ingest(request: Request, authorization: str | None = Header(default=None)) -> dict:
    expected = os.environ.get("ALANCHANDE_INGEST_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="snapshot ingestion is not configured")
    parts = (authorization or "").split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="unauthorized")
    supplied = parts[1]
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="unauthorized")
    if int(request.headers.get("content-length", "0") or 0) > 2_000_000:
        raise HTTPException(status_code=413, detail="snapshot payload is too large")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON payload") from exc
    try:
        snapshots = payload if isinstance(payload, list) else [payload]
        result = store.ingest_snapshots(snapshots)
    except (ValueError, SnapshotError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "accepted", **result}

