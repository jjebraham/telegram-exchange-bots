"""Small dependency-free snapshot store used before live feed ingestion.

The website can consume these JSON snapshots without importing Telegram/X
publishers. Values remain decimal strings on disk and over the future API.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Iterable


class SnapshotError(ValueError):
    pass


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


REQUIRED_QUOTE_FIELDS = {
    "quote_id", "series_id", "instrument_id", "base_asset", "base_quantity",
    "quote_currency", "unit", "quote_kind", "collected_at",
    "verification_status",
}
ALLOWED_STATUS = {"verified", "unverified", "rejected"}


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise SnapshotError(f"{field} must be an RFC3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError(f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or not value or any(ch in value for ch in "eE"):
        raise SnapshotError(f"{field} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise SnapshotError(f"{field} is not a decimal") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise SnapshotError(f"{field} must be finite and positive")
    return parsed


def validate_snapshot(payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != "1":
        raise SnapshotError("schema_version 1 is required")
    snapshot_id = payload.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise SnapshotError("snapshot_id is required")
    collected_at = _timestamp(payload.get("collected_at"), "collected_at")
    if now is not None and collected_at > now.astimezone(timezone.utc):
        raise SnapshotError("collected_at cannot be in the future")
    quotes = payload.get("quotes")
    if not isinstance(quotes, list) or not quotes:
        raise SnapshotError("quotes must be a non-empty list")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for quote in quotes:
        if not isinstance(quote, dict) or not REQUIRED_QUOTE_FIELDS.issubset(quote):
            raise SnapshotError("quote is missing required fields")
        quote_id = quote["quote_id"]
        if not isinstance(quote_id, str) or quote_id in seen:
            raise SnapshotError("quote_id values must be unique")
        seen.add(quote_id)
        status = quote["verification_status"]
        if not isinstance(status, str) or status not in ALLOWED_STATUS:
            raise SnapshotError(f"unsupported verification_status: {status}")
        _decimal(quote["base_quantity"], "base_quantity", positive=True)
        for field in ("bid", "ask", "reference", "mid"):
            if quote.get(field) is not None:
                _decimal(quote[field], field, positive=True)
        quote_collected_at = _timestamp(quote["collected_at"], "quote.collected_at")
        if now is not None and quote_collected_at > now.astimezone(timezone.utc):
            raise SnapshotError("quote.collected_at cannot be in the future")
        clean_quote = dict(quote)
        clean_quote["collected_at"] = quote_collected_at.isoformat()
        for field in ("source_observed_at", "verified_at", "valid_until"):
            if clean_quote.get(field) is not None:
                clean_quote[field] = _timestamp(clean_quote[field], f"quote.{field}").isoformat()
        normalized.append(clean_quote)
    return {**payload, "collected_at": collected_at.isoformat(), "quotes": normalized}


@dataclass
class SnapshotStore:
    root: Path

    def write(self, payload: dict[str, Any], *, now: datetime | None = None) -> Path:
        validated = validate_snapshot(payload, now=now)
        target = self.root / f"{validated['snapshot_id']}.json"
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(validated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        return target

    def latest(self) -> dict[str, Any] | None:
        files = sorted(self.root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not files:
            return None
        return validate_snapshot(json.loads(files[0].read_text(encoding="utf-8")))

