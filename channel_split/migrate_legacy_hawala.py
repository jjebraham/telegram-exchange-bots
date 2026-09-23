#!/usr/bin/env python3
"""Stage the legacy Hawala bot's Kiani-only post migration.

This script patches only the message formatter and Telegram send method in
/home/kianirad2020/kiani-hawala-bot/hawala_bot.py.  It leaves the existing rate
calculation, shared pricing runtime, scheduler, slot database and alert routing
untouched.  The bot must be stopped and its Supervisor destination changed to
@ExchangeKiani before restarting.  No Telegram requests are made here.

Default mode performs validation only; --apply writes a timestamped backup and
updates the source atomically.  Unknown or partially modified source fails
closed rather than attempting a broad textual replacement.
"""
from __future__ import annotations

import argparse
import ast
import os
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_BOT_FILE = Path("/home/kianirad2020/kiani-hawala-bot/hawala_bot.py")
FORMATTER_MARKER = "HAWALA_KIANI_FORMATTER_V1"
DESTINATION_MARKER = "HAWALA_KIANI_CHANNEL_GUARD_V1"
HTML_MARKER = "HAWALA_KIANI_HTML_SEND_V1"

FORMATTER_FUNCTION = '''def build_hawala_message(rates: Dict[str, int]) -> str:
    # HAWALA_KIANI_FORMATTER_V1: single Kiani format, old pricing unchanged.
    import sys

    posts_dir = os.environ.get(
        "HAWALA_KIANI_POSTS_DIR",
        "/home/kianirad2020/telegram_bot_repo/channel_split",
    )
    if posts_dir not in sys.path:
        sys.path.insert(0, posts_dir)
    from kiani_posts import build_kiani_remittance_post

    return build_kiani_remittance_post(
        {code: Decimal(str(value)) for code, value in rates.items()},
        now=datetime.now(TEHRAN),
    )
'''

OLD_SEND = '''            TELEGRAM_BOT.send_message(
                TELEGRAM_CHANNEL_ID,
                message,
            )'''
NEW_SEND = '''            # HAWALA_KIANI_HTML_SEND_V1
            TELEGRAM_BOT.send_message(
                TELEGRAM_CHANNEL_ID,
                message,
                parse_mode="HTML",
                disable_notification=True,
            )'''

OLD_CLIENT_CHECK = '''    if TELEGRAM_BOT is None:
        logger.error("Telegram client is unavailable.")
        return False'''
NEW_CLIENT_CHECK = '''    # HAWALA_KIANI_CHANNEL_GUARD_V1: never resume old AlanChande posts.
    if not DRY_RUN and TELEGRAM_CHANNEL_ID_RAW.casefold() != "@exchangekiani":
        logger.error("Refusing remittance delivery outside @ExchangeKiani")
        return False

    if TELEGRAM_BOT is None:
        logger.error("Telegram client is unavailable.")
        return False'''


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    matches = [
        node for node in getattr(tree, "body", [])
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one top-level {name} function")
    return matches[0]


def transform_source(source: str) -> str:
    markers = (FORMATTER_MARKER, DESTINATION_MARKER, HTML_MARKER)
    present = [marker in source for marker in markers]
    if all(present):
        return source  # Already fully migrated.
    if any(present):
        raise ValueError("Partially migrated source; review manually")

    tree = ast.parse(source)
    format_fn = _function(tree, "build_hawala_message")
    send_fn = _function(tree, "post_message")
    if format_fn.end_lineno is None or send_fn.end_lineno is None:
        raise ValueError("Cannot identify function boundaries")
    if "get_persian_date()" not in ast.get_source_segment(source, format_fn):
        raise ValueError("Unexpected original remittance formatter")
    send_segment = ast.get_source_segment(source, send_fn)
    if (send_segment.count(OLD_SEND) != 1 or
            send_segment.count(OLD_CLIENT_CHECK) != 1):
        raise ValueError("Unexpected Telegram delivery implementation")
    lines = source.splitlines(keepends=True)
    lines[format_fn.lineno - 1:format_fn.end_lineno] = [FORMATTER_FUNCTION + "\n"]
    updated = "".join(lines)

    if updated.count(OLD_SEND) != 1 or updated.count(OLD_CLIENT_CHECK) != 1:
        raise ValueError("Original send method not unique")
    updated = updated.replace(OLD_SEND, NEW_SEND, 1)
    updated = updated.replace(OLD_CLIENT_CHECK, NEW_CLIENT_CHECK, 1)
    ast.parse(updated)
    if not all(marker in updated for marker in markers):
        raise ValueError("Migration markers missing")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bot-file", type=Path, default=DEFAULT_BOT_FILE)
    parser.add_argument("--apply", action="store_true",
                        help="Back up and atomically patch the old bot")
    args = parser.parse_args()
    path = args.bot_file
    original_stat = path.stat()
    original = path.read_text(encoding="utf-8")
    updated = transform_source(original)

    if original == updated:
        print("ALREADY MIGRATED: no changes needed")
        return 0
    if not args.apply:
        print("PATCH CHECK: READY (no changes made)")
        print("Will replace only build_hawala_message and post_message.")
        print("Will guard against publishing outside @ExchangeKiani.")
        print("Keep the legacy bot stopped until destination is updated.")
        return 0

    current_stat = path.stat()
    if (
        current_stat.st_ino != original_stat.st_ino
        or current_stat.st_size != original_stat.st_size
        or current_stat.st_mtime_ns != original_stat.st_mtime_ns
    ):
        raise RuntimeError("Source changed while preparing migration; aborting")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.backup-{stamp}")
    if backup.exists():
        raise RuntimeError(f"Backup already exists: {backup}")
    shutil.copy2(path, backup)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".hawala-bot-migration-", delete=False,
        ) as output:
            output.write(updated)
            temp_name = output.name
        os.chmod(temp_name, stat.S_IMODE(original_stat.st_mode))
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    print(f"PATCH APPLIED: {path}")
    print(f"BACKUP: {backup}")
    print("NEXT: set Supervisor TELEGRAM_CHANNEL_ID=@ExchangeKiani,")
    print("then restart ONLY kiani_hawala_bot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
