#!/usr/bin/env python3
"""Fail-closed market safety gate for AlanChande financial posts.

The safety layer is deliberately separate from the formatters. A formatter may
successfully build a Telegram message while the safety gate still decides that
there is not enough independent evidence to publish it.

Modes:
- off:    evaluate/audit is optional; publication is never blocked.
- shadow: evaluate and audit, but do not block test publishing.
- enforce: only VERIFIED posts may be published.

"Last accepted" means a value from a successfully published VERIFIED post. A
blocked/suspicious or dry-run value never becomes the historical baseline.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

VERIFIED = "VERIFIED"
SUSPICIOUS = "SUSPICIOUS"
BLOCKED = "BLOCKED"
VALID_MODES = {"off", "shadow", "enforce"}

_SEVERITY = {VERIFIED: 0, SUSPICIOUS: 1, BLOCKED: 2}


@dataclass(frozen=True)
class SafetyObservation:
    market_key: str
    source_values: Mapping[str, Decimal]
    min_sources: int = 2
    max_source_deviation_pct: Decimal = Decimal("2.00")
    suspicious_move_pct: Decimal = Decimal("5.00")
    strong_quorum: int = 3
    structural_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class SafetyCheck:
    market_key: str
    decision: str
    reason: str
    source_values: dict[str, Decimal]
    reference_value: Decimal | None
    last_accepted_value: Decimal | None
    move_pct: Decimal | None


@dataclass(frozen=True)
class PostSafetyAssessment:
    post_type: str
    decision: str
    reason: str
    checks: tuple[SafetyCheck, ...]


@dataclass(frozen=True)
class AlertState:
    alert_key: str
    active: bool
    last_sent_at_utc: str | None
    reason_hash: str | None


def normalize_mode(value: str | None) -> str:
    mode = (value or "shadow").strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(
            f"Invalid MARKET_SAFETY_MODE {value!r}; expected one of "
            + ", ".join(sorted(VALID_MODES))
        )
    return mode


def publication_allowed(mode: str, assessment: PostSafetyAssessment) -> bool:
    normalized = normalize_mode(mode)
    if normalized in {"off", "shadow"}:
        return True
    return assessment.decision == VERIFIED


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Market value must be finite and positive: {value!r}")
    return parsed


def _median(values: Iterable[Decimal]) -> Decimal:
    items = list(values)
    if not items:
        raise ValueError("Cannot calculate a median from no values")
    return Decimal(str(statistics.median(items)))


def _pct_change(previous: Decimal, current: Decimal) -> Decimal:
    if previous <= 0:
        raise ValueError("Previous value must be positive")
    return ((current - previous) / previous) * Decimal("100")


def _max_deviation_pct(reference: Decimal, values: Iterable[Decimal]) -> Decimal:
    if reference <= 0:
        raise ValueError("Reference value must be positive")
    deviations = [
        (abs(value - reference) / reference) * Decimal("100")
        for value in values
    ]
    return max(deviations, default=Decimal("0"))


def _looks_like_unit_jump(previous: Decimal, current: Decimal) -> bool:
    if previous <= 0 or current <= 0:
        return False
    ratio = current / previous
    # Catch the classic rial/toman x10 or /10 class of normalization errors.
    return Decimal("8") <= ratio <= Decimal("12") or Decimal("0.08") <= ratio <= Decimal("0.12")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_safety_accepted (
            market_key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            accepted_at_utc TEXT NOT NULL,
            source_count INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_safety_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checked_at_utc TEXT NOT NULL,
            post_type TEXT NOT NULL,
            market_key TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            source_count INTEGER NOT NULL,
            source_values_json TEXT NOT NULL,
            reference_value TEXT,
            last_accepted_value TEXT,
            move_pct TEXT,
            mode TEXT NOT NULL,
            published INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_safety_audit_time "
        "ON market_safety_audit(checked_at_utc, id)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_safety_alert_state (
            alert_key TEXT PRIMARY KEY,
            active INTEGER NOT NULL,
            last_sent_at_utc TEXT,
            reason_hash TEXT
        )
        """
    )
    return connection


def load_last_accepted(db_path: Path, market_key: str) -> Decimal | None:
    if not db_path.exists():
        return None
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT value FROM market_safety_accepted WHERE market_key = ?",
            (market_key,),
        ).fetchone()
    if not row:
        return None
    return Decimal(str(row[0]))


