"""Offline tests for migrating the legacy Hawala publisher safely."""
from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))
from migrate_legacy_hawala import transform_source  # noqa: E402


LEGACY_SOURCE = '''from typing import Dict

def calculate_hawala_rates():
    return {"TRY": 4610}


def build_hawala_message(rates: Dict[str, int]) -> str:
    lines = [
        get_persian_date(),
        "",
        "💱 نرخ حواله به ایران",
        "",
    ]
    for code, flag, name in HAWALA_CURRENCIES:
        lines.append("{} حواله {} به ایران: {} تومان".format(
            flag, name, _format_fa_number(rates[code])))
    lines.extend(["", HAWALA_CTA])
    return "\\n".join(lines)


def post_message(message: str) -> bool:
    if len(message) > TELEGRAM_MAX_LENGTH:
        return False
    if DRY_RUN:
        logger.info("DRY_RUN message:\\n%s", message)
        return True

    if TELEGRAM_BOT is None:
        logger.error("Telegram client is unavailable.")
        return False

    for attempt in range(1, TELEGRAM_ATTEMPTS + 1):
        try:
            TELEGRAM_BOT.send_message(
                TELEGRAM_CHANNEL_ID,
                message,
            )
            return True
        except Exception:
            pass
    return False
'''


def _source_of(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    return ast.get_source_segment(source, node)


class MigrationTests(unittest.TestCase):
    def test_migrates_only_formatter_and_delivery(self):
        patched = transform_source(LEGACY_SOURCE)
        ast.parse(patched)
        self.assertEqual(
            _source_of(LEGACY_SOURCE, "calculate_hawala_rates"),
            _source_of(patched, "calculate_hawala_rates"),
        )
        self.assertIn("from kiani_posts import build_kiani_remittance_post", patched)
        self.assertIn("now=datetime.now(TEHRAN)", patched)
        self.assertIn('TELEGRAM_CHANNEL_ID_RAW.casefold() != "@exchangekiani"', patched)
        self.assertIn('parse_mode="HTML"', patched)
        self.assertIn("disable_notification=True", patched)
        self.assertEqual(transform_source(patched), patched)

    def test_refuses_unknown_delivery_code(self):
        source = LEGACY_SOURCE.replace(
            "TELEGRAM_BOT.send_message(\n",
            "TELEGRAM_BOT.send_photo(\n",
        )
        with self.assertRaisesRegex(ValueError, "Unexpected Telegram delivery"):
            transform_source(source)

    def test_refuses_partially_migrated_code(self):
        with self.assertRaisesRegex(ValueError, "Partially migrated"):
            transform_source(LEGACY_SOURCE + "# HAWALA_KIANI_HTML_SEND_V1")

    def test_cli_preflight_then_apply_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "hawala_bot.py"
            file.write_text(LEGACY_SOURCE, encoding="utf-8")
            script = ROOT / "channel_split" / "migrate_legacy_hawala.py"

            before = subprocess.run(
                [sys.executable, str(script), "--bot-file", str(file)],
                text=True, capture_output=True, check=True,
            )
            self.assertIn("PATCH CHECK: READY", before.stdout)
            self.assertEqual(file.read_text(encoding="utf-8"), LEGACY_SOURCE)

            applied = subprocess.run(
                [sys.executable, str(script), "--bot-file", str(file), "--apply"],
                text=True, capture_output=True, check=True,
            )
            self.assertIn("PATCH APPLIED", applied.stdout)
            self.assertIn("parse_mode=\"HTML\"", file.read_text(encoding="utf-8"))
            backups = list(Path(directory).glob("hawala_bot.py.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), LEGACY_SOURCE)


if __name__ == "__main__":
    unittest.main()
