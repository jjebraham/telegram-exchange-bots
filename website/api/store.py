"""SQLite-backed, append-only storage for validated website snapshots."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from data_foundation.snapshot import SnapshotError, validate_snapshot


def database_path() -> Path:
    configured = os.environ.get("ALANCHANDE_DB_PATH", "").strip()
    return Path(configured) if configured else Path(__file__).resolve().parent.parent / "var" / "market.sqlite3"


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 15000")
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA foreign_keys = ON")
    return db


def connect_readonly() -> sqlite3.Connection:
    path = database_path()
    if not path.is_file():
        raise FileNotFoundError("website market database has not been initialized")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only = ON")
    db.execute("PRAGMA busy_timeout = 15000")
    return db


def initialize() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id TEXT NOT NULL UNIQUE,
                collected_at TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS snapshots_time_idx
                ON snapshots(collected_at, id);
            CREATE TABLE IF NOT EXISTS quotes (
                snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
                quote_id TEXT NOT NULL,
                series_id TEXT NOT NULL,
                instrument_id TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                category TEXT NOT NULL,
                display_name_fa TEXT NOT NULL,
                quote_json TEXT NOT NULL,
                PRIMARY KEY(snapshot_id, quote_id)
            );
            CREATE INDEX IF NOT EXISTS quotes_series_time_idx
                ON quotes(series_id, collected_at);
            CREATE INDEX IF NOT EXISTS quotes_instrument_time_idx
                ON quotes(instrument_id, collected_at);
            CREATE TABLE IF NOT EXISTS import_cursors (
                source_name TEXT PRIMARY KEY,
                last_row_id INTEGER NOT NULL
            );
            """
        )


