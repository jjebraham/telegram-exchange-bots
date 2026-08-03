"""Read user-bot percentage adjustments from the shared pricing database."""

from __future__ import annotations

import os
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_PRICING_DB_PATH = "/home/kianirad2020/send_changes/pricing_settings.db"
MIN_ADJUSTMENT_PCT = Decimal("-50")
MAX_ADJUSTMENT_PCT = Decimal("50")


def pricing_db_path(override: str | None = None) -> str:
    return (
        override
        or os.getenv("PRICING_DB_PATH")
        or DEFAULT_PRICING_DB_PATH
    )


def _parse_percentage(value: object, default: Decimal) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default

    if not parsed.is_finite():
        return default
    if parsed < MIN_ADJUSTMENT_PCT or parsed > MAX_ADJUSTMENT_PCT:
        return default
    return parsed


def get_adjustment_percentage(
    key: str,
    default_percentage: Decimal | str,
    db_path: str | None = None,
) -> Decimal:
    """Return a valid percentage, falling back without interrupting the bot."""

    default = _parse_percentage(default_percentage, Decimal("0"))
    resolved_path = pricing_db_path(db_path)

    if not Path(resolved_path).is_file():
        return default

    try:
        connection = sqlite3.connect(resolved_path, timeout=3)
        try:
            connection.execute("PRAGMA busy_timeout = 3000")
            row = connection.execute(
                "SELECT value FROM pricing_settings WHERE key = ?",
                (key,),
            ).fetchone()
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return default

    if not row:
        return default
    return _parse_percentage(row[0], default)


def get_adjustment_factor(
    key: str,
    default_percentage: Decimal | str,
    db_path: str | None = None,
) -> Decimal:
    percentage = get_adjustment_percentage(
        key,
        default_percentage,
        db_path,
    )
    return Decimal("1") + (percentage / Decimal("100"))
