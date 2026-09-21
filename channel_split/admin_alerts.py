#!/usr/bin/env python3
"""Deduplicated Telegram admin alerts for AlanChande market safety."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from market_safety import (
    BLOCKED,
    SUSPICIOUS,
    VERIFIED,
    PostSafetyAssessment,
    SourceHealthEvent,
    alert_action,
    mark_alert_sent,
    mark_source_health_alert_sent,
    source_health_action,
)


def _fmt_value(value) -> str:
    if value is None:
        return "—"
    return f"{value:,}" if getattr(value, "as_tuple", None) else str(value)


def _send(token: str, chat_id: str, text: str, timeout: int = 20) -> None:
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
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
        detail = exc.read(1500).decode("utf-8", errors="replace")
        raise RuntimeError(f"Admin alert Telegram HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Admin alert Telegram request failed: {exc}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Admin alert Telegram API error: {result}")


def format_problem_alert(
    assessment: PostSafetyAssessment,
    *,
    mode: str,
) -> str:
    icon = "🛑" if assessment.decision == BLOCKED else "⚠️"
    lines = [
        f"{icon} <b>AlanChande RATE {assessment.decision}</b>",
        "",
        f"Post: <code>{html.escape(assessment.post_type)}</code>",
        f"Safety mode: <code>{html.escape(mode)}</code>",
        f"Time: <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</code>",
        "",
        f"Reason: {html.escape(assessment.reason)}",
    ]

    for check in assessment.checks[:4]:
        lines.extend(
            [
                "",
                f"<b>{html.escape(check.market_key)}</b>",
                f"Decision: <code>{check.decision}</code>",
                f"Sources: <code>{len(check.source_values)}</code>",
                f"Reference: <code>{html.escape(str(check.reference_value) if check.reference_value is not None else '—')}</code>",
                f"Last accepted: <code>{html.escape(str(check.last_accepted_value) if check.last_accepted_value is not None else '—')}</code>",
            ]
        )
        if check.move_pct is not None:
            lines.append(
                f"Move: <code>{html.escape(str(check.move_pct.quantize(Decimal('0.01'))))}%</code>"
            )

    if mode == "enforce":
        lines.extend(["", "❌ <b>PUBLIC POST NOT SENT</b>"])
    else:
        lines.extend(
            [
                "",
                "🧪 <b>SHADOW MODE:</b> the public/test post is not blocked yet.",
            ]
        )
    return "\n".join(lines)


def format_recovery_alert(assessment: PostSafetyAssessment) -> str:
    return "\n".join(
        [
            "✅ <b>AlanChande source recovered</b>",
            "",
            f"Post: <code>{html.escape(assessment.post_type)}</code>",
            f"Time: <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</code>",
            f"Safety gate: <b>{VERIFIED}</b>",
            "",
            html.escape(assessment.reason),
        ]
    )


def maybe_notify_admin(
    db_path: Path,
    assessment: PostSafetyAssessment,
    *,
    mode: str,
    token: str | None,
    chat_id: str | None,
    repeat_minutes: int = 60,
) -> str | None:
    """Send a deduplicated problem/recovery alert when admin config exists.

    Returns "problem", "recovery", or None. Safety blocking does not depend on
    alert delivery; an unavailable alert channel must never make a questionable
    market post publishable.
    """
    action = alert_action(
        db_path,
        assessment,
        repeat_minutes=repeat_minutes,
    )
    if action is None:
        return None

    if not token or not chat_id:
        return action

    text = (
        format_recovery_alert(assessment)
        if action == "recovery"
        else format_problem_alert(assessment, mode=mode)
    )
    _send(token, chat_id, text)
    mark_alert_sent(db_path, assessment, action=action)
    return action


def format_source_health_alert(
    event: SourceHealthEvent,
    *,
    recovery: bool,
) -> str:
    if recovery:
        return "\n".join(
            [
                "✅ <b>AlanChande source recovered</b>",
                "",
                f"Source: <code>{html.escape(event.source_key)}</code>",
                f"Time: <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</code>",
                "",
                "The provider is reachable/healthy again.",
            ]
        )

    return "\n".join(
        [
            "⚠️ <b>AlanChande source degraded</b>",
            "",
            f"Source: <code>{html.escape(event.source_key)}</code>",
            f"Time: <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</code>",
            "",
            f"Detail: {html.escape(event.detail or 'unavailable')}",
            "",
            "ℹ️ The public post may still be published if the remaining "
            "independent sources satisfy the safety quorum.",
        ]
    )


def maybe_notify_source_health(
    db_path: Path,
    event: SourceHealthEvent,
    *,
    token: str | None,
    chat_id: str | None,
    repeat_minutes: int = 60,
) -> str | None:
    action = source_health_action(
        db_path,
        event,
        repeat_minutes=repeat_minutes,
    )
    if action is None:
        return None

    if not token or not chat_id:
        return action

    _send(
        token,
        chat_id,
        format_source_health_alert(
            event,
            recovery=action == "recovery",
        ),
    )
    mark_source_health_alert_sent(
        db_path,
        event,
        action=action,
    )
    return action