def evaluate_observation(
    observation: SafetyObservation,
    *,
    last_accepted_value: Decimal | None = None,
) -> SafetyCheck:
    normalized: dict[str, Decimal] = {}
    errors = list(observation.structural_errors)

    for source, raw_value in observation.source_values.items():
        try:
            normalized[str(source)] = _decimal(raw_value)
        except ValueError as exc:
            errors.append(f"{source}: {exc}")

    if errors:
        return SafetyCheck(
            market_key=observation.market_key,
            decision=BLOCKED,
            reason="structural validation failed: " + "; ".join(errors),
            source_values=normalized,
            reference_value=None,
            last_accepted_value=last_accepted_value,
            move_pct=None,
        )

    if len(normalized) < observation.min_sources:
        return SafetyCheck(
            market_key=observation.market_key,
            decision=BLOCKED,
            reason=(
                "insufficient independent source families: "
                f"{len(normalized)} < {observation.min_sources}"
            ),
            source_values=normalized,
            reference_value=_median(normalized.values()) if normalized else None,
            last_accepted_value=last_accepted_value,
            move_pct=None,
        )

    initial_reference = _median(normalized.values())
    inliers = {
        source: value
        for source, value in normalized.items()
        if (
            abs(value - initial_reference) / initial_reference * Decimal("100")
        )
        <= observation.max_source_deviation_pct
    }
    rejected = {
        source: value
        for source, value in normalized.items()
        if source not in inliers
    }

    if len(inliers) < observation.min_sources:
        deviation = _max_deviation_pct(initial_reference, normalized.values())
        return SafetyCheck(
            market_key=observation.market_key,
            decision=BLOCKED,
            reason=(
                "independent sources disagree and quorum is lost: "
                f"{len(inliers)} inliers < {observation.min_sources}; "
                f"max deviation {deviation.quantize(Decimal('0.01'))}%"
            ),
            source_values=normalized,
            reference_value=initial_reference,
            last_accepted_value=last_accepted_value,
            move_pct=None,
        )

    # Recompute the reference from the surviving consensus. A single provider
    # may be rejected without vetoing two or more agreeing independent sources.
    reference = _median(inliers.values())
    consensus_note = ""
    if rejected:
        rejected_text = ", ".join(
            f"{source}={value}" for source, value in sorted(rejected.items())
        )
        consensus_note = f"; rejected outlier source(s): {rejected_text}"

    move_pct: Decimal | None = None
    if last_accepted_value is not None:
        if _looks_like_unit_jump(last_accepted_value, reference):
            return SafetyCheck(
                market_key=observation.market_key,
                decision=BLOCKED,
                reason="possible x10 or /10 unit-conversion jump versus last accepted value",
                source_values=normalized,
                reference_value=reference,
                last_accepted_value=last_accepted_value,
                move_pct=abs(_pct_change(last_accepted_value, reference)),
            )

        move_pct = abs(_pct_change(last_accepted_value, reference))
        if (
            move_pct > observation.suspicious_move_pct
            and len(inliers) < observation.strong_quorum
        ):
            return SafetyCheck(
                market_key=observation.market_key,
                decision=SUSPICIOUS,
                reason=(
                    "large move versus last accepted value requires stronger quorum: "
                    f"{move_pct.quantize(Decimal('0.01'))}% > "
                    f"{observation.suspicious_move_pct}% with "
                    f"{len(inliers)}/{observation.strong_quorum} source families"
                ),
                source_values=normalized,
                reference_value=reference,
                last_accepted_value=last_accepted_value,
                move_pct=move_pct,
            )

    return SafetyCheck(
        market_key=observation.market_key,
        decision=VERIFIED,
        reason=(
            f"{len(inliers)} independent source families agree within "
            f"{observation.max_source_deviation_pct}%{consensus_note}"
        ),
        source_values=inliers,
        reference_value=reference,
        last_accepted_value=last_accepted_value,
        move_pct=move_pct,
    )


