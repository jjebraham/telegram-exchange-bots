#!/usr/bin/env python3
"""Install the approved carousel into Selenium's existing 11:30 cron publisher."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo


# This is the exact version successfully published and reviewed on Selenium.
APPROVED_REVISION = "821cba7ddd0a7361e98c048623ddf05fca672837"
FILES = (
    "instagram_daily_rates.py", "instagram_carousel.py",
    "fonts/Vazirmatn-Regular.ttf", "fonts/Vazirmatn-Bold.ttf", "fonts/OFL.txt",
    "assets/instagram/icons.png", "assets/instagram/icons.json",
    "assets/instagram/kiani-logo.svg", "assets/instagram/README.md",
    "assets/instagram/LICENSE-GRAPHICS",
)


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.home() / "telegram_bot_repo")
    args = parser.parse_args()
    home = Path.home()
    repo = args.repo.expanduser().resolve()
    publisher = home / "kiani-instagram-publisher"
    env_path = home / ".kiani-instagram.env"
    wrapper = home / "publish-kiani-instagram-rates.sh"
    if os.geteuid() == 0:
        raise ActivationError("Run as kianirad2020, without sudo.")
    for path in (env_path, wrapper, publisher / "instagram_daily_rates.py"):
        if path.is_symlink() or not path.is_file():
            raise ActivationError(f"Expected an existing regular file: {path}")
    if env_path.stat().st_uid != os.geteuid():
        raise ActivationError("Run as the owner of .kiani-instagram.env.")
    if not (home / "kiani-instagram-venv/bin/python").is_file():
        raise ActivationError("The existing Instagram virtual environment is missing.")

    clock_env = dict(os.environ)
    clock_env.pop("TZ", None)
    offset = subprocess.check_output(["date", "+%z"], text=True, env=clock_env).strip()
    if offset != "+0000":
        raise ActivationError("This activation expects the confirmed UTC server clock.")
    if subprocess.run(["systemctl", "is-active", "--quiet", "cron"]).returncode:
        raise ActivationError("The cron service must be active before activation.")
    script = wrapper.read_text(encoding="utf-8")
    if 'SCRIPT="$HOME/kiani-instagram-publisher/instagram_daily_rates.py"' not in script:
        raise ActivationError("The existing wrapper's publisher path has changed.")
    if '. "$HOME/.kiani-instagram.env"' not in script or "set -a" not in script:
        raise ActivationError("The wrapper must export the private environment settings.")
    if 'INSTAGRAM_STATE_FILE="$STATE_DIR/$mode.json"' not in script:
        raise ActivationError("The wrapper must retain separate Story and Feed state files.")
    subprocess.run(["bash", "-n", str(wrapper)], check=True)

    cron = subprocess.check_output(["crontab", "-l"], text=True)
    jobs = [line.strip() for line in cron.splitlines()
            if line.strip() and not line.lstrip().startswith("#") and str(wrapper) in line]
    wanted = (f"30 8 * * * {wrapper} publish >> "
              f"{home / 'kiani-instagram-cron.log'} 2>&1")
    if jobs != [wanted]:
        raise ActivationError("Expected one existing 08:30 UTC Instagram cron entry; configuration changed.")
    for line in cron.splitlines():
        match = re.match(r"^\s*CRON_TZ\s*=\s*(.*?)\s*$", line)
        if match and match.group(1).strip("\"'") not in ("UTC", "Etc/UTC", ""):
            raise ActivationError("A non-UTC CRON_TZ setting needs review before activation.")

    files: dict[Path, bytes] = {}
    for name in FILES:
        data = subprocess.check_output([
            "git", "-C", str(repo), "show", f"{APPROVED_REVISION}:{name}",
        ])
        if name.endswith(".py"):
            compile(data, name, "exec")
        target = publisher / name
        if target.is_symlink() or publisher.resolve() not in target.resolve().parents:
            raise ActivationError(f"Unexpected installation path: {target}")
        files[target] = data

    settings = {
        "INSTAGRAM_FEED_FORMAT": "carousel",
        "INSTAGRAM_TELEGRAM_REPO": str(repo),
        "INSTAGRAM_TELEGRAM_PYTHON": "/usr/bin/python3",
        "INSTAGRAM_MARKET_HISTORY_DB": str(repo / "channel_split/market_history_production.sqlite3"),
        "INSTAGRAM_HAWALA_SNAPSHOT": str(home / ".local/state/kiani-x/hawala.json"),
    }
    original_env = env_path.read_text(encoding="utf-8")
    lines = []
    for line in original_env.splitlines(keepends=True):
        match = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", line)
        if not match or match.group(1) not in settings:
            lines.append(line)
    updated_env = "".join(lines).rstrip("\n") + "\n"
    updated_env += "".join(f"{key}={shlex.quote(value)}\n" for key, value in settings.items())
    files[env_path] = updated_env.encode("utf-8")

    backup = Path(tempfile.mkdtemp(prefix="kiani-instagram-carousel-backup-", dir=home))
    backup.chmod(0o700)
    original: dict[Path, tuple[bytes, int] | None] = {}
    for path in files:
        saved = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
        original[path] = saved
        if saved is not None:
            atomic_write(backup / path.relative_to(home), saved[0], 0o600)
    atomic_write(backup / "crontab.txt", cron.encode("utf-8"), 0o600)
    atomic_write(backup / wrapper.name, wrapper.read_bytes(), 0o600)
    print(f"Backup: {backup}")

    changed: list[Path] = []
    try:
        for path, data in files.items():
            changed.append(path)
            atomic_write(path, data, 0o600 if path == env_path else 0o644)
        if subprocess.check_output(["crontab", "-l"], text=True) != cron:
            raise ActivationError("The crontab changed during activation; restoring the previous publisher.")
    except BaseException:
        for path in reversed(changed):
            saved = original[path]
            if saved is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, saved[0], saved[1])
        raise

    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    next_run = now.replace(hour=11, minute=30, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    print(f"Installed reviewed publisher: {APPROVED_REVISION}")
    print("Feed: carousel | Story: existing rate card")
    print("Daily schedule confirmed: 11:30 Europe/Istanbul (08:30 UTC)")
    print(f"Next scheduled run: {next_run:%Y-%m-%d %H:%M} Istanbul")
    print("Activation complete. The existing cron will use these settings on its next run.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ActivationError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

