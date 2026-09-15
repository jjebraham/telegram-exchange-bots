#!/usr/bin/env python3
"""Create and verify consistent SQLite backups.

Normal backup:

    DB_PATH=/path/referral_bot.db BACKUP_DIR=/path/backups \
    python scripts/backup_db.py

Restore/integrity test of the newest backup:

    DB_PATH=/path/referral_bot.db BACKUP_DIR=/path/backups RESTORE_TEST=1 \
    python scripts/backup_db.py

Set BACKUP_FILE=/path/file.sqlite together with RESTORE_TEST=1 to test a
specific snapshot. SQLite's backup API is safe while the live bot is running in
WAL mode. BACKUP_RETENTION_DAYS defaults to 30.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
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


def truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def latest_backup(backup_dir: Path) -> Path:
    files = sorted(
        backup_dir.glob("referral_bot-*.sqlite"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise SystemExit(f"No backups found in {backup_dir}")
    return files[0]


def verify_backup(backup: Path) -> dict:
    if not backup.exists():
        raise SystemExit(f"Backup does not exist: {backup}")

    digest = sha256_file(backup)
    manifest_path = backup.with_suffix(backup.suffix + ".json")
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest.get("sha256")
        if expected and expected != digest:
            raise SystemExit("Backup SHA-256 does not match its manifest")

    # Copy the snapshot to a disposable path and open that copy. This exercises
    # the restore path without ever touching the production DB.
    with tempfile.TemporaryDirectory(prefix="alanchande-restore-") as temp_dir:
        restored = Path(temp_dir) / "restored.sqlite"
        shutil.copy2(backup, restored)
        conn = sqlite3.connect(str(restored), timeout=30)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise SystemExit(f"SQLite integrity_check failed: {integrity}")
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            required = {"campaigns", "users", "invite_links", "referrals", "draws"}
            missing = sorted(required - tables)
            if missing:
                raise SystemExit(f"Restore is missing required tables: {', '.join(missing)}")
            counts = {
                "campaigns": conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0],
                "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "referrals": conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0],
            }
        finally:
            conn.close()

    return {
        "backup": str(backup),
        "sha256": digest,
        "integrity_check": "ok",
        "counts": counts,
        "restore_test": "passed",
        "manifest_present": bool(manifest),
    }


def create_backup(db_path: Path, backup_dir: Path, retention_days: int) -> dict:
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
        check = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"backup integrity_check failed: {check}")
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
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    cutoff = time.time() - timedelta(days=retention_days).total_seconds()
    for old in backup_dir.glob("referral_bot-*.sqlite"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
            old.with_suffix(old.suffix + ".json").unlink(missing_ok=True)

    return manifest


def main() -> None:
    db_path = Path(os.environ.get("DB_PATH", "referral_bot.db")).expanduser().resolve()
    backup_dir = Path(
        os.environ.get("BACKUP_DIR", str(db_path.parent / "backups"))
    ).expanduser().resolve()
    retention_days = max(1, int(os.environ.get("BACKUP_RETENTION_DAYS", "30")))

    if truthy("RESTORE_TEST"):
        requested = os.environ.get("BACKUP_FILE", "").strip()
        backup = Path(requested).expanduser().resolve() if requested else latest_backup(backup_dir)
        print(json.dumps(verify_backup(backup), sort_keys=True))
        return

    print(json.dumps(create_backup(db_path, backup_dir, retention_days), sort_keys=True))


if __name__ == "__main__":
    main()
