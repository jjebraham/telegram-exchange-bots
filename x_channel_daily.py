#!/usr/bin/env python3
"""Once-daily compact X posts; intended for the Telegram production host.

An uncertain X write is left reserved for manual reconciliation, never retried
automatically. Dry runs neither open the delivery database nor send messages.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from x_channel_formats import POST_TYPES, render
from x_daily_rates import publish_to_x
from x_post_policy import inspect_text, validate_text

ROOT = Path(__file__).resolve().parent


def collect(post, hawala_snapshot=None):
    if post == "kiani-hawala":
        if not hawala_snapshot:
            raise ValueError("Hawala requires a fresh snapshot from the existing hawala rate service")
        data = json.loads(Path(hawala_snapshot).read_text(encoding="utf-8"))
        when = datetime.fromisoformat(data["generated_at"])
        if when.tzinfo is None:
            raise ValueError("Hawala snapshot timestamp must include timezone")
        age = (datetime.now(timezone.utc) - when).total_seconds()
        if data.get("source") != "kiani-hawala" or not 0 <= age <= 900:
            raise ValueError("Hawala snapshot must come from kiani-hawala and be at most 15 minutes old")
        sys.path.insert(0, str(ROOT / "channel_split"))
        from kiani_posts import build_kiani_remittance_post
        return build_kiani_remittance_post({k: Decimal(str(v)) for k, v in data["rates"].items()})
    env = dict(os.environ, MARKET_SAFETY_MODE="enforce", PYTHONIOENCODING="utf-8")
    env.setdefault("MARKET_HISTORY_DB", str(ROOT / "channel_split" / "market_history_production.sqlite3"))
    # Some history readers initialize tables. Give collection a SQLite backup
    # so even schema initialization cannot change Telegram production history.
    with tempfile.TemporaryDirectory(prefix="kiani-x-history-") as tmp:
        history = Path(env["MARKET_HISTORY_DB"])
        if not history.is_absolute():
            history = ROOT / "channel_split" / history
        snapshot = Path(tmp) / "history.sqlite3"
        if history.exists():
            with closing(sqlite3.connect(history.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(snapshot)) as target:
                    source.backup(target)
        env["MARKET_HISTORY_DB"] = str(snapshot)
        result = subprocess.run(
            [sys.executable, str(ROOT / "channel_split" / "publish_channels.py"),
             "--post", post, "--export-json"], cwd=ROOT / "channel_split",
            env=env, capture_output=True, text=True, encoding="utf-8", timeout=420,
        )
    if result.returncode:
        raise RuntimeError("Verified collection failed: " + result.stderr[-1500:])
    data = json.loads(result.stdout)
    if data.get("post") != post or data.get("verified") is not True:
        raise ValueError("Unverified or mismatched X export")
    return data["text"]


def deliver(post, text, state_file, *, now=None, sender=publish_to_x):
    text = validate_text(text)
    day = (now or datetime.now(ZoneInfo("Europe/Istanbul"))).astimezone(
        ZoneInfo("Europe/Istanbul")).date().isoformat()
    Path(state_file).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(state_file, timeout=30)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS deliveries (day TEXT, post TEXT, status TEXT, text TEXT, post_id TEXT, PRIMARY KEY(day, post))")
        inserted = db.execute("INSERT OR IGNORE INTO deliveries VALUES (?, ?, 'reserved', ?, NULL)",
                              (day, post, text)).rowcount
        db.commit()  # Reserve durably BEFORE making a non-idempotent X request.
        if not inserted:
            return "already sent or reserved; inspect state before retrying"
        result = sender(text)  # Any failure retains the reservation for reconciliation.
        post_id = result.get("data", {}).get("id")
        if not post_id:
            raise RuntimeError("X response lacks post ID; reservation retained")
        db.execute("UPDATE deliveries SET status='sent', post_id=? WHERE day=? AND post=?",
                   (post_id, day, post))
        db.commit()
    return "published " + post_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post", required=True, choices=POST_TYPES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--state-file", default=os.getenv("X_CHANNEL_STATE_FILE", ".x-channel-state/deliveries.sqlite3"))
    parser.add_argument("--hawala-snapshot", default=os.getenv("X_HAWALA_SNAPSHOT"))
    args = parser.parse_args()
    text = render(args.post, collect(args.post, args.hawala_snapshot))
    if args.dry_run:
        print(json.dumps({"post": args.post, "weighted_length": inspect_text(text)["weightedLength"],
                          "text": text}, ensure_ascii=False, indent=2))
        return 0
    print(deliver(args.post, text, args.state_file))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