def assess_post(
    db_path: Path,
    post_type: str,
    observations: Iterable[SafetyObservation],
) -> PostSafetyAssessment:
    checks: list[SafetyCheck] = []
    for observation in observations:
        checks.append(
            evaluate_observation(
                observation,
                last_accepted_value=load_last_accepted(
                    db_path, observation.market_key
                ),
            )
        )

    if not checks:
        checks.append(
            SafetyCheck(
                market_key=f"{post_type}:no-observations",
                decision=BLOCKED,
                reason="no safety observations were supplied",
                source_values={},
                reference_value=None,
                last_accepted_value=None,
                move_pct=None,
            )
        )

    worst = max(checks, key=lambda item: _SEVERITY[item.decision]).decision
    reasons = [
        f"{check.market_key}: {check.reason}"
        for check in checks
        if check.decision != VERIFIED
    ]
    if reasons:
        summary = " | ".join(reasons[:4])
        if len(reasons) > 4:
            summary += f" | +{len(reasons) - 4} more"
    else:
        summary = f"all {len(checks)} safety checks verified"

    return PostSafetyAssessment(
        post_type=post_type,
        decision=worst,
        reason=summary,
        checks=tuple(checks),
    )


def record_assessment(
    db_path: Path,
    assessment: PostSafetyAssessment,
    *,
    mode: str,
    published: bool,
    now: datetime | None = None,
) -> None:
    checked = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    checked_text = checked.isoformat(timespec="seconds")
    normalized_mode = normalize_mode(mode)

    with _connect(db_path) as connection:
        for check in assessment.checks:
            connection.execute(
                """
                INSERT INTO market_safety_audit (
                    checked_at_utc, post_type, market_key, decision, reason,
                    source_count, source_values_json, reference_value,
                    last_accepted_value, move_pct, mode, published
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checked_text,
                    assessment.post_type,
                    check.market_key,
                    check.decision,
                    check.reason,
                    len(check.source_values),
                    json.dumps(
                        {key: str(value) for key, value in check.source_values.items()},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    str(check.reference_value) if check.reference_value is not None else None,
                    str(check.last_accepted_value)
                    if check.last_accepted_value is not None
                    else None,
                    str(check.move_pct) if check.move_pct is not None else None,
                    normalized_mode,
                    1 if published else 0,
                ),
            )

            # Only a successfully published VERIFIED value may become the
            # baseline for future circuit-breaker comparisons.
            if (
                published
                and check.decision == VERIFIED
                and check.reference_value is not None
            ):
                connection.execute(
                    """
                    INSERT INTO market_safety_accepted (
                        market_key, value, accepted_at_utc, source_count
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(market_key) DO UPDATE SET
                        value = excluded.value,
                        accepted_at_utc = excluded.accepted_at_utc,
                        source_count = excluded.source_count
                    """,
                    (
                        check.market_key,
                        str(check.reference_value),
                        checked_text,
                        len(check.source_values),
                    ),
                )


def get_alert_state(db_path: Path, alert_key: str) -> AlertState:
    if not db_path.exists():
        return AlertState(alert_key, False, None, None)
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT active, last_sent_at_utc, reason_hash
            FROM market_safety_alert_state
            WHERE alert_key = ?
            """,
            (alert_key,),
        ).fetchone()
    if not row:
        return AlertState(alert_key, False, None, None)
    return AlertState(
        alert_key=alert_key,
        active=bool(row[0]),
        last_sent_at_utc=str(row[1]) if row[1] else None,
        reason_hash=str(row[2]) if row[2] else None,
    )


def alert_action(
    db_path: Path,
    assessment: PostSafetyAssessment,
    *,
    now: datetime | None = None,
    repeat_minutes: int = 60,
) -> str | None:
    """Return 'problem', 'recovery', or None for deduplicated admin alerts."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    state = get_alert_state(db_path, assessment.post_type)

    if assessment.decision == VERIFIED:
        return "recovery" if state.active else None

    digest = hashlib.sha256(assessment.reason.encode("utf-8")).hexdigest()
    if not state.active:
        return "problem"
    if state.reason_hash != digest:
        return "problem"
    if state.last_sent_at_utc:
        try:
            last = datetime.fromisoformat(state.last_sent_at_utc)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if current - last.astimezone(timezone.utc) >= timedelta(
                minutes=repeat_minutes
            ):
                return "problem"
        except ValueError:
            return "problem"
    return None


def mark_alert_sent(
    db_path: Path,
    assessment: PostSafetyAssessment,
    *,
    action: str,
    now: datetime | None = None,
) -> None:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    timestamp = current.isoformat(timespec="seconds")
    reason_hash = (
        hashlib.sha256(assessment.reason.encode("utf-8")).hexdigest()
        if assessment.decision != VERIFIED
        else None
    )
    active = 0 if action == "recovery" else 1

    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO market_safety_alert_state (
                alert_key, active, last_sent_at_utc, reason_hash
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(alert_key) DO UPDATE SET
                active = excluded.active,
                last_sent_at_utc = excluded.last_sent_at_utc,
                reason_hash = excluded.reason_hash
            """,
            (assessment.post_type, active, timestamp, reason_hash),
        )


