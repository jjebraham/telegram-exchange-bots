#!/usr/bin/env python3
"""Local history for Iranian gold and coin prices used by AlanChande."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS iran_gold_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at_utc TEXT NOT NULL,
            asset_key TEXT NOT NULL,
            price_rial TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_iran_gold_time "
        "ON iran_gold_snapshots(recorded_at_utc, id)"
    )
    return connection


def _market_values(market: Any) -> dict[str, Decimal]:
    values = {str(key): Decimal(str(value)) for key, value in market.coin_prices_rial.items()}
    if market.gold18_rial is not None:
        values["طلای ۱۸ عیار"] = Decimal(str(market.gold18_rial))
    if market.mesghal_rial is not None:
        values["مثقال طلا"] = Decimal(str(market.mesghal_rial))
    return values


def record_iran_gold_market(
    db_path: Path,
    market: Any,
    *,
    now: datetime | None = None,
) -> str:
    values = _market_values(market)
    if not values:
        raise ValueError("No Iran gold prices supplied")

    local_now = now.astimezone(TEHRAN_TZ) if now else datetime.now(TEHRAN_TZ)
    recorded_at_utc = local_now.astimezone(timezone.utc).isoformat(timespec="seconds")

    with _connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO iran_gold_snapshots (
                recorded_at_utc, asset_key, price_rial
            ) VALUES (?, ?, ?)
            """,
            [
                (recorded_at_utc, asset_key, str(price_rial))
                for asset_key, price_rial in values.items()
            ],
        )

    return recorded_at_utc


def load_iran_gold_near_24h(
    db_path: Path,
    *,
    now: datetime | None = None,
    min_age_hours: int = 18,
    max_age_hours: int = 30,
) -> dict[str, Decimal]:
    if not db_path.exists():
        return {}

    local_now = now.astimezone(TEHRAN_TZ) if now else datetime.now(TEHRAN_TZ)
    now_utc = local_now.astimezone(timezone.utc)

    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT recorded_at_utc, asset_key, price_rial
            FROM iran_gold_snapshots
            ORDER BY recorded_at_utc DESC, id ASC
            """
        ).fetchall()

    batches: dict[str, dict[str, Decimal]] = {}
    for recorded_at_utc, asset_key, price_rial in rows:
        timestamp = str(recorded_at_utc)
        batches.setdefault(timestamp, {})[str(asset_key)] = Decimal(str(price_rial))

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
