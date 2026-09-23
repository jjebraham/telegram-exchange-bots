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
from iran_gold import IranGoldMarket  # noqa: E402
from market_safety import (  # noqa: E402
    BLOCKED,
    PostSafetyAssessment,
    load_last_accepted,
    recent_safety_status,
)


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

    def test_shadow_blocked_iran_fx_never_records_change_history(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "history.sqlite3"
            argv = ["publish_channels.py", "--post", "alanchande-iran-fx"]
            blocked = PostSafetyAssessment(
                post_type="iran-fx",
                decision=BLOCKED,
                reason="single verifier",
                checks=(),
            )

            with (
                patch.object(sys, "argv", argv),
                patch.dict(os.environ, self._env(db, "shadow"), clear=False),
                patch.object(
                    publish_channels,
                    "fetch_iran_open_market_fx",
                    return_value={"USD": Decimal("230000")},
                ),
                patch.object(
                    publish_channels,
                    "build_iran_fx_post",
                    return_value="IRAN-FX",
                ),
                patch.object(
                    publish_channels,
                    "fetch_pashizi_iran_fx",
                    side_effect=RuntimeError("verifier unavailable"),
                ),
                patch.object(
                    publish_channels,
                    "assess_post",
                    return_value=blocked,
                ),
                patch.object(
                    publish_channels,
                    "telegram_send",
                    return_value={"ok": True},
                ) as telegram_send,
                patch.object(
                    publish_channels,
                    "record_published_values",
                ) as record_published_values,
                patch("sys.stdout", new_callable=io.StringIO),
                patch("sys.stderr", new_callable=io.StringIO),
            ):
                result = publish_channels.main()

            self.assertEqual(result, 0)
            telegram_send.assert_called_once()
            record_published_values.assert_not_called()

    def test_iran_fx_pashizi_consensus_allows_enforce_publish(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "history.sqlite3"
            argv = ["publish_channels.py", "--post", "alanchande-iran-fx"]
            tgju = {"USD": Decimal("233200")}
            pashizi = {"USD": Decimal("233100")}

            with (
                patch.object(sys, "argv", argv),
                patch.dict(os.environ, self._env(db, "enforce"), clear=False),
                patch.object(
                    publish_channels,
                    "fetch_iran_open_market_fx",
                    return_value=tgju,
                ),
                patch.object(
                    publish_channels,
                    "fetch_pashizi_iran_fx",
                    return_value=pashizi,
                ),
                patch.object(
                    publish_channels,
                    "build_iran_fx_post",
                    return_value="IRAN-FX",
                ),
                patch.object(
                    publish_channels,
                    "telegram_send",
                    return_value={"ok": True},
                ) as telegram_send,
                patch.object(
                    publish_channels,
                    "record_published_values",
                    return_value="2026-09-23T00:00:00+00:00",
                ) as record_published_values,
                patch("sys.stdout", new_callable=io.StringIO),
                patch("sys.stderr", new_callable=io.StringIO),
            ):
                result = publish_channels.main()

            self.assertEqual(result, 0)
            telegram_send.assert_called_once()
            record_published_values.assert_called_once()

            status = recent_safety_status(db)
            self.assertIn("iran-fx", status)
            self.assertIn("VERIFIED", status)
            self.assertIn("published=1", status)

    def test_iran_fx_three_source_consensus_rejects_tgju_try_outlier(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "history.sqlite3"
            argv = ["publish_channels.py", "--post", "alanchande-iran-fx"]
            tgju = {"TRY": Decimal("4866")}
            pashizi = {"TRY": Decimal("4750")}

            with (
                patch.object(sys, "argv", argv),
                patch.dict(os.environ, self._env(db, "enforce"), clear=False),
                patch.object(
                    publish_channels,
                    "fetch_iran_open_market_fx",
                    return_value=tgju,
                ),
                patch.object(
                    publish_channels,
                    "fetch_pashizi_iran_fx",
                    return_value=pashizi,
                ),
                patch.object(
                    publish_channels,
                    "fetch_adonis_try_sell_toman",
                    return_value=Decimal("4741"),
                ),
                patch.object(
                    publish_channels,
                    "build_iran_fx_post",
                    return_value="IRAN-FX",
                ) as build_iran_fx_post,
                patch.object(
                    publish_channels,
                    "telegram_send",
                    return_value={"ok": True},
                ) as telegram_send,
                patch.object(
                    publish_channels,
                    "record_published_values",
                    return_value="2026-09-23T00:00:00+00:00",
                ) as record_published_values,
                patch("sys.stdout", new_callable=io.StringIO),
                patch("sys.stderr", new_callable=io.StringIO),
            ):
                result = publish_channels.main()

            self.assertEqual(result, 0)
            telegram_send.assert_called_once()

            published_rates = build_iran_fx_post.call_args.args[0]
            self.assertEqual(
                published_rates["TRY"],
                Decimal("4745.5"),
            )

            history_values = record_published_values.call_args.args[2]
            self.assertEqual(
                history_values["TRY"],
                Decimal("4745.5"),
            )

            status = recent_safety_status(db)
            self.assertIn("VERIFIED", status)
            self.assertIn("rejected outlier source(s): tgju=4866", status)

    def test_iran_gold_external_consensus_allows_enforce_publish(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "history.sqlite3"
            argv = [
                "publish_channels.py",
                "--post",
                "alanchande-iran-gold",
            ]
            market = IranGoldMarket(
                coin_prices_rial={
                    "سکه امامی": Decimal("2339800000"),
                    "سکه بهار آزادی": Decimal("2301300000"),
                    "نیم سکه": Decimal("1200000000"),
                    "ربع سکه": Decimal("630000000"),
                    "سکه گرمی": Decimal("330000000"),
                },
                bubble_values_rial={},
                gold18_rial=Decimal("237072000"),
                mesghal_rial=Decimal("1026980000"),
            )
            external = {
                "سکه امامی": Decimal("234000000"),
                "سکه بهار آزادی": Decimal("230000000"),
                "نیم سکه": Decimal("120000000"),
                "ربع سکه": Decimal("63000000"),
                "سکه گرمی": Decimal("33000000"),
                "طلای ۱۸ عیار": Decimal("23731470"),
                "مثقال طلا": Decimal("102800000"),
            }

            with (
                patch.object(sys, "argv", argv),
                patch.dict(os.environ, self._env(db, "enforce"), clear=False),
                patch.object(
                    publish_channels,
                    "fetch_iran_gold_market",
                    return_value=market,
                ),
                patch.object(
                    publish_channels,
                    "fetch_dolarchand_iran_gold",
                    return_value=external,
                ),
                patch.object(
                    publish_channels,
                    "load_iran_gold_near_24h",
                    return_value={},
                ),
                patch.object(
                    publish_channels,
                    "telegram_send",
                    return_value={"ok": True},
                ) as telegram_send,
                patch.object(
                    publish_channels,
                    "record_iran_gold_market",
                    return_value="2026-09-22T00:00:00+00:00",
                ) as record_iran_gold_market,
                patch("sys.stdout", new_callable=io.StringIO),
                patch("sys.stderr", new_callable=io.StringIO),
            ):
                result = publish_channels.main()

            self.assertEqual(result, 0)
            telegram_send.assert_called_once()
            record_iran_gold_market.assert_called_once()

            status = recent_safety_status(db)
            self.assertIn("iran-gold", status)
            self.assertIn("VERIFIED", status)
            self.assertIn("published=1", status)

    def test_garanti_external_consensus_can_verify_when_official_is_down(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "history.sqlite3"
            argv = ["publish_channels.py", "--post", "bank-comparison"]
            garanti = BankQuote(
                name="Garanti BBVA",
                buy=Decimal("47.6750"),
                sell=Decimal("49.6750"),
            )

            with (
                patch.object(sys, "argv", argv),
                patch.dict(os.environ, self._env(db, "enforce"), clear=False),
                patch.object(
                    publish_channels,
                    "fetch_usd_comparison",
                    return_value=[garanti],
                ),
                patch.object(
                    publish_channels,
                    "fetch_altinkaynak_currency_quotes",
                    return_value={},
                ),
                patch.object(
                    publish_channels,
                    "fetch_garanti_quote",
                    side_effect=RuntimeError("official unavailable"),
                ),
                patch.object(
                    publish_channels,
                    "fetch_canlidoviz_garanti_quote",
                    return_value=(
                        Decimal("47.6748"),
                        Decimal("49.6752"),
                    ),
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

            status = recent_safety_status(db)
            self.assertIn("VERIFIED", status)
            self.assertIn("published=1", status)
            self.assertEqual(
                load_last_accepted(db, "bank:USD/TRY:Garanti BBVA:buy"),
                Decimal("47.6749"),
            )
            self.assertEqual(
                load_last_accepted(db, "bank:USD/TRY:Garanti BBVA:sell"),
                Decimal("49.6751"),
            )

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
