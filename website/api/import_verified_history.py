"""Incrementally copy verified publisher history into the website-owned store.

The source bot database is opened read-only. The importer uses only tables that
the publisher writes after successful VERIFIED delivery; it never calls market
collectors, Telegram/X senders, or bot database write helpers.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from data_foundation.snapshot import SnapshotError, validate_snapshot
from api.store import database_path, ingest_snapshots


IRAN_FX_LABELS = {
    "USD": "دلار آمریکا", "EUR": "یورو", "GBP": "پوند انگلیس", "CHF": "فرانک سوئیس",
    "CAD": "دلار کانادا", "AUD": "دلار استرالیا", "SEK": "کرون سوئد", "NOK": "کرون نروژ",
    "RUB": "روبل روسیه", "THB": "بات تایلند", "SGD": "دلار سنگاپور", "HKD": "دلار هنگ‌کنگ",
    "AZN": "منات آذربایجان", "DKK": "کرون دانمارک", "AED": "درهم امارات", "TRY": "لیر ترکیه",
    "CNY": "یوان چین", "SAR": "ریال عربستان", "INR": "روپیه هند", "MYR": "رینگیت مالزی",
    "AFN": "افغانی", "KWD": "دینار کویت", "BHD": "دینار بحرین", "OMR": "ریال عمان", "QAR": "ریال قطر",
}
BANK_LABELS = {
    "Kapalıçarşı": "بازار کاپالی‌چارشی", "Garanti BBVA": "گارانتی BBVA",
    "İş Bankası": "ایش بانک", "Kuveyt Türk": "کویت ترک", "Ziraat Bankası": "زراعت بانک",
}
IRAN_GOLD = {
    "سکه امامی": ("emami", "سکه امامی", "piece"),
    "سکه بهار آزادی": ("bahar-azadi", "سکه بهار آزادی", "piece"),
    "نیم سکه": ("half", "نیم سکه", "piece"),
    "ربع سکه": ("quarter", "ربع سکه", "piece"),
    "سکه گرمی": ("gram-coin", "سکه گرمی", "piece"),
    "طلای ۱۸ عیار": ("gold-18k", "گرم طلای ۱۸ عیار", "gram-18k"),
    "مثقال طلا": ("mithqal", "مثقال طلا", "mithqal"),
}
TURKEY_GOLD = {
    "gram": ("gram", "گرم طلا"), "quarter": ("quarter", "ربع سکه"),
    "half": ("half", "نیم سکه"), "tam": ("full", "تمام سکه"),
}
USDT_EXCHANGES = {
    "wallex": "والکس", "nobitex": "نوبیتکس", "ramzinex": "رمزینکس",
    "bitpin": "بیت‌پین", "abantether": "آبان‌تتر", "aban": "آبان‌تتر",
    "tabdeal": "تبدیل", "exir": "اکسیر",
}
DIGEST_FX = {
    "USD": "دلار آمریکا", "EUR": "یورو", "USDT": "تتر", "AED": "درهم امارات",
    "TRY": "لیر ترکیه", "CNY": "یوان چین", "CAD": "دلار کانادا",
    "AUD": "دلار استرالیا", "GBP": "پوند انگلیس", "IQD100": "صد دینار عراق",
    "AFN": "افغانی",
}
DIGEST_GOLD = {
    "COIN_EMAMI": ("coin-emami", "سکه امامی", "piece"),
    "COIN_AZADI": ("coin-azadi", "سکه بهار آزادی", "piece"),
    "COIN_HALF": ("coin-half", "نیم سکه", "piece"),
    "COIN_QUARTER": ("coin-quarter", "ربع سکه", "piece"),
    "MESGHAL": ("mesghal", "مثقال طلا", "mithqal"),
    "GOLD18": ("gold18", "گرم طلای ۱۸ عیار", "gram-18k"),
    "XAUUSD": ("xauusd", "انس جهانی طلا", "troy-ounce"),
}
DIGEST_CRYPTO = {
    "BTC": "بیت‌کوین", "ETH": "اتریوم", "BNB": "بایننس کوین",
    "TRX": "ترون", "SHIB": "شیبا", "ADA": "کاردانو",
    "DOGE": "دوج‌کوین", "GRAM": "گرام", "NOT": "نات‌کوین",
    "SOL": "سولانا", "XRP": "ریپل",
}
HAWALA_LABELS = {
    "USD": "حواله دلار آمریکا", "EUR": "حواله یورو",
    "GBP": "حواله پوند انگلیس", "CAD": "حواله دلار کانادا",
    "AUD": "حواله دلار استرالیا", "SEK": "حواله کرون سوئد",
    "TRY": "حواله لیر ترکیه",
}


def _utc(value: str) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _decimal(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SnapshotError("malformed value in verified publisher history") from exc
    if not number.is_finite() or number <= 0:
        raise SnapshotError("non-positive value in verified publisher history")
    return number


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")


def _quote(
    *, quote_id: str, series_id: str, instrument_id: str, base_asset: str,
    quote_currency: str, unit: str, category: str, label: str, collected_at: str,
    source_id: str, bid: Decimal | None = None, ask: Decimal | None = None,
    reference: Decimal | None = None, base_quantity: str = "1",
    quote_kind: str | None = None, valid_until: str | None = None,
) -> dict[str, Any]:
    return {
        "quote_id": quote_id, "series_id": series_id, "instrument_id": instrument_id,
        "base_asset": base_asset, "base_quantity": base_quantity, "quote_currency": quote_currency,
        "unit": unit, "quote_kind": quote_kind or (
            "venue_quote" if bid is not None or ask is not None else "market_reference"
        ),
        "bid": str(bid) if bid is not None else None,
        "ask": str(ask) if ask is not None else None,
        "reference": str(reference) if reference is not None else None,
        "mid": str((bid + ask) / Decimal("2")) if bid is not None and ask is not None else None,
        "source_id": source_id, "source_family": "telegram_verified_history",
        "source_observed_at": None, "collected_at": collected_at,
        "verification_status": "verified", "category": category, "display_name_fa": label,
        "valid_until": valid_until,
    }


def _snapshot(table: str, timestamp: str, quotes: list[dict[str, Any]]) -> dict[str, Any]:
    stamp = _utc(timestamp)
    material = json.dumps(quotes, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256((table + stamp + material).encode("utf-8")).hexdigest()[:20]
    payload = {
        "schema_version": "1", "snapshot_id": f"bot-{table}-{digest}",
        "collected_at": stamp, "quotes": quotes,
    }
    return validate_snapshot(payload)


def _groups(rows: list[sqlite3.Row], timestamp_col: str = "recorded_at_utc") -> dict[str, list[sqlite3.Row]]:
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[_utc(row[timestamp_col])].append(row)
    return grouped


def _read_rows(db: sqlite3.Connection, table: str, cursor: int, where: str = "") -> tuple[list[sqlite3.Row], int]:
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not exists:
        return [], cursor
    sql = f"SELECT * FROM {table} WHERE id > ? {where} ORDER BY id"
    rows = db.execute(sql, (cursor,)).fetchall()
    return rows, max([cursor, *(int(row["id"]) for row in rows)])


def collect_new_snapshots(source_path: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not source_path.is_file():
        raise FileNotFoundError(f"verified publisher database not found: {source_path}")
    website_path = database_path()
    cursors: dict[str, int] = {}
    if website_path.is_file():
        website_db = sqlite3.connect(website_path.resolve().as_uri() + "?mode=ro", uri=True)
        website_db.row_factory = sqlite3.Row
        website_db.execute("PRAGMA query_only = ON")
        try:
            exists = website_db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='import_cursors'"
            ).fetchone()
            if exists:
                cursors = {
                    row["source_name"]: int(row["last_row_id"])
                    for row in website_db.execute("SELECT * FROM import_cursors")
                }
        finally:
            website_db.close()
    source = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    source.execute("PRAGMA query_only = ON")
    try:
        payloads: list[dict[str, Any]] = []
        next_cursors: dict[str, int] = {}

        rows, next_id = _read_rows(source, "bank_fx_snapshots", cursors.get("bank_fx_snapshots", 0))
        for stamp, batch in _groups(rows).items():
            quotes = []
            for row in batch:
                pair = str(row["pair"]).upper()
                if pair not in {"USD/TRY", "EUR/TRY"}:
                    continue
                base = pair.split("/", 1)[0]
                market = str(row["market"])
                slug = _slug(market) or "market"
                quotes.append(_quote(
                    quote_id=f"bank_fx_snapshots:{row['id']}",
                    series_id=f"fx:{base.lower()}:{slug}:try:1:venue:v1",
                    instrument_id=f"fx:{base.lower()}", base_asset=base, quote_currency="TRY",
                    unit="currency-unit", category="turkey_fx",
                    label=f"{base}/TRY · {BANK_LABELS.get(market, market)}", collected_at=stamp,
                    source_id=f"verified-telegram:{slug}", bid=_decimal(row["buy"]), ask=_decimal(row["sell"]),
                ))
            if quotes:
                payloads.append(_snapshot("bank-fx", stamp, quotes))
        next_cursors["bank_fx_snapshots"] = next_id

        rows, next_id = _read_rows(source, "turkey_gold_snapshots", cursors.get("turkey_gold_snapshots", 0))
        for stamp, batch in _groups(rows).items():
            quotes = []
            for row in batch:
                key = str(row["asset_key"])
                if key not in TURKEY_GOLD:
                    continue
                slug, label = TURKEY_GOLD[key]
                quotes.append(_quote(
                    quote_id=f"turkey_gold_snapshots:{row['id']}",
                    series_id=f"gold:turkey:{slug}:try:venue:v1",
                    instrument_id=f"gold:turkey:{slug}", base_asset=label,
                    quote_currency="TRY", unit="gold-product", category="turkey_gold", label=label,
                    collected_at=stamp, source_id="verified-telegram:turkey-gold",
                    bid=_decimal(row["buy"]), ask=_decimal(row["sell"]),
                ))
            if quotes:
                payloads.append(_snapshot("turkey-gold", stamp, quotes))
        next_cursors["turkey_gold_snapshots"] = next_id

        rows, next_id = _read_rows(source, "iran_gold_snapshots", cursors.get("iran_gold_snapshots", 0))
        for stamp, batch in _groups(rows).items():
            quotes = []
            for row in batch:
                key = str(row["asset_key"])
                if key not in IRAN_GOLD:
                    continue
                slug, label, unit = IRAN_GOLD[key]
                toman = _decimal(row["price_rial"]) / Decimal("10")
                quotes.append(_quote(
                    quote_id=f"iran_gold_snapshots:{row['id']}",
                    series_id=f"gold:iran:{slug}:toman:reference:v1",
                    instrument_id=f"gold:iran:{slug}", base_asset=label,
                    quote_currency="TOMAN", unit=unit, category="iran_gold", label=label,
                    collected_at=stamp, source_id="verified-telegram:iran-gold", reference=toman,
                ))
            if quotes:
                payloads.append(_snapshot("iran-gold", stamp, quotes))
        next_cursors["iran_gold_snapshots"] = next_id

        rows, next_id = _read_rows(
            source, "published_value_snapshots", cursors.get("published_value_snapshots", 0),
            "AND board IN ('iran-fx', 'usdt-buy')",
        )
        for stamp, batch in _groups(rows).items():
            quotes = []
            for row in batch:
                board = str(row["board"])
                item = str(row["item"])
                value = _decimal(row["value"])
                if board == "iran-fx":
                    code = item.upper()
                    if code not in IRAN_FX_LABELS:
                        continue
                    quotes.append(_quote(
                        quote_id=f"published_value_snapshots:{row['id']}",
                        series_id=f"fx:{code.lower()}:iran-open:toman:reference:v1",
                        instrument_id=f"fx:{code.lower()}", base_asset=code,
                        quote_currency="TOMAN", unit="currency-unit", category="iran_fx",
                        label=IRAN_FX_LABELS[code], collected_at=stamp,
                        source_id="verified-telegram:iran-fx", reference=value,
                    ))
                elif board == "usdt-buy":
                    slug = _slug(item)
                    if not slug:
                        continue
                    label = USDT_EXCHANGES.get(slug, item)
                    quotes.append(_quote(
                        quote_id=f"published_value_snapshots:{row['id']}",
                        series_id=f"usdt:{slug}:toman:customer-ask:v1",
                        instrument_id="crypto:usdt", base_asset="USDT",
                        quote_currency="TOMAN", unit="token", category="usdt_exchange",
                        label=f"USDT · {label}", collected_at=stamp,
                        source_id=f"verified-telegram:usdt:{slug}", ask=value,
                    ))
            if quotes:
                payloads.append(_snapshot("published-values", stamp, quotes))
        next_cursors["published_value_snapshots"] = next_id

        # Use a separate cursor: the older importer advanced its shared cursor
        # past digest rows whenever a later Iran FX or USDT post was recorded.
        digest_cursor = "published_value_snapshots_daily_digest"
        rows, next_id = _read_rows(
            source, "published_value_snapshots", cursors.get(digest_cursor, 0),
            "AND board = 'daily-digest'",
        )
        for stamp, batch in _groups(rows).items():
            quotes = []
            for row in batch:
                key = str(row["item"]).upper()
                value = _decimal(row["value"])
                common = {
                    "quote_id": f"published_value_snapshots:{row['id']}",
                    "collected_at": stamp,
                    "source_id": "verified-telegram:daily-digest",
                    "reference": value,
                }
                if key in DIGEST_FX:
                    base_asset = "IQD" if key == "IQD100" else key
                    quotes.append(_quote(
                        **common, series_id=f"digest:fx:{key.lower()}:toman:reference:v1",
                        instrument_id=f"digest:fx:{key.lower()}", base_asset=base_asset,
                        base_quantity="100" if key == "IQD100" else "1",
                        quote_currency="TOMAN", unit="token" if key == "USDT" else "currency-unit",
                        category="daily_fx", label=DIGEST_FX[key],
                    ))
                elif key in DIGEST_GOLD:
                    slug, label, unit = DIGEST_GOLD[key]
                    currency = "USD" if key == "XAUUSD" else "TOMAN"
                    quotes.append(_quote(
                        **common, series_id=f"digest:gold:{slug}:{currency.lower()}:reference:v1",
                        instrument_id=f"digest:gold:{slug}", base_asset="XAU" if key == "XAUUSD" else label,
                        quote_currency=currency, unit=unit, category="daily_gold", label=label,
                    ))
                elif key in DIGEST_CRYPTO:
                    quotes.append(_quote(
                        **common, series_id=f"digest:crypto:{key.lower()}:usd:reference:v1",
                        instrument_id=f"crypto:{key.lower()}", base_asset=key,
                        quote_currency="USD", unit="token", category="crypto_global",
                        label=DIGEST_CRYPTO[key],
                    ))
            if quotes:
                payloads.append(_snapshot("daily-digest", stamp, quotes))
        next_cursors[digest_cursor] = next_id
        return payloads, next_cursors
    finally:
        source.close()


def collect_hawala_snapshot(path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Read only the fresh export written after successful hawala Telegram delivery."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("source") != "kiani-hawala":
        raise SnapshotError("hawala export has an unexpected source")
    generated = datetime.fromisoformat(str(data.get("generated_at", "")).replace("Z", "+00:00"))
    if generated.tzinfo is None:
        raise SnapshotError("hawala export needs a timezone")
    current = now or datetime.now(timezone.utc)
    age = (current.astimezone(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds()
    if not 0 <= age <= 900:
        raise SnapshotError("hawala export must be no older than 15 minutes")
    rates = data.get("rates")
    if not isinstance(rates, dict) or set(rates) != set(HAWALA_LABELS):
        raise SnapshotError("hawala export must contain all seven expected currencies")
    stamp = _utc(data["generated_at"])
    expiry = (generated.astimezone(timezone.utc) + timedelta(minutes=15)).isoformat(timespec="seconds")
    quotes = [
        _quote(
            quote_id=f"hawala:{code}", series_id=f"hawala:{code.lower()}:toman:payout:v1",
            instrument_id=f"hawala:{code.lower()}", base_asset=code,
            quote_currency="TOMAN", unit="currency-unit", category="kiani_hawala",
            label=HAWALA_LABELS[code], collected_at=stamp,
            source_id="verified-telegram:kiani-hawala", reference=_decimal(rates[code]),
            quote_kind="customer_rate", valid_until=expiry,
        )
        for code in HAWALA_LABELS
    ]
    return _snapshot("kiani-hawala", stamp, quotes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write new observations to the website database")
    args = parser.parse_args()
    raw_source = os.environ.get("ALANCHANDE_SOURCE_DB", "").strip()
    if not raw_source:
        parser.error("set ALANCHANDE_SOURCE_DB to the existing market history SQLite file")
    payloads, cursors = collect_new_snapshots(Path(raw_source))
    hawala_path = os.environ.get("ALANCHANDE_HAWALA_SNAPSHOT", "").strip()
    hawala_status = "not_configured"
    if hawala_path:
        try:
            payloads.append(collect_hawala_snapshot(Path(hawala_path)))
            hawala_status = "fresh_snapshot_included"
        except (OSError, ValueError, SnapshotError) as exc:
            # The hourly hawala export is normally older than 15 minutes.
            # Its absence must not hold up the independent market imports.
            hawala_status = f"skipped:{type(exc).__name__}"
            print(f"HAWALA SKIPPED: {exc}", file=sys.stderr)
    for payload in payloads:
        validate_snapshot(payload)
    summary = {
        "source_db_read_only": True,
        "website_db": str(database_path()),
        "mode": "apply" if args.apply else "dry-run",
        "snapshots": len(payloads),
        "quotes": sum(len(payload["quotes"]) for payload in payloads),
        "source_rows_through": cursors,
        "hawala": hawala_status,
        "no_social_posts_sent": True,
    }
    if args.apply:
        summary.update(ingest_snapshots(payloads, cursors=cursors))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, sqlite3.Error, SnapshotError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

