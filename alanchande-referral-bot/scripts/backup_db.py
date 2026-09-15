#!/usr/bin/env python3
"""Create a consistent SQLite backup with SHA-256 manifest and retention cleanup.

Usage under cron/Systemd/Supervisor environment:

    DB_PATH=/path/referral_bot.db \
    BACKUP_DIR=/path/offbox-or-synced-backups \
    python scripts/backup_db.py

SQLite's backup API is safe while the bot is running in WAL mode. For real
off-host protection, point BACKUP_DIR at a mounted remote volume or sync this
directory to a separate host/object store after each run.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    db_path = Path(os.environ.get("DB_PATH", "referral_bot.db")).expanduser().resolve()
    backup_dir = Path(os.environ.get("BACKUP_DIR", str(db_path.parent / "backups"))).expanduser().resolve()
    retention_days = max(1, int(os.environ.get("BACKUP_RETENTION_DAYS", "30")))

    if not db_path.exists():
        raise SystemExit(f"Database does not exist: {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"referral_bot-{stamp}.sqlite"
    temp = backup_dir / f".{target.name}.tmp"

    source = sqlite3.connect(str(db_path), timeout=30)
    destination = sqlite3.connect(str(temp), timeout=30)
    try:
        source.execute("PRAGMA busy_timeout=10000")
        source.backup(destination, pages=1000, sleep=0.05)
        destination.execute("PRAGMA integrity_check")
        destination.commit()
    finally:
        destination.close()
        source.close()

    temp.replace(target)
    digest = sha256_file(target)
    manifest = {
        "created_at": now.isoformat(),
        "source": str(db_path),
        "backup": str(target),
        "size_bytes": target.stat().st_size,
        "sha256": digest,
    }
    manifest_path = target.with_suffix(target.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    cutoff = time.time() - timedelta(days=retention_days).total_seconds()
    for old in backup_dir.glob("referral_bot-*.sqlite"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
            old.with_suffix(old.suffix + ".json").unlink(missing_ok=True)

    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
