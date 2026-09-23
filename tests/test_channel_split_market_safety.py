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
    SourceHealthEvent,
    alert_action,
    bank_fx_observations,
    assess_post,
    evaluate_observation,
    iran_gold_observations,
    mark_alert_sent,
    mark_source_health_alert_sent,
    publication_allowed,
    record_source_health_event,
    record_assessment,
    recent_source_health_status,
    source_health_action,
    turkey_gold_observations,
    usdt_observations,
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

    def test_two_sources_cannot_hide_wide_gap_behind_midpoint(self):
        check = evaluate_observation(
            SafetyObservation(
                "usdtry",
                {
                    "source-a": Decimal("48.70"),
                    "source-b": Decimal("50.00"),
                },
                max_source_deviation_pct=Decimal("1.50"),
            )
        )
        self.assertEqual(check.decision, BLOCKED)
        self.assertIn("spread", check.reason)

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

    def test_three_source_tight_majority_rejects_near_threshold_outlier(self):
        check = evaluate_observation(
            SafetyObservation(
                "iran-fx:TRY/TOMAN",
                {
                    "adonis": Decimal("4727"),
                    "pashizi": Decimal("4735"),
                    "tgju": Decimal("4826.5"),
                },
                min_sources=2,
                max_source_deviation_pct=Decimal("2.00"),
                strong_quorum=3,
            )
        )
        self.assertEqual(check.decision, VERIFIED)
        self.assertEqual(set(check.source_values), {"adonis", "pashizi"})
        self.assertEqual(check.reference_value, Decimal("4731"))
        self.assertIn("rejected outlier source(s): tgju=4826.5", check.reason)

    def test_two_source_disagreement_still_blocks(self):
        check = evaluate_observation(
            SafetyObservation(
                "iran-fx:AZN/TOMAN",
                {
                    "pashizi": Decimal("133400"),
                    "tgju": Decimal("137220"),
                },
                min_sources=2,
                max_source_deviation_pct=Decimal("2.00"),
            )
        )
        self.assertEqual(check.decision, BLOCKED)
        self.assertIn("consensus spread is too wide", check.reason)

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

    def test_garanti_bank_row_can_verify_with_official_source(self):
        quote = type(
            "BankQuote",
            (),
            {
                "name": "Garanti BBVA",
                "buy": Decimal("47.6750"),
                "sell": Decimal("49.6750"),
            },
        )()
        observations = bank_fx_observations(
            "USD/TRY",
            [quote],
            {
                "garanti-official": {
                    "Garanti BBVA": (
                        Decimal("47.6751"),
                        Decimal("49.6749"),
                    )
                }
            },
        )
        self.assertEqual(len(observations), 2)
        for observation in observations:
            check = evaluate_observation(observation)
            self.assertEqual(check.decision, VERIFIED)
            self.assertEqual(
                set(check.source_values),
                {"doviz", "garanti-official"},
            )

    def test_kuveyt_bank_row_can_verify_with_official_source(self):
        quote = type(
            "BankQuote",
            (),
            {
                "name": "Kuveyt Türk",
                "buy": Decimal("48.1475"),
                "sell": Decimal("49.2544"),
            },
        )()
        observations = bank_fx_observations(
            "USD/TRY",
            [quote],
            {
                "kuveyt-official": {
                    "Kuveyt Türk": (
                        Decimal("48.14757"),
                        Decimal("49.25438"),
                    )
                }
            },
        )
        self.assertEqual(len(observations), 2)
        for observation in observations:
            check = evaluate_observation(observation)
            self.assertEqual(check.decision, VERIFIED)
            self.assertEqual(
                set(check.source_values),
                {"doviz", "kuveyt-official"},
            )

    def test_iran_gold_can_verify_with_independent_dolarchand_family(self):
        market = type(
            "IranGoldMarket",
            (),
            {
                "coin_prices_rial": {
                    "سکه امامی": Decimal("2339800000"),
                    "سکه بهار آزادی": Decimal("2301300000"),
                    "نیم سکه": Decimal("1200000000"),
                    "ربع سکه": Decimal("630000000"),
                    "سکه گرمی": Decimal("330000000"),
                },
                "gold18_rial": Decimal("237072000"),
                "mesghal_rial": Decimal("1026980000"),
            },
        )()
        external = {
            "سکه امامی": Decimal("234000000"),
            "سکه بهار آزادی": Decimal("230000000"),
            "نیم سکه": Decimal("120000000"),
            "ربع سکه": Decimal("63000000"),
            "سکه گرمی": Decimal("33000000"),
            "طلای ۱۸ عیار": Decimal("23731470"),
            "مثقال طلا": Decimal("102800000"),
        }

        observations = iran_gold_observations(
            market,
            {"dolarchand": external},
        )

        self.assertEqual(len(observations), 7)
        for observation in observations:
            check = evaluate_observation(observation)
            self.assertEqual(check.decision, VERIFIED)
            self.assertEqual(
                set(check.source_values),
                {"tgju", "dolarchand"},
            )

    def test_turkey_gold_can_verify_with_independent_altinkaynak_source(self):
        quote = type(
            "GoldQuote",
            (),
            {
                "key": "gram",
                "buy": Decimal("6826"),
                "sell": Decimal("6834"),
            },
        )()
        observations = turkey_gold_observations(
            [quote],
            {
                "altinkaynak": {
                    "gram": (Decimal("6825"), Decimal("6835"))
                }
            },
        )
        self.assertEqual(len(observations), 1)
        check = evaluate_observation(observations[0])
        self.assertEqual(check.decision, VERIFIED)
        self.assertEqual(
            set(check.source_values),
            {"doviz", "altinkaynak"},
        )

    def test_physical_coin_allows_modest_cross_dealer_midpoint_premium(self):
        quote = type(
            "GoldQuote",
            (),
            {
                "key": "quarter",
                "buy": Decimal("10826.04"),
                "sell": Decimal("11073.13"),
            },
        )()
        observation = turkey_gold_observations(
            [quote],
            {
                "altinkaynak": {
                    "quarter": (
                        Decimal("11000"),
                        Decimal("11290"),
                    )
                }
            },
        )[0]
        check = evaluate_observation(observation)
        self.assertEqual(check.decision, VERIFIED)

    def test_gram_gold_keeps_tighter_cross_source_tolerance(self):
        quote = type(
            "GoldQuote",
            (),
            {
                "key": "gram",
                "buy": Decimal("6766"),
                "sell": Decimal("6773"),
            },
        )()
        observation = turkey_gold_observations(
            [quote],
            {
                "altinkaynak": {
                    "gram": (
                        Decimal("6880"),
                        Decimal("6890"),
                    )
                }
            },
        )[0]
        check = evaluate_observation(observation)
        self.assertEqual(check.decision, BLOCKED)

    def test_turkey_gold_abnormally_wide_displayed_spread_blocks(self):
        quote = type(
            "GoldQuote",
            (),
            {
                "key": "quarter",
                "buy": Decimal("10000"),
                "sell": Decimal("11000"),
            },
        )()
        observation = turkey_gold_observations(
            [quote],
            {
                "altinkaynak": {
                    "quarter": (Decimal("10450"), Decimal("10550"))
                }
            },
        )[0]
        check = evaluate_observation(observation)
        self.assertEqual(check.decision, BLOCKED)
        self.assertIn("displayed dealer spread", check.reason)

    def test_usdt_requires_independent_source_families_not_just_rows(self):
        rows = [
            type(
                "Q",
                (),
                {
                    "exchange": name,
                    "buy_toman": Decimal("230000") + Decimal(index),
                    "sell_toman": Decimal("229900") + Decimal(index),
                    "source": "tgju",
                },
            )()
            for index, name in enumerate(
                ["a", "b", "c", "d", "e", "f", "g"]
            )
        ]
        check = evaluate_observation(usdt_observations(rows)[0])
        self.assertEqual(check.decision, BLOCKED)
        self.assertIn("independent source families", check.reason)

    def test_usdt_direct_exchange_plus_aggregator_can_reach_quorum(self):
        rows = [
            type(
                "Q",
                (),
                {
                    "exchange": "والکس",
                    "buy_toman": Decimal("230000"),
                    "sell_toman": Decimal("229900"),
                    "source": "direct",
                },
            )(),
            *[
                type(
                    "Q",
                    (),
                    {
                        "exchange": name,
                        "buy_toman": Decimal("230010") + Decimal(index),
                        "sell_toman": Decimal("229910") + Decimal(index),
                        "source": "tgju",
                    },
                )()
                for index, name in enumerate(["b", "c", "d", "e"])
            ],
        ]
        check = evaluate_observation(usdt_observations(rows)[0])
        self.assertEqual(check.decision, VERIFIED)
        self.assertEqual(set(check.source_values), {"direct:والکس", "tgju"})

    def test_usdt_bad_displayed_exchange_row_blocks_post(self):
        rows = [
            type(
                "Q",
                (),
                {
                    "exchange": "والکس",
                    "buy_toman": Decimal("230000"),
                    "sell_toman": Decimal("229900"),
                    "source": "direct",
                },
            )(),
            *[
                type(
                    "Q",
                    (),
                    {
                        "exchange": name,
                        "buy_toman": Decimal("230100") + Decimal(index),
                        "sell_toman": Decimal("230000") + Decimal(index),
                        "source": "tgju",
                    },
                )()
                for index, name in enumerate(["b", "c", "d"])
            ],
            type(
                "Q",
                (),
                {
                    "exchange": "bad-row",
                    "buy_toman": Decimal("245000"),
                    "sell_toman": Decimal("244900"),
                    "source": "ramzarz",
                },
            )(),
        ]
        check = evaluate_observation(usdt_observations(rows)[0])
        self.assertEqual(check.decision, BLOCKED)
        self.assertIn("cross-exchange median", check.reason)

    def test_usdt_abnormally_wide_customer_spread_blocks_post(self):
        rows = [
            type(
                "Q",
                (),
                {
                    "exchange": "wide",
                    "buy_toman": Decimal("235000"),
                    "sell_toman": Decimal("225000"),
                    "source": "direct",
                },
            )(),
            *[
                type(
                    "Q",
                    (),
                    {
                        "exchange": name,
                        "buy_toman": Decimal("230050") + Decimal(index),
                        "sell_toman": Decimal("229950") + Decimal(index),
                        "source": "tgju",
                    },
                )()
                for index, name in enumerate(["b", "c", "d", "e"])
            ],
        ]
        check = evaluate_observation(usdt_observations(rows)[0])
        self.assertEqual(check.decision, BLOCKED)
        self.assertIn("customer spread", check.reason)

    def test_mixed_blocked_post_does_not_advance_any_baseline(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "safety.sqlite3"
            assessment = assess_post(
                db,
                "mixed-post",
                [
                    SafetyObservation(
                        "verified-market",
                        {
                            "a": Decimal("100"),
                            "b": Decimal("100.1"),
                        },
                    ),
                    SafetyObservation(
                        "blocked-market",
                        {"only": Decimal("200")},
                    ),
                ],
            )
            self.assertEqual(assessment.decision, BLOCKED)

            record_assessment(
                db,
                assessment,
                mode="shadow",
                published=True,
            )

            from market_safety import load_last_accepted

            self.assertIsNone(
                load_last_accepted(db, "verified-market")
            )
            self.assertIsNone(
                load_last_accepted(db, "blocked-market")
            )

    def test_enforce_blocks_non_verified_but_shadow_allows(self):
        assessment = type(
            "Assessment",
            (),
            {"decision": BLOCKED},
        )()
        self.assertFalse(publication_allowed("enforce", assessment))
        self.assertTrue(publication_allowed("shadow", assessment))

    def test_source_health_degradation_is_deduplicated_and_recovers(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "safety.sqlite3"
            degraded = SourceHealthEvent(
                source_key="usdt:ramzarz",
                healthy=False,
                detail="certificate expired",
            )
            now = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)

            self.assertEqual(
                source_health_action(db, degraded, now=now),
                "degraded",
            )
            mark_source_health_alert_sent(
                db,
                degraded,
                action="degraded",
                now=now,
            )
            self.assertIsNone(
                source_health_action(
                    db,
                    degraded,
                    now=now + timedelta(minutes=20),
                    repeat_minutes=60,
                )
            )

            healthy = SourceHealthEvent(
                source_key="usdt:ramzarz",
                healthy=True,
            )
            self.assertEqual(
                source_health_action(
                    db,
                    healthy,
                    now=now + timedelta(minutes=21),
                ),
                "recovery",
            )

    def test_source_health_audit_records_degraded_provider(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Path(tempdir) / "safety.sqlite3"
            event = SourceHealthEvent(
                source_key="usdt:ramzarz",
                healthy=False,
                detail="certificate expired",
            )
            record_source_health_event(db, event)
            status = recent_source_health_status(db)
            self.assertIn("usdt:ramzarz", status)
            self.assertIn("DEGRADED", status)
            self.assertIn("certificate expired", status)

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
