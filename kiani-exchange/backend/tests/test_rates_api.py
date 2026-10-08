import asyncio
import time
import unittest
from decimal import Decimal
from unittest.mock import patch

from app.api import rates


TRY_ADJUSTMENTS = {
    "user_tl_buy_adjustment_pct": Decimal("1"),
    "user_tl_sell_adjustment_pct": Decimal("-2"),
}


class FakePriceCache:
    def __init__(self):
        now = time.time()
        self.usdt_irr_time = now
        self.usdt_try_time = now

    async def get_usdt_irr(self):
        return 2669020.0

    async def get_usdt_try(self):
        return 49.229


class RatesApiTests(unittest.TestCase):
    def test_try_endpoint_uses_customer_rate_cache_and_shared_settings(self):
        with (
            patch.object(rates, "price_cache", FakePriceCache()),
            patch(
                "app.canonical_try_rates.load_try_adjustments",
                return_value=TRY_ADJUSTMENTS,
            ),
        ):
            payload = asyncio.run(rates.get_try_rates())

        self.assertEqual(payload["rates"]["buy_lira"], 5480)
        self.assertEqual(payload["rates"]["sell_lira"], 5310)
        self.assertEqual(payload["rates"]["source"], "kiani-price-cache")

    def test_current_rates_remain_available_if_hawala_adjustment_is_missing(self):
        with (
            patch.object(rates, "price_cache", FakePriceCache()),
            patch(
                "app.canonical_try_rates.load_try_adjustments",
                return_value=TRY_ADJUSTMENTS,
            ),
            patch(
                "app.canonical_try_rates.load_hawala_try_adjustment",
                side_effect=RuntimeError("hawala adjustment unavailable"),
            ),
        ):
            payload = asyncio.run(rates.get_current_rates())

        self.assertEqual(payload["rates"]["buy_lira"], 5480)
        self.assertEqual(payload["rates"]["sell_lira"], 5310)
        self.assertIn("USDT_IRR", payload["rates"])
        self.assertNotIn("HAWALA_TRY_TOMAN", payload["rates"])


if __name__ == "__main__":
    unittest.main()