def recent_safety_status(db_path: Path, limit: int = 20) -> str:
    if not db_path.exists():
        return "safety audit: no database yet"
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT checked_at_utc, post_type, market_key, decision, reason,
                   source_count, mode, published
            FROM market_safety_audit
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

    if not rows:
        return "safety audit: no checks recorded yet"

    lines = ["safety audit (newest first):"]
    for checked, post_type, market_key, decision, reason, count, mode, published in rows:
        lines.append(
            f"{checked} | {post_type} | {market_key} | {decision} | "
            f"sources={count} | mode={mode} | published={published} | {reason}"
        )
    return "\n".join(lines)


def _midpoint(buy: Decimal, sell: Decimal) -> Decimal:
    return (_decimal(buy) + _decimal(sell)) / Decimal("2")


def bank_fx_observations(
    pair: str,
    quotes: Iterable[Any],
    extra_sources: Mapping[str, Mapping[str, Decimal]] | None = None,
) -> list[SafetyObservation]:
    observations: list[SafetyObservation] = []
    for quote in quotes:
        errors: list[str] = []
        if Decimal(str(quote.sell)) <= Decimal(str(quote.buy)):
            errors.append("sell must be greater than buy")
        source_values = {"doviz": _midpoint(quote.buy, quote.sell)}
        for source_name, values in (extra_sources or {}).items():
            if quote.name in values:
                source_values[str(source_name)] = _decimal(values[quote.name])
        observations.append(
            SafetyObservation(
                market_key=f"bank:{pair}:{quote.name}",
                source_values=source_values,
                structural_errors=tuple(errors),
                max_source_deviation_pct=Decimal("1.50"),
                suspicious_move_pct=Decimal("4.00"),
            )
        )
    return observations


def fx_pulse_observations(
    usd_quotes: Iterable[Any],
    eur_quotes: Iterable[Any],
    extra_sources: Mapping[str, Mapping[str, Decimal]] | None = None,
) -> list[SafetyObservation]:
    result: list[SafetyObservation] = []
    for pair, quotes in (("USD/TRY", usd_quotes), ("EUR/TRY", eur_quotes)):
        kapali = next((q for q in quotes if q.name == "Kapalıçarşı"), None)
        if kapali is None:
            result.append(
                SafetyObservation(
                    market_key=f"fx:{pair}:kapalicarsi",
                    source_values={},
                    structural_errors=("Kapalıçarşı row missing",),
                    max_source_deviation_pct=Decimal("1.50"),
                    suspicious_move_pct=Decimal("4.00"),
                )
            )
            continue
        source_values = {"doviz": _midpoint(kapali.buy, kapali.sell)}
        for source_name, pair_values in (extra_sources or {}).items():
            if pair in pair_values:
                source_values[str(source_name)] = _decimal(pair_values[pair])
        result.append(
            SafetyObservation(
                market_key=f"fx:{pair}:kapalicarsi",
                source_values=source_values,
                max_source_deviation_pct=Decimal("1.50"),
                suspicious_move_pct=Decimal("4.00"),
            )
        )
    return result


def turkey_gold_observations(
    quotes: Iterable[Any],
    extra_sources: Mapping[str, Mapping[str, Decimal]] | None = None,
) -> list[SafetyObservation]:
    observations: list[SafetyObservation] = []
    for quote in quotes:
        errors: list[str] = []
        if Decimal(str(quote.sell)) <= Decimal(str(quote.buy)):
            errors.append("sell must be greater than buy")
        source_values = {"doviz": _midpoint(quote.buy, quote.sell)}
        for source_name, values in (extra_sources or {}).items():
            if quote.key in values:
                source_values[str(source_name)] = _decimal(values[quote.key])
        observations.append(
            SafetyObservation(
                market_key=f"turkey-gold:{quote.key}",
                source_values=source_values,
                structural_errors=tuple(errors),
                max_source_deviation_pct=Decimal("1.50"),
                suspicious_move_pct=Decimal("5.00"),
            )
        )
    return observations


