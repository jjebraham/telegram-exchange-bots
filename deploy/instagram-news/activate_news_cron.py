#!/usr/bin/env python3
"""Install the reviewed news publisher and schedule it daily at 18:00 Istanbul."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo


# Both the explicit example and automatic selection were published from this revision.
APPROVED_REVISION = "f3a1fd016f8e471bbfbdfc3a7ee20f415cf1e37b"
APPROVED_SHARED_REVISION = "821cba7ddd0a7361e98c048623ddf05fca672837"
NEWS_FILES = ("instagram_crypto_news.py", "instagram_news_renderer.py")
SHARED_FILES = (
    "instagram_daily_rates.py", "fonts/Vazirmatn-Regular.ttf",
    "fonts/Vazirmatn-Bold.ttf", "assets/instagram/kiani-logo.svg",
)
MARKER = "# Kiani Instagram crypto news: daily 18:00 Europe/Istanbul (15:00 UTC)"

WRAPPER = r'''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export TZ=Europe/Istanbul
export PYTHONIOENCODING=utf-8

STATE_DIR="$HOME/.local/state/kiani-instagram-news"
umask 077
mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/publisher.lock"
if ! /usr/bin/flock -n 9; then
  printf '%s News publisher already running; skipped.\n' "$(date -Is)"
  exit 0
fi

set -a
. "$HOME/.kiani-instagram.env"
set +a
# Public JPEGs must remain readable by the web server.
umask 022

printf '%s Starting scheduled crypto news.\n' "$(date -Is)"
if "$HOME/kiani-instagram-venv/bin/python" -u \
  "$HOME/kiani-instagram-news-publisher/instagram_crypto_news.py" \
  --source-dir "$HOME/sub" \
  --publisher-root "$HOME/kiani-instagram-publisher" \
  --db "$STATE_DIR/news.sqlite3" \
  --output /var/www/peerexo.com/public/instagram-rates/news \
  --public-base https://peerexo.com/instagram-rates/news \
  --limit 1 --publish; then
  printf '%s Scheduled crypto news completed.\n' "$(date -Is)"
else
  result=$?
  printf '%s Scheduled crypto news failed (exit %s); see the preceding error.\n' "$(date -Is)" "$result" >&2
  exit "$result"
fi
'''


class ActivationError(RuntimeError):
    pass


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_cron() -> str:
    result = subprocess.run(["crontab", "-l"], text=True, capture_output=True, timeout=20)
    if result.returncode:
        raise ActivationError("Could not read the existing user crontab; no schedule was replaced.")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.home() / "telegram_bot_repo")
    args = parser.parse_args()
    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        raise ActivationError("Run on Selenium as the existing Instagram publisher user, without sudo.")
    home = Path.home().resolve()
    repo = args.repo.expanduser().resolve()
    shared = home / "kiani-instagram-publisher"
    news_root = home / "kiani-instagram-news-publisher"
    wrapper = home / "publish-kiani-instagram-news.sh"
    env_path = home / ".kiani-instagram.env"
    python = home / "kiani-instagram-venv/bin/python"
    db = home / ".local/state/kiani-instagram-news/news.sqlite3"
    output = Path("/var/www/peerexo.com/public/instagram-rates/news")
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    next_run = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    utc_run = next_run.astimezone(timezone.utc)
    if utc_run.hour != 15 or utc_run.minute != 0:
        raise ActivationError("Istanbul's timezone rules changed; review the UTC schedule.")

    for path in (env_path, db, *(home / "sub" / name for name in (
            "crypto_news_history.json", "translation_cache.json"))):
        if path.is_symlink() or not path.is_file() or not os.access(path, os.R_OK):
            raise ActivationError(f"Expected the existing readable file: {path}")
    if env_path.stat().st_uid != os.geteuid():
        raise ActivationError("Run as the owner of the existing Instagram environment.")
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ActivationError("The existing Instagram Python environment is missing.")
    if not os.access(db, os.W_OK) or not os.access(db.parent, os.W_OK):
        raise ActivationError("The existing news database must be writable by this user.")
    if not output.is_dir() or not os.access(output, os.W_OK):
        raise ActivationError("The public news image directory from the manual test is not writable.")
    if not Path("/usr/bin/flock").is_file():
        raise ActivationError("The existing system needs /usr/bin/flock for the publisher lock.")

    clock_env = dict(os.environ)
    clock_env.pop("TZ", None)
    server_zone = subprocess.check_output(
        ["timedatectl", "show", "--property=Timezone", "--value"],
        text=True, env=clock_env, timeout=20).strip()
    if server_zone not in {"UTC", "Etc/UTC", "GMT", "Etc/GMT"}:
        raise ActivationError("This activation expects the confirmed UTC server timezone.")
    if subprocess.run(["systemctl", "is-active", "--quiet", "cron"], timeout=20).returncode:
        raise ActivationError("The cron service must be active before scheduling.")

    original_cron = read_cron()
    for line in original_cron.splitlines():
        match = re.match(r"^\s*CRON_TZ\s*=\s*(.*?)\s*$", line)
        if match and match.group(1).strip("\"'") not in {"", "UTC", "Etc/UTC", "GMT", "Etc/GMT"}:
            raise ActivationError("A non-UTC CRON_TZ setting needs review before scheduling.")
    job = (f"0 15 * * * {shlex.quote(str(wrapper))} >> "
           f"{shlex.quote(str(home / 'kiani-instagram-news-cron.log'))} 2>&1")
    kept = []
    for line in original_cron.splitlines(keepends=True):
        if line.strip() == MARKER:
            continue
        if str(wrapper) in line and not line.lstrip().startswith("#"):
            if line.strip() != job:
                raise ActivationError("An unexpected existing news cron entry needs review before replacement.")
            continue
        kept.append(line)
    updated_cron = "".join(kept)
    if updated_cron and not updated_cron.endswith("\n"):
        updated_cron += "\n"
    updated_cron += MARKER + "\n" + job + "\n"

    # Reuse the installed fonts/logo and publishing helper without replacing rate files.
    for name in SHARED_FILES:
        expected = subprocess.check_output([
            "git", "-C", str(repo), "show", f"{APPROVED_SHARED_REVISION}:{name}"], timeout=20)
        if (shared / name).read_bytes() != expected:
            raise ActivationError(f"The shared publisher differs from the reviewed rate installation: {name}")

    files = {}
    for name in NEWS_FILES:
        data = subprocess.check_output([
            "git", "-C", str(repo), "show", f"{APPROVED_REVISION}:{name}"], timeout=20)
        compile(data, name, "exec")
        files[news_root / name] = (data, 0o644)
    files[news_root / "revision.txt"] = ((APPROVED_REVISION + "\n").encode(), 0o644)
    files[wrapper] = (WRAPPER.encode(), 0o700)
    subprocess.run(["bash", "-n"], input=WRAPPER, text=True, check=True, timeout=20)
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(home):
            raise ActivationError(f"Unexpected installation path: {path}")
        if path.exists() and not path.is_file():
            raise ActivationError(f"Expected a regular installation file: {path}")

    backup = Path(tempfile.mkdtemp(prefix="kiani-instagram-news-backup-", dir=home))
    backup.chmod(0o700)
    original = {}
    for path in files:
        saved = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
        original[path] = saved
        if saved is not None:
            atomic_write(backup / path.relative_to(home), saved[0], 0o600)
    atomic_write(backup / "crontab.txt", original_cron.encode(), 0o600)
    print(f"Backup: {backup}", flush=True)

    changed = []
    cron_attempted = False
    try:
        for path, (data, mode) in files.items():
            changed.append(path)
            atomic_write(path, data, mode)
        if read_cron() != original_cron:
            raise ActivationError("The crontab changed during installation; retry after reviewing it.")
        cron_attempted = True
        subprocess.run(["crontab", "-"], input=updated_cron, text=True, check=True, timeout=20)
        if read_cron() != updated_cron:
            raise ActivationError("The installed crontab did not match the requested schedule.")
    except BaseException:
        safe_to_restore_files = True
        if cron_attempted:
            try:
                current = read_cron()
                if current == updated_cron:
                    subprocess.run(["crontab", "-"], input=original_cron, text=True, check=True, timeout=20)
                elif current != original_cron:
                    safe_to_restore_files = False
            except Exception:
                safe_to_restore_files = False
        if safe_to_restore_files:
            for path in reversed(changed):
                saved = original[path]
                if saved is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, saved[0], saved[1])
        else:
            print("Crontab changed externally or could not be restored; installed files retained. Review the backup.", file=sys.stderr)
        raise

    print(f"Installed reviewed news publisher: {APPROVED_REVISION}")
    print("Selection: one highest-ranked unpublished story from the last 24 hours")
    print(f"Existing news database preserved: {db}")
    print("Daily schedule confirmed: 18:00 Europe/Istanbul (15:00 UTC)")
    print(f"Next scheduled run: {next_run:%Y-%m-%d %H:%M} Istanbul")
    print(f"News log: {home / 'kiani-instagram-news-cron.log'}")
    print("Activation complete. The next scheduled run will publish automatically.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ActivationError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
