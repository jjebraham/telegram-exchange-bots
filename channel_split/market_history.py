#!/usr/bin/env python3
"""Local SQLite history for neutral AlanChande market snapshots.

The history database is intentionally local to the server and is not committed.
It stores Kapalicarsi USD/TRY and EUR/TRY quotes so AlanChande can calculate
intraday changes, highs/lows and later chart data without depending on Kiani's
transaction-rate API.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
DEFAULT_HISTORY_DB = Path(__file__).with_name("market_history.sqlite3")


@dataclass(frozen=True)
class MarketSnapshot:
    local_date: str
    local_time: str
    recorded_at_utc: str
    usd_buy: Decimal
    usd_sell: Decimal
    eur_buy: Decimal
    eur_sell: Decimal

    @property
    def usd_mid(self) -> Decimal:
        return (self.usd_buy + self.usd_sell) / Decimal("2")

    @property
    def eur_mid(self) -> Decimal:
        return (self.eur_buy + self.eur_sell) / Decimal("2")


def _kapalicarsi(quotes: list[Any]) -> Any:
    quote = next((q for q in quotes if q.name == "Kapalıçarşı"), None)
    if quote is None:
        raise ValueError("Kapalıçarşı quote is required for history")
    return quote


def build_snapshot(
    usd_quotes: list[Any],
    eur_quotes: list[Any],
    *,
    now: datetime | None = None,
) -> MarketSnapshot:
    local_now = now.astimezone(ISTANBUL_TZ) if now else datetime.now(ISTANBUL_TZ)
    usd = _kapalicarsi(usd_quotes)
    eur = _kapalicarsi(eur_quotes)
    return MarketSnapshot(
        local_date=local_now.strftime("%Y-%m-%d"),
        local_time=local_now.strftime("%H:%M:%S"),
        recorded_at_utc=local_now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        usd_buy=Decimal(str(usd.buy)),
        usd_sell=Decimal(str(usd.sell)),
        eur_buy=Decimal(str(eur.buy)),
        eur_sell=Decimal(str(eur.sell)),
    )


def _create_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at_utc TEXT NOT NULL,
            local_date TEXT NOT NULL,
            local_time TEXT NOT NULL,
            usd_buy TEXT NOT NULL,
            usd_sell TEXT NOT NULL,
            eur_buy TEXT NOT NULL,
            eur_sell TEXT NOT NULL
        )
        """
    )


def _migrate_old_kiani_schema(connection: sqlite3.Connection) -> None:
    """Remove the first MVP's Kiani columns if that schema was already created."""
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_snapshots'"
    ).fetchone()
    if not exists:
        return

    columns = connection.execute("PRAGMA table_info(market_snapshots)").fetchall()
    names = {str(row[1]) for row in columns}
    if not any(name.startswith("kiani_") for name in names):
        return

    connection.execute("DROP INDEX IF EXISTS idx_market_snapshots_local_date")
    connection.execute("ALTER TABLE market_snapshots RENAME TO market_snapshots_legacy")
    _create_table(connection)
    connection.execute(
        """
        INSERT INTO market_snapshots (
            id, recorded_at_utc, local_date, local_time,
            usd_buy, usd_sell, eur_buy, eur_sell
        )
        SELECT
            id, recorded_at_utc, local_date, local_time,
            usd_buy, usd_sell, eur_buy, eur_sell
        FROM market_snapshots_legacy
        """
    )
    connection.execute("DROP TABLE market_snapshots_legacy")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    _migrate_old_kiani_schema(connection)
    _create_table(connection)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_snapshots_local_date ON market_snapshots(local_date, id)"
    )
    return connection


def record_snapshot(db_path: Path, snapshot: MarketSnapshot) -> int:
    with _connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO market_snapshots (
                recorded_at_utc, local_date, local_time,
                usd_buy, usd_sell, eur_buy, eur_sell
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.recorded_at_utc,
                snapshot.local_date,
                snapshot.local_time,
                str(snapshot.usd_buy),
                str(snapshot.usd_sell),
                str(snapshot.eur_buy),
                str(snapshot.eur_sell),
            ),
        )
        return int(cursor.lastrowid)


def _row_to_snapshot(row: tuple[Any, ...]) -> MarketSnapshot:
    return MarketSnapshot(
        recorded_at_utc=str(row[0]),
        local_date=str(row[1]),
        local_time=str(row[2]),
        usd_buy=Decimal(str(row[3])),
        usd_sell=Decimal(str(row[4])),
        eur_buy=Decimal(str(row[5])),
        eur_sell=Decimal(str(row[6])),
    )


def load_day(db_path: Path, local_date: str) -> list[MarketSnapshot]:
    if not db_path.exists():
        return []
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT recorded_at_utc, local_date, local_time,
                   usd_buy, usd_sell, eur_buy, eur_sell
            FROM market_snapshots
            WHERE local_date = ?
            ORDER BY id ASC
            """,
            (local_date,),
        ).fetchall()
    return [_row_to_snapshot(row) for row in rows]


def _fmt_rate(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.0001')):.4f}".rstrip("0").rstrip(".")


def _fmt_pct(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    if rounded > 0:
        return f"+{rounded:.2f}%"
    return f"{rounded:.2f}%"


def _direction(value: Decimal) -> str:
    if value > 0:
        return "🟢"
    if value < 0:
        return "🔴"
    return "⚪️"


def _change(first: Decimal, latest: Decimal) -> Decimal:
    if first == 0:
        raise ValueError("Cannot calculate percentage change from zero")
    return ((latest - first) / first) * Decimal("100")


def build_alanchande_daily_change_post(
    stored: list[MarketSnapshot],
    current: MarketSnapshot,
) -> str:
    if not stored:
        raise ValueError("No historical snapshot recorded for today yet")

    first = stored[0]
    points = [*stored, current]

    usd_change = _change(first.usd_mid, current.usd_mid)
    eur_change = _change(first.eur_mid, current.eur_mid)
    usd_mids = [point.usd_mid for point in points]
    eur_mids = [point.eur_mid for point in points]

    first_time = first.local_time[:5]
    current_time = current.local_time[:5]

    return "\n".join(
        [
            "📈 <b>تغییر امروز بازار</b>",
            "",
            f"{_direction(usd_change)} دلار/لیر: <b>{_fmt_rate(current.usd_mid)}</b> | <b>{_fmt_pct(usd_change)}</b>",
            f"کف ثبت‌شده: {_fmt_rate(min(usd_mids))} | سقف ثبت‌شده: {_fmt_rate(max(usd_mids))}",
            "",
            f"{_direction(eur_change)} یورو/لیر: <b>{_fmt_rate(current.eur_mid)}</b> | <b>{_fmt_pct(eur_change)}</b>",
            f"کف ثبت‌شده: {_fmt_rate(min(eur_mids))} | سقف ثبت‌شده: {_fmt_rate(max(eur_mids))}",
            "",
            f"🕒 از اولین ثبت امروز ({first_time}) تا الان ({current_time})",
        ]
    )


def history_status(db_path: Path, local_date: str) -> str:
    rows = load_day(db_path, local_date)
    if not rows:
        return f"history: 0 snapshots for {local_date}"
    return (
        f"history: {len(rows)} snapshots for {local_date}; "
        f"first={rows[0].local_time[:5]} latest={rows[-1].local_time[:5]}"
    )
