import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app import canonical_try_rates as canonical


class CanonicalTryRatesTests(unittest.TestCase):
    def setUp(self):
        canonical._MARKET_CACHE = None

    def tearDown(self):
        canonical._MARKET_CACHE = None

    def test_market_snapshot_is_shared_but_percentages_are_live(self):
        snapshot = SimpleNamespace(
            quotes=[
                SimpleNamespace(buy_toman=Decimal("236000")),
                SimpleNamespace(buy_toman=Decimal("238000")),
                SimpleNamespace(buy_toman=Decimal("237000")),
            ]
        )

        with (
            patch.object(
                canonical,
                "collect_hybrid_usdt_snapshot",
                return_value=snapshot,
            ) as collect_mock,
            patch.object(
                canonical,
                "fetch_btcturk_usdt_try",
                return_value=Decimal("49.40"),
            ) as btcturk_mock,
            patch.object(
                canonical,
                "load_try_adjustments",
                side_effect=[
                    {
                        "user_tl_buy_adjustment_pct": Decimal("1"),
                        "user_tl_sell_adjustment_pct": Decimal("-2"),
                    },
                    {
                        "user_tl_buy_adjustment_pct": Decimal("1.5"),
                        "user_tl_sell_adjustment_pct": Decimal("-2.5"),
                    },
                ],
            ),
        ):
            first = canonical.get_canonical_try_rates()
            second = canonical.get_canonical_try_rates()

        self.assertEqual(collect_mock.call_count, 1)
        self.assertEqual(btcturk_mock.call_count, 1)
        self.assertNotEqual(first["buy_lira"], second["buy_lira"])
        self.assertNotEqual(first["sell_lira"], second["sell_lira"])
        self.assertEqual(first["source_count"], 3)
        self.assertEqual(second["market_usdt_toman"], Decimal("237000"))
        self.assertEqual(second["market_usdt_try"], Decimal("49.40"))

    def test_even_source_count_uses_exact_decimal_median(self):
        quotes = [
            SimpleNamespace(buy_toman=Decimal("236000")),
            SimpleNamespace(buy_toman=Decimal("238000")),
            SimpleNamespace(buy_toman=Decimal("237000")),
            SimpleNamespace(buy_toman=Decimal("239000")),
        ]
        self.assertEqual(
            canonical._median_buy_toman(quotes),
            Decimal("237500"),
        )


    def test_hawala_uses_same_cached_market_snapshot(self):
        snapshot = SimpleNamespace(
            quotes=[
                SimpleNamespace(buy_toman=Decimal("235000")),
                SimpleNamespace(buy_toman=Decimal("236000")),
                SimpleNamespace(buy_toman=Decimal("237000")),
            ]
        )

        with (
            patch.object(
                canonical,
                "collect_hybrid_usdt_snapshot",
                return_value=snapshot,
            ) as collect_mock,
            patch.object(
                canonical,
                "fetch_btcturk_usdt_try",
                return_value=Decimal("49"),
            ) as btcturk_mock,
            patch.object(
                canonical,
                "load_try_adjustments",
                return_value={
                    "user_tl_buy_adjustment_pct": Decimal("1"),
                    "user_tl_sell_adjustment_pct": Decimal("-2"),
                },
            ),
            patch.object(
                canonical,
                "load_hawala_try_adjustment",
                return_value=Decimal("-2"),
            ),
        ):
            try_rates = canonical.get_canonical_try_rates()
            hawala = canonical.get_canonical_hawala_try_rate()

        self.assertEqual(collect_mock.call_count, 1)
        self.assertEqual(btcturk_mock.call_count, 1)
        self.assertEqual(hawala["hawala_try"], try_rates["sell_lira"])
        self.assertEqual(hawala["adjustment_pct"], Decimal("-2"))



if __name__ == "__main__":
    unittest.main()