def _canonical(payload: dict[str, Any]) -> tuple[str, str]:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def ingest_snapshots(
    payloads: Iterable[dict[str, Any]],
    *,
    cursors: dict[str, int] | None = None,
) -> dict[str, int]:
    """Validate a complete batch before committing any rows or import cursors."""
    prepared: list[tuple[dict[str, Any], str, str]] = []
    now = datetime.now(timezone.utc)
    for payload in payloads:
        normalized = validate_snapshot(payload, now=now)
        encoded, digest = _canonical(normalized)
        prepared.append((normalized, encoded, digest))

    initialize()
    inserted = 0
    existing = 0
    with connect() as db:
        for payload, encoded, digest in prepared:
            snapshot_id = payload["snapshot_id"]
            row = db.execute(
                "SELECT payload_hash FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if row:
                if row["payload_hash"] != digest:
                    raise SnapshotError("snapshot_id already exists with different content")
                existing += 1
                continue
            db.execute(
                "INSERT INTO snapshots(snapshot_id, collected_at, payload_hash, payload_json) VALUES (?, ?, ?, ?)",
                (snapshot_id, payload["collected_at"], digest, encoded),
            )
            for quote in payload["quotes"]:
                db.execute(
                    """INSERT INTO quotes(
                        snapshot_id, quote_id, series_id, instrument_id, collected_at,
                        verification_status, category, display_name_fa, quote_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot_id,
                        quote["quote_id"],
                        quote["series_id"],
                        quote["instrument_id"],
                        quote["collected_at"],
                        quote["verification_status"],
                        str(quote.get("category", "other")),
                        str(quote.get("display_name_fa", quote["instrument_id"])),
                        json.dumps(quote, ensure_ascii=False, sort_keys=True),
                    ),
                )
            inserted += 1
        for source, row_id in (cursors or {}).items():
            db.execute(
                """INSERT INTO import_cursors(source_name, last_row_id) VALUES (?, ?)
                   ON CONFLICT(source_name) DO UPDATE SET last_row_id = MAX(last_row_id, excluded.last_row_id)""",
                (source, int(row_id)),
            )
    return {"inserted_snapshots": inserted, "already_present": existing, "quotes": sum(len(p[0]["quotes"]) for p in prepared)}


def latest_quotes(
    instrument_ids: list[str] | None = None,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 3600,
) -> list[dict[str, Any]]:
    filters = ["q.verification_status = 'verified'"]
    params: list[Any] = []
    if instrument_ids:
        filters.append("q.instrument_id IN (" + ",".join("?" for _ in instrument_ids) + ")")
        params.extend(instrument_ids)
    query = f"""
        SELECT q.quote_json FROM quotes q
        JOIN snapshots s ON s.snapshot_id = q.snapshot_id
        WHERE {' AND '.join(filters)}
        ORDER BY q.collected_at DESC, s.id DESC
    """
    with connect_readonly() as db:
        rows = db.execute(query, params).fetchall()
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    for row in rows:
        quote = json.loads(row["quote_json"])
        series_id = quote["series_id"]
        if series_id in seen:
            continue
        seen.add(series_id)
        collected = datetime.fromisoformat(quote["collected_at"].replace("Z", "+00:00"))
        valid_until = quote.get("valid_until")
        expiry = (
            datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
            if isinstance(valid_until, str)
            else collected + timedelta(seconds=stale_after_seconds)
        )
        quote["freshness_status"] = "fresh" if current <= expiry else "stale"
        result.append(quote)
    return result


def available_markets() -> list[dict[str, Any]]:
    with connect_readonly() as db:
        rows = db.execute(
            """SELECT DISTINCT category, instrument_id, display_name_fa
               FROM quotes WHERE verification_status = 'verified'
               ORDER BY category, instrument_id"""
        ).fetchall()
    return [dict(row) for row in rows]


def history(series_id: str, start: datetime, end: datetime, limit: int) -> dict[str, Any]:
    start_utc = start.astimezone(timezone.utc).isoformat()
    end_utc = end.astimezone(timezone.utc).isoformat()
    with connect_readonly() as db:
        total = db.execute(
            """SELECT COUNT(*) FROM quotes WHERE series_id = ? AND verification_status = 'verified'
               AND collected_at >= ? AND collected_at <= ?""",
            (series_id, start_utc, end_utc),
        ).fetchone()[0]
        rows = db.execute(
            """SELECT quote_json, snapshot_id FROM (
                   SELECT q.quote_json, q.snapshot_id, q.collected_at, s.id AS snapshot_order
                   FROM quotes q JOIN snapshots s ON s.snapshot_id = q.snapshot_id
                   WHERE q.series_id = ? AND q.verification_status = 'verified'
                     AND q.collected_at >= ? AND q.collected_at <= ?
                   ORDER BY q.collected_at DESC, s.id DESC LIMIT ?
               ) ORDER BY collected_at ASC, snapshot_order ASC""",
            (series_id, start_utc, end_utc, limit),
        ).fetchall()
    points = [
        {"snapshot_id": row["snapshot_id"], "quote": json.loads(row["quote_json"])}
        for row in rows
    ]
    return {
        "series_id": series_id,
        "requested_from": start_utc,
        "requested_to": end_utc,
        "available_from": points[0]["quote"]["collected_at"] if points else None,
        "available_to": points[-1]["quote"]["collected_at"] if points else None,
        "observation_count": total,
        "returned_point_count": len(points),
        "sampling_kind": "verified_publisher_observations",
        "expected_cadence_seconds": None,
        "known_gaps": None,
        "points": points,
    }


def health() -> dict[str, Any]:
    if not database_path().is_file():
        return {
            "status": "waiting_for_verified_data",
            "latest_collected_at": None,
            "latest_snapshot_id": None,
            "verified_quote_observations": 0,
        }
    with connect_readonly() as db:
        row = db.execute(
            "SELECT collected_at, snapshot_id FROM snapshots ORDER BY collected_at DESC, id DESC LIMIT 1"
        ).fetchone()
        count = db.execute("SELECT COUNT(*) FROM quotes WHERE verification_status = 'verified'").fetchone()[0]
    return {
        "status": "ready" if row else "waiting_for_verified_data",
        "latest_collected_at": row["collected_at"] if row else None,
        "latest_snapshot_id": row["snapshot_id"] if row else None,
        "verified_quote_observations": count,
    }

