import unittest
from decimal import Decimal
from unittest.mock import patch

from app import canonical_try_rates as canonical


TRY_ADJUSTMENTS = {
    "user_tl_buy_adjustment_pct": Decimal("1"),
    "user_tl_sell_adjustment_pct": Decimal("-2"),
}


class CanonicalTryRatesTests(unittest.TestCase):
    def test_customer_rates_use_the_live_api_market_snapshot(self):
        with patch.object(
            canonical,
            "load_try_adjustments",
            return_value=TRY_ADJUSTMENTS,
        ):
            rates = canonical.get_canonical_try_rates(
                Decimal("266902"),
                Decimal("49.229"),
                market_age_seconds=12.5,
            )

        self.assertEqual(rates["buy_lira"], Decimal("5480"))
        self.assertEqual(rates["sell_lira"], Decimal("5310"))
        self.assertEqual(rates["market_usdt_toman"], Decimal("266902"))
        self.assertEqual(rates["market_usdt_try"], Decimal("49.229"))
        self.assertEqual(rates["source_count"], 1)
        self.assertEqual(rates["market_age_seconds"], 12.5)

    def test_hawala_quote_uses_the_same_market_snapshot(self):
        with patch.object(
            canonical,
            "load_hawala_try_adjustment",
            return_value=Decimal("-2"),
        ):
            hawala = canonical.get_canonical_hawala_try_rate(
                Decimal("266902"),
                Decimal("49.229"),
                market_age_seconds=5,
            )

        self.assertEqual(hawala["hawala_try"], Decimal("5310"))
        self.assertEqual(hawala["market_usdt_toman"], Decimal("266902"))
        self.assertEqual(hawala["market_usdt_try"], Decimal("49.229"))
        self.assertEqual(hawala["market_age_seconds"], 5.0)

    def test_nonpositive_market_values_are_rejected(self):
        with patch.object(canonical, "load_try_adjustments", return_value=TRY_ADJUSTMENTS):
            with self.assertRaisesRegex(ValueError, "market_usdt_toman must be positive"):
                canonical.get_canonical_try_rates(Decimal("0"), Decimal("49.229"))


if __name__ == "__main__":
    unittest.main()
