import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

import admin_alerts  # noqa: E402
from market_safety import SafetyObservation, assess_post  # noqa: E402


class AdminAlertTests(unittest.TestCase):
    def test_problem_is_sent_once_then_recovery_is_sent(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "safety.sqlite3"

            blocked = assess_post(
                db,
                "iran-gold",
                [
                    SafetyObservation(
                        "iran-gold:emami",
                        {"tgju": Decimal("230000000")},
                    )
                ],
            )

            with patch.object(admin_alerts, "_send") as send:
                action = admin_alerts.maybe_notify_admin(
                    db,
                    blocked,
                    mode="enforce",
                    token="token",
                    chat_id="-100123",
                )
                self.assertEqual(action, "problem")
                send.assert_called_once()
                self.assertIn(
                    "PUBLIC POST NOT SENT",
                    send.call_args.args[2],
                )

                send.reset_mock()
                repeated = admin_alerts.maybe_notify_admin(
                    db,
                    blocked,
                    mode="enforce",
                    token="token",
                    chat_id="-100123",
                )
                self.assertIsNone(repeated)
                send.assert_not_called()

                verified = assess_post(
                    db,
                    "iran-gold",
                    [
                        SafetyObservation(
                            "iran-gold:emami",
                            {
                                "source-a": Decimal("230000000"),
                                "source-b": Decimal("230100000"),
                            },
                        )
                    ],
                )
                recovered = admin_alerts.maybe_notify_admin(
                    db,
                    verified,
                    mode="enforce",
                    token="token",
                    chat_id="-100123",
                )
                self.assertEqual(recovered, "recovery")
                send.assert_called_once()
                self.assertIn(
                    "source recovered",
                    send.call_args.args[2],
                )

    def test_missing_admin_destination_does_not_change_safety_action(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "safety.sqlite3"
            blocked = assess_post(
                db,
                "usdt",
                [
                    SafetyObservation(
                        "usdt:IRT",
                        {"one-source": Decimal("230000")},
                    )
                ],
            )

            action = admin_alerts.maybe_notify_admin(
                db,
                blocked,
                mode="enforce",
                token=None,
                chat_id=None,
            )
            self.assertEqual(action, "problem")


if __name__ == "__main__":
    unittest.main()
