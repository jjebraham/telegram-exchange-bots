#!/usr/bin/env python3
"""Create, verify, and optionally sync consistent SQLite backups.

Normal local backup:

    DB_PATH=/path/referral_bot.db BACKUP_DIR=/path/backups \
    python scripts/backup_db.py

Optional off-server copy using rclone:

    BACKUP_RCLONE_DEST='remote:alanchande-backups' python scripts/backup_db.py

Restore/integrity test of the newest local backup:

    RESTORE_TEST=1 python scripts/backup_db.py

Optional Telegram failure alerts use BOT_TOKEN plus BACKUP_ALERT_CHAT_ID. If the
chat ID is omitted, the first ADMIN_IDS value is used. BACKUP_ALERT_ON_SUCCESS=1
can be enabled for success notices, but failures are alerted automatically when
credentials are available.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
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


def alert_chat_id() -> str:
    explicit = os.environ.get("BACKUP_ALERT_CHAT_ID", "").strip()
    if explicit:
        return explicit
    admins = os.environ.get("ADMIN_IDS", "").split(",")
    return admins[0].strip() if admins and admins[0].strip() else ""


def send_telegram_alert(text: str) -> None:
    token = os.environ.get("BOT_TOKEN", "").strip()
    chat_id = alert_chat_id()
    if not token or not chat_id:
        return
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
    except Exception as exc:
        print(json.dumps({"backup_alert_error": str(exc)}, sort_keys=True))


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
        "remote_uploaded": bool(manifest.get("remote_uploaded")),
        "remote_destination": manifest.get("remote_destination", ""),
    }


def create_backup(db_path: Path, backup_dir: Path, retention_days: int) -> tuple[dict, Path]:
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
        "remote_uploaded": False,
        "remote_destination": "",
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

    return manifest, target


def sync_remote(target: Path, manifest: dict, remote_dest: str) -> dict:
    executable = shutil.which("rclone")
    if not executable:
        raise RuntimeError("BACKUP_RCLONE_DEST is configured but rclone is not installed")
    remote_base = remote_dest.rstrip("/")
    remote_db = f"{remote_base}/{target.name}"
    subprocess.run(
        [executable, "copyto", str(target), remote_db, "--retries", "3", "--low-level-retries", "5"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=600,
    )
    manifest["remote_uploaded"] = True
    manifest["remote_destination"] = remote_db
    manifest["remote_uploaded_at"] = datetime.now(UTC).isoformat()
    manifest_path = target.with_suffix(target.suffix + ".json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    subprocess.run(
        [
            executable, "copyto", str(manifest_path),
            f"{remote_base}/{manifest_path.name}", "--retries", "3", "--low-level-retries", "5",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300,
    )
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

    try:
        manifest, target = create_backup(db_path, backup_dir, retention_days)
        remote_dest = os.environ.get("BACKUP_RCLONE_DEST", "").strip()
        if remote_dest:
            manifest = sync_remote(target, manifest, remote_dest)
        print(json.dumps(manifest, sort_keys=True))
        if truthy("BACKUP_ALERT_ON_SUCCESS"):
            remote = " + off-server" if manifest.get("remote_uploaded") else ""
            send_telegram_alert(
                f"✅ AlanChande backup OK{remote}\n{target.name}\nSHA-256: {manifest['sha256']}"
            )
    except SystemExit as exc:
        send_telegram_alert(f"❌ AlanChande backup failed\n{exc}")
        raise
    except Exception as exc:
        send_telegram_alert(f"❌ AlanChande backup failed\n{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
