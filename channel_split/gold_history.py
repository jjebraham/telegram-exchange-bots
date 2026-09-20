#!/usr/bin/env python3
"""Local history for Turkish gold quotes used by AlanChande."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS turkey_gold_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at_utc TEXT NOT NULL,
            asset_key TEXT NOT NULL,
            buy TEXT NOT NULL,
            sell TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_turkey_gold_time "
        "ON turkey_gold_snapshots(recorded_at_utc, id)"
    )
    return connection


def record_turkey_gold_quotes(
    db_path: Path,
    quotes: list[Any],
    *,
    now: datetime | None = None,
) -> str:
    if not quotes:
        raise ValueError("No Turkish gold quotes supplied")

    local_now = now.astimezone(ISTANBUL_TZ) if now else datetime.now(ISTANBUL_TZ)
    recorded_at_utc = local_now.astimezone(timezone.utc).isoformat(timespec="seconds")

    with _connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO turkey_gold_snapshots (
                recorded_at_utc, asset_key, buy, sell
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (
                    recorded_at_utc,
                    str(q.key),
                    str(q.buy),
                    str(q.sell),
                )
                for q in quotes
            ],
        )

    return recorded_at_utc


def load_turkey_gold_near_24h(
    db_path: Path,
    *,
    now: datetime | None = None,
    min_age_hours: int = 18,
    max_age_hours: int = 30,
) -> dict[str, tuple[Decimal, Decimal]]:
    if not db_path.exists():
        return {}

    local_now = now.astimezone(ISTANBUL_TZ) if now else datetime.now(ISTANBUL_TZ)
    now_utc = local_now.astimezone(timezone.utc)

    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT recorded_at_utc, asset_key, buy, sell
            FROM turkey_gold_snapshots
            ORDER BY recorded_at_utc DESC, id ASC
            """
        ).fetchall()

    batches: dict[str, dict[str, tuple[Decimal, Decimal]]] = {}
    for recorded_at_utc, asset_key, buy, sell in rows:
        timestamp = str(recorded_at_utc)
        batches.setdefault(timestamp, {})[str(asset_key)] = (
            Decimal(str(buy)),
            Decimal(str(sell)),
        )

    eligible: list[tuple[float, str]] = []
    for timestamp in batches:
        try:
            recorded = datetime.fromisoformat(timestamp)
        except ValueError:
            continue
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=timezone.utc)

        age_hours = (
            now_utc - recorded.astimezone(timezone.utc)
        ).total_seconds() / 3600

        if min_age_hours <= age_hours <= max_age_hours:
            eligible.append((abs(age_hours - 24), timestamp))

    if not eligible:
        return {}

    _, selected = min(eligible, key=lambda item: item[0])
    return batches[selected]
