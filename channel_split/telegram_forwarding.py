"""Persist Kiani source message IDs and forward selected daily posts safely."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")


@dataclass(frozen=True)
class SourceMessage:
    source_key: str
    local_date: str
    sent_at: datetime
    message_id: int
    source_chat_id: str


@dataclass(frozen=True)
class ForwardOutcome:
    status: str
    source_key: str
    local_date: str
    source_message_id: int | None = None
    forwarded_message_id: int | None = None


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS kiani_forward_source_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT NOT NULL,
            local_date TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            source_chat_id TEXT NOT NULL,
            UNIQUE(source_chat_id, message_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_kiani_forward_source_slot
        ON kiani_forward_source_messages(source_key, local_date)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS kiani_forward_deliveries (
            source_key TEXT NOT NULL,
            local_date TEXT NOT NULL,
            source_message_id INTEGER NOT NULL,
            forwarded_message_id INTEGER NOT NULL,
            forwarded_at TEXT NOT NULL,
            PRIMARY KEY(source_key, local_date)
        )
        """
    )
    return connection


def record_source_message(
    db_path: Path,
    *,
    source_key: str,
    message_id: int,
    source_chat_id: str,
    sent_at: datetime | None = None,
) -> None:
    captured = sent_at or datetime.now(timezone.utc)
    if captured.tzinfo is None:
        raise ValueError("sent_at must be timezone-aware")
    local_date = captured.astimezone(ISTANBUL_TZ).date().isoformat()

    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO kiani_forward_source_messages
                (source_key, local_date, sent_at, message_id, source_chat_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                source_key,
                local_date,
                captured.astimezone(timezone.utc).isoformat(),
                int(message_id),
                source_chat_id,
            ),
        )


def find_source_for_slot(
    db_path: Path,
    *,
    source_key: str,
    local_date: str,
    expected_local_time: str,
    tolerance_minutes: int = 12,
) -> SourceMessage | None:
    hour_text, minute_text = expected_local_time.split(":", 1)
    target = datetime.combine(
        datetime.fromisoformat(local_date).date(),
        dt_time(hour=int(hour_text), minute=int(minute_text)),
        tzinfo=ISTANBUL_TZ,
    )

    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT sent_at, message_id, source_chat_id
            FROM kiani_forward_source_messages
            WHERE source_key = ? AND local_date = ?
            """,
            (source_key, local_date),
        ).fetchall()

    candidates: list[tuple[timedelta, SourceMessage]] = []
    for sent_at_text, message_id, source_chat_id in rows:
        sent_at = datetime.fromisoformat(sent_at_text)
        if sent_at.tzinfo is None:
            continue
        delta = abs(sent_at.astimezone(ISTANBUL_TZ) - target)
        candidates.append(
            (
                delta,
                SourceMessage(
                    source_key=source_key,
                    local_date=local_date,
                    sent_at=sent_at,
                    message_id=int(message_id),
                    source_chat_id=str(source_chat_id),
                ),
            )
        )

    if not candidates:
        return None

    delta, candidate = min(candidates, key=lambda item: item[0])
    if delta > timedelta(minutes=max(1, tolerance_minutes)):
        return None
    return candidate


def already_forwarded(
    db_path: Path,
    *,
    source_key: str,
    local_date: str,
) -> bool:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM kiani_forward_deliveries
            WHERE source_key = ? AND local_date = ?
            LIMIT 1
            """,
            (source_key, local_date),
        ).fetchone()
    return row is not None


def record_forward(
    db_path: Path,
    *,
    source_key: str,
    local_date: str,
    source_message_id: int,
    forwarded_message_id: int,
    forwarded_at: datetime | None = None,
) -> None:
    timestamp = forwarded_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("forwarded_at must be timezone-aware")
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO kiani_forward_deliveries
                (
                    source_key,
                    local_date,
                    source_message_id,
                    forwarded_message_id,
                    forwarded_at
                )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                source_key,
                local_date,
                int(source_message_id),
                int(forwarded_message_id),
                timestamp.astimezone(timezone.utc).isoformat(),
            ),
        )


def telegram_forward(
    token: str,
    *,
    from_chat_id: str,
    to_chat_id: str,
    message_id: int,
    timeout: int = 20,
) -> dict[str, Any]:
    endpoint = f"https://api.telegram.org/bot{token}/forwardMessage"
    payload = urlencode(
        {
            "chat_id": to_chat_id,
            "from_chat_id": from_chat_id,
            "message_id": str(int(message_id)),
            "disable_notification": "true",
        }
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Telegram forward returned HTTP {exc.code}: {detail}"
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Telegram forward request failed: {exc}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram forward API error: {result}")
    return result


def forward_daily_slot(
    db_path: Path,
    *,
    source_key: str,
    expected_local_time: str,
    token: str,
    source_chat_id: str,
    destination_chat_id: str,
    now: datetime | None = None,
    tolerance_minutes: int = 12,
    dry_run: bool = False,
) -> ForwardOutcome:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_date = current.astimezone(ISTANBUL_TZ).date().isoformat()

    if already_forwarded(
        db_path,
        source_key=source_key,
        local_date=local_date,
    ):
        return ForwardOutcome(
            status="already-forwarded",
            source_key=source_key,
            local_date=local_date,
        )

    source = find_source_for_slot(
        db_path,
        source_key=source_key,
        local_date=local_date,
        expected_local_time=expected_local_time,
        tolerance_minutes=tolerance_minutes,
    )
    if source is None:
        raise RuntimeError(
            f"No {source_key} source message recorded within "
            f"{tolerance_minutes} minutes of {expected_local_time} Istanbul"
        )

    if source.source_chat_id != source_chat_id:
        raise RuntimeError(
            f"Recorded source chat mismatch: {source.source_chat_id!r} "
            f"!= {source_chat_id!r}"
        )

    if dry_run:
        return ForwardOutcome(
            status="dry-run-ready",
            source_key=source_key,
            local_date=local_date,
            source_message_id=source.message_id,
        )

    response = telegram_forward(
        token,
        from_chat_id=source_chat_id,
        to_chat_id=destination_chat_id,
        message_id=source.message_id,
    )
    payload = response.get("result")
    if not isinstance(payload, dict) or "message_id" not in payload:
        raise RuntimeError("Telegram forward response has no result.message_id")
    forwarded_message_id = int(payload["message_id"])

    record_forward(
        db_path,
        source_key=source_key,
        local_date=local_date,
        source_message_id=source.message_id,
        forwarded_message_id=forwarded_message_id,
    )
    return ForwardOutcome(
        status="forwarded",
        source_key=source_key,
        local_date=local_date,
        source_message_id=source.message_id,
        forwarded_message_id=forwarded_message_id,
    )