def iran_gold_observations(
    market: Any,
    extra_sources: Mapping[str, Mapping[str, Decimal]] | None = None,
) -> list[SafetyObservation]:
    observations: list[SafetyObservation] = []
    for label, value in market.coin_prices_rial.items():
        source_values = {"tgju": _decimal(value) / Decimal("10")}
        for source_name, values in (extra_sources or {}).items():
            if label in values:
                source_values[str(source_name)] = _decimal(values[label])
        observations.append(
            SafetyObservation(
                market_key=f"iran-gold:{label}",
                source_values=source_values,
                max_source_deviation_pct=Decimal("2.00"),
                suspicious_move_pct=Decimal("7.00"),
            )
        )
    if market.gold18_rial is not None:
        source_values = {"tgju": _decimal(market.gold18_rial) / Decimal("10")}
        for source_name, values in (extra_sources or {}).items():
            if "طلای ۱۸ عیار" in values:
                source_values[str(source_name)] = _decimal(values["طلای ۱۸ عیار"])
        observations.append(
            SafetyObservation(
                market_key="iran-gold:طلای ۱۸ عیار",
                source_values=source_values,
                max_source_deviation_pct=Decimal("2.00"),
                suspicious_move_pct=Decimal("7.00"),
            )
        )
    if market.mesghal_rial is not None:
        source_values = {"tgju": _decimal(market.mesghal_rial) / Decimal("10")}
        for source_name, values in (extra_sources or {}).items():
            if "مثقال طلا" in values:
                source_values[str(source_name)] = _decimal(values["مثقال طلا"])
        observations.append(
            SafetyObservation(
                market_key="iran-gold:مثقال طلا",
                source_values=source_values,
                max_source_deviation_pct=Decimal("2.00"),
                suspicious_move_pct=Decimal("7.00"),
            )
        )
    return observations


def _usdt_source_family(quote: Any) -> str:
    source = str(quote.source)
    if source == "direct":
        # Each direct exchange API is independently operated.
        return f"direct:{quote.exchange}"
    if source in {"tgju", "ramzarz"}:
        return source
    if source == "tgju+ramzarz":
        # A mixed row is not a new independent source family. Count it
        # conservatively as one aggregator family rather than inflating quorum.
        return "tgju"
    return f"fallback:{source}"


def usdt_source_family_values(quotes: Iterable[Any]) -> dict[str, Decimal]:
    grouped: dict[str, list[Decimal]] = {}
    for quote in quotes:
        buy = _decimal(quote.buy_toman)
        sell = (
            _decimal(quote.sell_toman)
            if quote.sell_toman is not None
            else None
        )
        value = (buy + sell) / Decimal("2") if sell is not None else buy
        grouped.setdefault(_usdt_source_family(quote), []).append(value)
    return {family: _median(values) for family, values in grouped.items()}


def usdt_observations(quotes: Iterable[Any]) -> list[SafetyObservation]:
    rows = list(quotes)
    errors: list[str] = []
    if len(rows) < 5:
        errors.append(f"only {len(rows)} exchange rows survived; need at least 5")

    two_sided = 0
    for quote in rows:
        buy = _decimal(quote.buy_toman)
        if quote.sell_toman is None:
            continue
        sell = _decimal(quote.sell_toman)
        if sell >= buy:
            errors.append(f"{quote.exchange}: crossed customer buy/sell pair")
        else:
            two_sided += 1
    if two_sided < 4:
        errors.append(f"only {two_sided} two-sided exchange rows; need at least 4")

    return [
        SafetyObservation(
            market_key="usdt:IRT",
            source_values=usdt_source_family_values(rows),
            min_sources=2,
            max_source_deviation_pct=Decimal("2.00"),
            suspicious_move_pct=Decimal("5.00"),
            strong_quorum=3,
            structural_errors=tuple(errors),
        )
    ]
