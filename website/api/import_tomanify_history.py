"""Archive public Tomanify free-market snapshots in the website SQLite store.

The upstream JSON is a latest-value file rather than a historical API. Its
public Git history preserves versions of data.json, so this importer uses
GitHub's file-specific commit list and the immutable raw file at each commit.
Chart timestamps are GitHub archive commit times, not claimed market
observation times; the feed only publishes a calendar date for observations.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from data_foundation.snapshot import SnapshotError, validate_snapshot
from api.store import imported_snapshot_ids, ingest_snapshots


REPOSITORY = "rate-json/default"
COMMITS_URL = f"https://api.github.com/repos/{REPOSITORY}/commits"
RAW_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/{{sha}}/data.json"
SOURCE_PREFIX = "tomanify-"
SOURCE_ID = "tomanify:rate-json-default"
SOURCE_FAMILY = "public_market_provider"
MAX_HISTORY_COMMITS = 1500
PER_PAGE = 100
HTTP_TIMEOUT_SECONDS = 25
MAX_RESPONSE_BYTES = 1_000_000
MAX_WORKERS = 5
SUPPORTED_CURRENCIES = {
    "USD": "دلار آمریکا", "EUR": "یورو", "AED": "درهم امارات",
    "TRY": "لیر ترکیه", "CNY": "یوان چین",
}
REQUEST_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "alanchande-public-market-history/1.0",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _fetch_json(url: str) -> Any:
    request = Request(url, headers=REQUEST_HEADERS)
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SnapshotError(f"upstream request failed: {getattr(exc, 'code', type(exc).__name__)}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise SnapshotError("upstream response exceeded the size limit")
    try:
        return json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("upstream response was not valid JSON") from exc


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise SnapshotError(f"{field} must be an RFC3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError(f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _price_string(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise SnapshotError("Tomanify values must be integer or decimal numbers")
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SnapshotError("Tomanify rate was not numeric") from exc
    if not number.is_finite() or number <= 0:
        raise SnapshotError("Tomanify rate must be finite and positive")
    result = format(number, "f")
    if len(result) > 32:
        raise SnapshotError("Tomanify rate was outside the supported size")
    return result


def _source_reported_date(payload: dict[str, Any]) -> date:
    """Read current date-only and legacy timezone-unspecified Tomanify fields."""
    generated = payload.get("generated_by_tomanify_at")
    if isinstance(generated, str):
        try:
            reported = date.fromisoformat(generated)
        except ValueError as exc:
            raise SnapshotError("Tomanify generated date must be YYYY-MM-DD") from exc
        if reported.isoformat() != generated:
            raise SnapshotError("Tomanify generated date must be YYYY-MM-DD")
        return reported
    if generated is not None:
        raise SnapshotError("Tomanify generated date must be YYYY-MM-DD")

    legacy = payload.get("generated_at")
    if isinstance(legacy, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", legacy):
        try:
            reported = date.fromisoformat(legacy)
        except ValueError as exc:
            raise SnapshotError("Tomanify legacy generated_at date was invalid") from exc
        if reported.isoformat() == legacy:
            return reported
    if isinstance(legacy, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", legacy
    ):
        try:
            return datetime.strptime(legacy, "%Y-%m-%d %H:%M:%S").date()
        except ValueError as exc:
            raise SnapshotError("Tomanify legacy generated_at timestamp was invalid") from exc
    raise SnapshotError(
        "Tomanify snapshot must contain generated_by_tomanify_at (YYYY-MM-DD) "
        "or legacy generated_at (YYYY-MM-DD HH:MM:SS)"
    )


def build_snapshot(payload: Any, sha: str, archived_at: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Validate one immutable archived data.json version and map its currencies."""
    if not isinstance(payload, dict):
        raise SnapshotError("Tomanify response must be a JSON object")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise SnapshotError("GitHub commit SHA must be 40 lowercase hexadecimal characters")
    reported_date = _source_reported_date(payload)
    values = payload.get("values")
    if not isinstance(values, dict):
        raise SnapshotError("Tomanify values must be an object")

    collected = _timestamp(archived_at, "archived_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if collected > current:
        raise SnapshotError("archive commit time cannot be in the future")
    stamp = collected.isoformat()
    archive_expiry = collected + timedelta(hours=8)
    reported_date_expiry = datetime.combine(
        reported_date + timedelta(days=1), datetime.min.time(), timezone.utc
    ) + timedelta(hours=12)
    valid_until = min(archive_expiry, reported_date_expiry).isoformat()
    quotes: list[dict[str, Any]] = []
    for code, label in SUPPORTED_CURRENCIES.items():
        if code not in values:
            continue
        amount = _price_string(values[code])
        quotes.append({
            "quote_id": f"tomanify:{sha}:{code.lower()}",
            "series_id": f"fx:{code.lower()}:iran-open:toman:tomanify:v1",
            "instrument_id": f"fx:{code.lower()}",
            "base_asset": code,
            "base_quantity": "1",
            "quote_currency": "TOMAN",
            "unit": "currency-unit",
            "quote_kind": "market_reference",
            "bid": None,
            "ask": None,
            "reference": amount,
            "mid": None,
            "source_id": SOURCE_ID,
            "source_family": SOURCE_FAMILY,
            # The feed gives a date but not an exact market-observation time.
            "source_observed_at": None,
            "source_reported_date": reported_date.isoformat(),
            # The GitHub file-history commit timestamp is the archive time.
            "collected_at": stamp,
            "verification_status": "source_published",
            "valid_until": valid_until,
            "category": "iran_fx",
            "display_name_fa": f"{code} · {label} · Tomanify",
            "methodology_version": "tomanify-github-archive-commit-time-v1",
        })
    if not quotes:
        raise SnapshotError("Tomanify snapshot did not contain a supported currency rate")

    snapshot = {
        "schema_version": "1",
        "snapshot_id": f"{SOURCE_PREFIX}{sha}",
        "collected_at": stamp,
        "quotes": quotes,
    }
    return validate_snapshot(snapshot, now=current)


def _commit_time(commit: dict[str, Any]) -> str:
    data = commit.get("commit")
    if not isinstance(data, dict):
        raise SnapshotError("GitHub commit entry was malformed")
    committer = data.get("committer")
    author = data.get("author")
    value = committer.get("date") if isinstance(committer, dict) else None
    if value is None and isinstance(author, dict):
        value = author.get("date")
    if not isinstance(value, str):
        raise SnapshotError("GitHub commit did not include an archive time")
    return value


def collect_new_snapshots(limit: int = MAX_HISTORY_COMMITS) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if limit < 1 or limit > MAX_HISTORY_COMMITS:
        raise ValueError(f"limit must be between 1 and {MAX_HISTORY_COMMITS}")
    known = imported_snapshot_ids(SOURCE_PREFIX)
    commits: list[dict[str, str]] = []
    page = 1
    stopped_at_known = False
    while len(commits) < limit:
        query = urlencode({"path": "data.json", "per_page": PER_PAGE, "page": page})
        result = _fetch_json(f"{COMMITS_URL}?{query}")
        if not isinstance(result, list):
            raise SnapshotError("GitHub commit history response was malformed")
        if not result:
            break
        for item in result:
            if not isinstance(item, dict) or not isinstance(item.get("sha"), str):
                raise SnapshotError("GitHub commit entry was malformed")
            sha = item["sha"]
            if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
                raise SnapshotError("GitHub commit SHA was malformed")
            snapshot_id = f"{SOURCE_PREFIX}{sha}"
            if snapshot_id in known:
                stopped_at_known = True
                break
            commits.append({"sha": sha, "archived_at": _commit_time(item)})
            if len(commits) >= limit:
                break
        if stopped_at_known or len(result) < PER_PAGE or len(commits) >= limit:
            break
        page += 1

    # The provider API lists newest commits first; fetch immutable files in a
    # small bounded pool, then ingest in chronological order.
    commits.reverse()
    snapshots_by_index: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_json, RAW_URL.format(sha=item["sha"])): (index, item)
            for index, item in enumerate(commits)
        }
        for future in as_completed(futures):
            index, item = futures[future]
            snapshots_by_index[index] = build_snapshot(
                future.result(), item["sha"], item["archived_at"]
            )
    snapshots = [snapshots_by_index[index] for index in range(len(commits))]
    return snapshots, {
        "commit_count": len(commits),
        "pages_read": page,
        "stopped_at_existing_snapshot": stopped_at_known,
        "history_limit_reached": len(commits) >= limit and not stopped_at_known,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write new source snapshots to the website SQLite database")
    parser.add_argument("--limit", type=int, default=MAX_HISTORY_COMMITS, help="maximum upstream snapshots to backfill")
    args = parser.parse_args()
    try:
        snapshots, scan = collect_new_snapshots(args.limit)
        result = ingest_snapshots(snapshots) if args.apply else {
            "inserted_snapshots": 0,
            "already_present": 0,
            "quotes": sum(len(item["quotes"]) for item in snapshots),
        }
    except (OSError, SnapshotError, ValueError) as exc:
        print(f"Tomanify history import failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "source": SOURCE_ID,
        "mode": "apply" if args.apply else "dry_run",
        **scan,
        **result,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
