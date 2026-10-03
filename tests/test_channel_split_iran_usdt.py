import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from iran_usdt import UsdtExchangeQuote, filter_usdt_quotes  # noqa: E402


class IranUsdtFreshnessTests(unittest.TestCase):
    def test_freshest_date_beats_larger_stale_batch(self):
        quotes = [
            UsdtExchangeQuote("والکس", Decimal("2642710"), Decimal("2642690"), None, "1405/07/11", "11:46"),
            UsdtExchangeQuote("نوبیتکس", Decimal("2551400"), Decimal("2550170"), None, "1405/07/08", "19:21"),
            UsdtExchangeQuote("رمزینکس", Decimal("2549999"), None, None, "1405/07/08", "19:20"),
            UsdtExchangeQuote("بیت پین", Decimal("2561490"), None, None, "1405/07/08", "19:09"),
            UsdtExchangeQuote("آبان تتر", Decimal("2565080"), Decimal("2543430"), None, "1405/07/08", "19:19"),
            UsdtExchangeQuote("تبدیل", Decimal("2546910"), None, None, "1405/07/08", "19:17"),
            UsdtExchangeQuote("اکسیر", Decimal("2535560"), None, None, "1405/07/08", "19:20"),
        ]

        filtered = filter_usdt_quotes(quotes)

        self.assertEqual([q.exchange for q in filtered], ["والکس"])
        self.assertEqual(filtered[0].source_date, "1405/07/11")

    def test_undated_rows_do_not_join_dated_fresh_batch(self):
        quotes = [
            UsdtExchangeQuote("والکس", Decimal("2642710"), Decimal("2642690"), None, "1405/07/11", "11:46"),
            UsdtExchangeQuote("نوبیتکس", Decimal("2551400"), Decimal("2550170"), None, None, None),
        ]

        filtered = filter_usdt_quotes(quotes)

        self.assertEqual([q.exchange for q in filtered], ["والکس"])

    def test_relative_time_filter_still_applies_within_freshest_date(self):
        quotes = [
            UsdtExchangeQuote("والکس", Decimal("2642710"), Decimal("2642690"), None, "1405/07/11", "11:46"),
            UsdtExchangeQuote("نوبیتکس", Decimal("2641000"), Decimal("2640000"), None, "1405/07/11", "10:30"),
            UsdtExchangeQuote("تبدیل", Decimal("2640000"), Decimal("2639000"), None, "1405/07/11", "09:30"),
        ]

        filtered = filter_usdt_quotes(quotes, max_lag_minutes=90)

        self.assertEqual([q.exchange for q in filtered], ["والکس", "نوبیتکس"])


if __name__ == "__main__":
    unittest.main()
