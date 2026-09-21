import io
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

import publish_channels  # noqa: E402
from bank_compare import BankQuote  # noqa: E402
from market_safety import load_last_accepted, recent_safety_status  # noqa: E402


class PublisherSafetyModeTests(unittest.TestCase):
    def _env(self, db_path: Path, mode: str) -> dict[str, str]:
        return {
            "MARKET_HISTORY_DB": str(db_path),
            "MARKET_SAFETY_MODE": mode,
            "ALANCHANDE_TELEGRAM_BOT_TOKEN": "test-token",
            "ALANCHANDE_CHANNEL_ID": "@test-channel",
            "ALANCHANDE_ADMIN_CHAT_ID": "",
            "ALANCHANDE_ADMIN_BOT_TOKEN": "",
        }

    def _quote(self) -> BankQuote:
        return BankQuote(
            name="Kapalıçarşı",
            buy=Decimal("48.69"),
            sell=Decimal("48.71"),
        )

    def test_enforce_blocked_post_never_calls_telegram(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "history.sqlite3"
            argv = ["publish_channels.py", "--post", "bank-comparison"]

            with (
                patch.object(sys, "argv", argv),
                patch.dict(os.environ, self._env(db, "enforce"), clear=False),
                patch.object(
                    publish_channels,
                    "fetch_usd_comparison",
                    return_value=[self._quote()],
                ),
                patch.object(
                    publish_channels,
                    "fetch_altinkaynak_currency_quotes",
                    side_effect=TimeoutError("verifier unavailable"),
                ),
                patch.object(publish_channels, "telegram_send") as telegram_send,
                patch("sys.stdout", new_callable=io.StringIO),
                patch("sys.stderr", new_callable=io.StringIO),
            ):
                result = publish_channels.main()

            self.assertEqual(result, 0)
            telegram_send.assert_not_called()

            status = recent_safety_status(db)
            self.assertIn("BLOCKED", status)
            self.assertIn("published=0", status)
            self.assertIn("altinkaynak-currency", status)

    def test_shadow_blocked_post_sends_but_never_becomes_accepted_baseline(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "history.sqlite3"
            argv = ["publish_channels.py", "--post", "bank-comparison"]

            with (
                patch.object(sys, "argv", argv),
                patch.dict(os.environ, self._env(db, "shadow"), clear=False),
                patch.object(
                    publish_channels,
                    "fetch_usd_comparison",
                    return_value=[self._quote()],
                ),
                patch.object(
                    publish_channels,
                    "fetch_altinkaynak_currency_quotes",
                    side_effect=TimeoutError("verifier unavailable"),
                ),
                patch.object(
                    publish_channels,
                    "telegram_send",
                    return_value={"ok": True},
                ) as telegram_send,
                patch.object(
                    publish_channels,
                    "record_bank_fx_quotes",
                    return_value="unexpected",
                ) as record_bank_fx_quotes,
                patch("sys.stdout", new_callable=io.StringIO),
                patch("sys.stderr", new_callable=io.StringIO),
            ):
                result = publish_channels.main()

            self.assertEqual(result, 0)
            telegram_send.assert_called_once()
            record_bank_fx_quotes.assert_not_called()
            self.assertIsNone(
                load_last_accepted(db, "bank:USD/TRY:Kapalıçarşı:buy")
            )
            status = recent_safety_status(db)
            self.assertIn("BLOCKED", status)
            self.assertIn("published=1", status)

    def test_enforce_verified_post_is_sent_and_becomes_baseline(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "history.sqlite3"
            argv = ["publish_channels.py", "--post", "bank-comparison"]

            with (
                patch.object(sys, "argv", argv),
                patch.dict(os.environ, self._env(db, "enforce"), clear=False),
                patch.object(
                    publish_channels,
                    "fetch_usd_comparison",
                    return_value=[self._quote()],
                ),
                patch.object(
                    publish_channels,
                    "fetch_altinkaynak_currency_quotes",
                    return_value={
                        "USD/TRY": (Decimal("48.69"), Decimal("48.71"))
                    },
                ),
                patch.object(
                    publish_channels,
                    "telegram_send",
                    return_value={"ok": True},
                ) as telegram_send,
                patch.object(
                    publish_channels,
                    "record_bank_fx_quotes",
                    return_value="2026-09-22T00:00:00+00:00",
                ) as record_bank_fx_quotes,
                patch("sys.stdout", new_callable=io.StringIO),
                patch("sys.stderr", new_callable=io.StringIO),
            ):
                result = publish_channels.main()

            self.assertEqual(result, 0)
            telegram_send.assert_called_once()
            record_bank_fx_quotes.assert_called_once()
            self.assertEqual(
                load_last_accepted(db, "bank:USD/TRY:Kapalıçarşı:buy"),
                Decimal("48.69"),
            )
            self.assertEqual(
                load_last_accepted(db, "bank:USD/TRY:Kapalıçarşı:sell"),
                Decimal("48.71"),
            )
            status = recent_safety_status(db)
            self.assertIn("VERIFIED", status)
            self.assertIn("published=1", status)


if __name__ == "__main__":
    unittest.main()
