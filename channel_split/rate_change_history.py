#!/usr/bin/env python3
"""Trusted published-value history for AlanChande percentage-change columns.

Only successfully delivered VERIFIED posts should be recorded here. Shadow
BLOCKED/SUSPICIOUS posts, dry runs, and failed sends must never advance this
history.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS published_value_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at_utc TEXT NOT NULL,
            board TEXT NOT NULL,
            item TEXT NOT NULL,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_published_value_board_time "
        "ON published_value_snapshots(board, recorded_at_utc, id)"
    )
    return connection


def record_published_values(
    db_path: Path,
    board: str,
    values: Mapping[str, Decimal],
    *,
    now: datetime | None = None,
) -> str:
    if not values:
        raise ValueError("No published values supplied")

    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    recorded_at_utc = instant.astimezone(timezone.utc).isoformat(timespec="seconds")

    rows = []
    for item, raw in values.items():
        value = Decimal(str(raw))
        if not value.is_finite() or value <= 0:
            raise ValueError(f"Invalid published value for {item}: {raw!r}")
        rows.append((recorded_at_utc, board, str(item), str(value)))

    with _connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO published_value_snapshots (
                recorded_at_utc, board, item, value
            ) VALUES (?, ?, ?, ?)
            """,
            rows,
        )
    return recorded_at_utc


def load_published_values_near_age(
    db_path: Path,
    board: str,
    *,
    target_hours: int,
    min_age_hours: int,
    max_age_hours: int,
    now: datetime | None = None,
) -> dict[str, Decimal]:
    if not db_path.exists():
        return {}

    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    now_utc = instant.astimezone(timezone.utc)

    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT recorded_at_utc, item, value
            FROM published_value_snapshots
            WHERE board = ?
            ORDER BY recorded_at_utc DESC, id ASC
            """,
            (board,),
        ).fetchall()

    batches: dict[str, dict[str, Decimal]] = {}
    for recorded_at_utc, item, value in rows:
        batches.setdefault(str(recorded_at_utc), {})[str(item)] = Decimal(str(value))

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
            eligible.append((abs(age_hours - target_hours), timestamp))

    if not eligible:
        return {}

    _, selected = min(eligible, key=lambda item: item[0])
    return batches[selected]


def percentage_changes(
    current: Mapping[str, Decimal],
    previous: Mapping[str, Decimal],
) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for item, current_raw in current.items():
        if item not in previous:
            continue
        current_value = Decimal(str(current_raw))
        previous_value = Decimal(str(previous[item]))
        if previous_value <= 0:
            continue
        result[item] = (
            (current_value - previous_value) / previous_value
        ) * Decimal("100")
    return result
