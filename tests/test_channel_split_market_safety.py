import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from market_safety import (  # noqa: E402
    BLOCKED,
    SUSPICIOUS,
    VERIFIED,
    SafetyObservation,
    alert_action,
    assess_post,
    evaluate_observation,
    mark_alert_sent,
    publication_allowed,
    record_assessment,
)


class MarketSafetyTests(unittest.TestCase):
    def test_two_agreeing_independent_sources_verify(self):
        check = evaluate_observation(
            SafetyObservation(
                "usdtry",
                {
                    "source-a": Decimal("48.70"),
                    "source-b": Decimal("48.75"),
                },
                max_source_deviation_pct=Decimal("1"),
            )
        )
        self.assertEqual(check.decision, VERIFIED)

    def test_single_source_blocks(self):
        check = evaluate_observation(
            SafetyObservation("gold", {"only-source": Decimal("6800")})
        )
        self.assertEqual(check.decision, BLOCKED)
        self.assertIn("insufficient independent", check.reason)

    def test_disagreeing_sources_block(self):
        check = evaluate_observation(
            SafetyObservation(
                "usdtry",
                {
                    "source-a": Decimal("48.70"),
                    "source-b": Decimal("53.00"),
                },
                max_source_deviation_pct=Decimal("1.5"),
            )
        )
        self.assertEqual(check.decision, BLOCKED)
        self.assertIn("disagree", check.reason)

    def test_three_sources_can_reject_one_outlier_and_keep_quorum(self):
        check = evaluate_observation(
            SafetyObservation(
                "usdtry",
                {
                    "source-a": Decimal("48.70"),
                    "source-b": Decimal("48.72"),
                    "source-bad": Decimal("55.00"),
                },
                max_source_deviation_pct=Decimal("1.5"),
            )
        )
        self.assertEqual(check.decision, VERIFIED)
        self.assertEqual(set(check.source_values), {"source-a", "source-b"})
        self.assertIn("rejected outlier", check.reason)

    def test_x10_unit_jump_blocks(self):
        check = evaluate_observation(
            SafetyObservation(
                "irt",
                {
                    "source-a": Decimal("2290000"),
                    "source-b": Decimal("2291000"),
                    "source-c": Decimal("2289000"),
                },
            ),
            last_accepted_value=Decimal("229000"),
        )
        self.assertEqual(check.decision, BLOCKED)
        self.assertIn("x10", check.reason)

    def test_large_move_needs_stronger_quorum(self):
        check = evaluate_observation(
            SafetyObservation(
                "usdtry",
                {
                    "source-a": Decimal("52.00"),
                    "source-b": Decimal("52.02"),
                },
                suspicious_move_pct=Decimal("4"),
                strong_quorum=3,
            ),
            last_accepted_value=Decimal("48.00"),
        )
        self.assertEqual(check.decision, SUSPICIOUS)

    def test_large_move_with_three_agreeing_sources_can_verify(self):
        check = evaluate_observation(
            SafetyObservation(
                "usdtry",
                {
                    "source-a": Decimal("52.00"),
                    "source-b": Decimal("52.02"),
                    "source-c": Decimal("51.99"),
                },
                suspicious_move_pct=Decimal("4"),
                strong_quorum=3,
            ),
            last_accepted_value=Decimal("48.00"),
        )
        self.assertEqual(check.decision, VERIFIED)

    def test_only_published_verified_value_becomes_baseline(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "safety.sqlite3"
            observation = SafetyObservation(
                "usdtry",
                {
                    "source-a": Decimal("48.70"),
                    "source-b": Decimal("48.71"),
                },
            )
            assessment = assess_post(db, "bank-usd", [observation])

            record_assessment(
                db, assessment, mode="shadow", published=False
            )
            later = assess_post(db, "bank-usd", [observation])
            self.assertIsNone(later.checks[0].last_accepted_value)

            record_assessment(
                db, assessment, mode="shadow", published=True
            )
            accepted = assess_post(db, "bank-usd", [observation])
            self.assertIsNotNone(accepted.checks[0].last_accepted_value)

    def test_enforce_blocks_non_verified_but_shadow_allows(self):
        assessment = type(
            "Assessment",
            (),
            {"decision": BLOCKED},
        )()
        self.assertFalse(publication_allowed("enforce", assessment))
        self.assertTrue(publication_allowed("shadow", assessment))

    def test_alerts_are_deduplicated_then_recover(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "safety.sqlite3"
            blocked = assess_post(
                db,
                "gold",
                [SafetyObservation("gold", {"one": Decimal("6800")})],
            )
            now = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
            self.assertEqual(alert_action(db, blocked, now=now), "problem")
            mark_alert_sent(db, blocked, action="problem", now=now)
            self.assertIsNone(
                alert_action(
                    db,
                    blocked,
                    now=now + timedelta(minutes=30),
                    repeat_minutes=60,
                )
            )
            self.assertEqual(
                alert_action(
                    db,
                    blocked,
                    now=now + timedelta(minutes=61),
                    repeat_minutes=60,
                ),
                "problem",
            )

            verified = assess_post(
                db,
                "gold",
                [
                    SafetyObservation(
                        "gold",
                        {
                            "one": Decimal("6800"),
                            "two": Decimal("6801"),
                        },
                    )
                ],
            )
            self.assertEqual(
                alert_action(
                    db,
                    verified,
                    now=now + timedelta(minutes=62),
                ),
                "recovery",
            )


if __name__ == "__main__":
    unittest.main()
