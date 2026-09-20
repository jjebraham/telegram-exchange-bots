import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from direct_usdt_compare import DirectUsdtQuote  # noqa: E402
from hybrid_usdt_compare import (  # noqa: E402
    build_hybrid_usdt_post,
    merge_hybrid_usdt_quotes,
)
from iran_usdt import UsdtExchangeQuote  # noqa: E402
from ramzarz_usdt import RamzarzUsdtQuote  # noqa: E402


class HybridUsdtComparisonTests(unittest.TestCase):
    def test_direct_overrides_tgju_and_tgju_fills_missing_rows(self):
        direct = [
            DirectUsdtQuote("والکس", Decimal("229100"), Decimal("229000")),
            DirectUsdtQuote("رمزینکس", Decimal("230000"), Decimal("229900")),
            DirectUsdtQuote("اکسیر", Decimal("229700"), Decimal("228500")),
        ]
        tgju = [
            UsdtExchangeQuote("والکس", Decimal("2287000"), Decimal("2286000"), Decimal("1.1"), "1405/06/30", "23:50"),
            UsdtExchangeQuote("نوبیتکس", Decimal("2293000"), Decimal("2291000"), Decimal("1.0"), "1405/06/30", "23:50"),
            UsdtExchangeQuote("رمزینکس", Decimal("2295000"), Decimal("2293000"), Decimal("1.2"), "1405/06/30", "23:50"),
            UsdtExchangeQuote("بیت پین", Decimal("2294000"), Decimal("2292000"), Decimal("1.1"), "1405/06/30", "23:50"),
            UsdtExchangeQuote("آبان تتر", Decimal("2298000"), Decimal("2296000"), Decimal("1.2"), "1405/06/30", "23:50"),
            UsdtExchangeQuote("تبدیل", Decimal("2291000"), Decimal("2289000"), Decimal("1.1"), "1405/06/30", "23:50"),
            UsdtExchangeQuote("اکسیر", Decimal("2289000"), Decimal("2287000"), Decimal("1.0"), "1405/06/30", "23:50"),
        ]

        merged = merge_hybrid_usdt_quotes(direct, tgju, [])

        self.assertEqual(len(merged), 7)
        wallex = next(q for q in merged if q.exchange == "والکس")
        nobitex = next(q for q in merged if q.exchange == "نوبیتکس")
        self.assertEqual(wallex.source, "direct")
        self.assertEqual(wallex.buy_toman, Decimal("229100"))
        self.assertEqual(nobitex.source, "tgju")
        self.assertEqual(nobitex.buy_toman, Decimal("229300"))
        self.assertEqual(nobitex.sell_toman, Decimal("229100"))

    def test_ramzarz_fills_exchange_when_tgju_missing(self):
        tgju = [
            UsdtExchangeQuote("والکس", Decimal("2291000"), Decimal("2290000"), None, None, None),
            UsdtExchangeQuote("رمزینکس", Decimal("2295000"), Decimal("2293000"), None, None, None),
            UsdtExchangeQuote("بیت پین", Decimal("2294000"), Decimal("2292000"), None, None, None),
            UsdtExchangeQuote("آبان تتر", Decimal("2298000"), Decimal("2296000"), None, None, None),
            UsdtExchangeQuote("اکسیر", Decimal("2289000"), Decimal("2287000"), None, None, None),
        ]
        ramzarz = [
            RamzarzUsdtQuote("نوبیتکس", Decimal("229850"), Decimal("229650")),
            RamzarzUsdtQuote("تبدیل", Decimal("229500"), Decimal("229260")),
        ]

        merged = merge_hybrid_usdt_quotes([], tgju, ramzarz)
        self.assertEqual(len(merged), 7)
        nobitex = next(q for q in merged if q.exchange == "نوبیتکس")
        tabdeal = next(q for q in merged if q.exchange == "تبدیل")
        self.assertEqual(nobitex.source, "ramzarz")
        self.assertEqual(tabdeal.source, "ramzarz")

    def test_crossed_tgju_pair_uses_valid_ramzarz_pair(self):
        tgju = [
            UsdtExchangeQuote(
                "تبدیل",
                Decimal("2295420"),
                Decimal("2298290"),
                Decimal("0.68"),
                "1405/06/30",
                "23:50",
            ),
            UsdtExchangeQuote("والکس", Decimal("2291000"), Decimal("2290000"), None, None, None),
            UsdtExchangeQuote("رمزینکس", Decimal("2295000"), Decimal("2293000"), None, None, None),
            UsdtExchangeQuote("بیت پین", Decimal("2294000"), Decimal("2292000"), None, None, None),
            UsdtExchangeQuote("آبان تتر", Decimal("2298000"), Decimal("2296000"), None, None, None),
        ]
        ramzarz = [
            RamzarzUsdtQuote("تبدیل", Decimal("229500"), Decimal("229260")),
        ]

        merged = merge_hybrid_usdt_quotes([], tgju, ramzarz)
        tabdeal = next(q for q in merged if q.exchange == "تبدیل")
        self.assertEqual(tabdeal.source, "ramzarz")
        self.assertEqual(tabdeal.buy_toman, Decimal("229500"))
        self.assertEqual(tabdeal.sell_toman, Decimal("229260"))
        self.assertLess(tabdeal.sell_toman, tabdeal.buy_toman)

    def test_post_shows_direct_and_fallback_counts(self):
        quotes = [
            # Seven rows are not required by the formatter itself.
            # Source counts should still be correct.
            type("Q", (), {
                "exchange": "والکس",
                "buy_toman": Decimal("229100"),
                "sell_toman": Decimal("229000"),
                "change_pct": Decimal("1.00"),
                "source": "direct",
            })(),
            type("Q", (), {
                "exchange": "نوبیتکس",
                "buy_toman": Decimal("229300"),
                "sell_toman": Decimal("229100"),
                "change_pct": Decimal("0.80"),
                "source": "tgju",
            })(),
        ]

        post = build_hybrid_usdt_post(quotes)
        self.assertNotIn("1️⃣", post)
        self.assertIn("EXCHANGE", post)
        self.assertIn("SELL", post)
        self.assertIn("BUY", post)
        self.assertIn("Δ24H", post)
        self.assertIn("Wallex", post)
        self.assertIn("Nobitex", post)
        self.assertIn("<pre>", post)
        self.assertIn("+1.00%", post)
        self.assertIn("🌐 مستقیم <b>1</b>", post)
        self.assertIn("🧩 پشتیبان <b>1</b>", post)
        self.assertNotIn("میانگین", post)
        self.assertIn("🔴 SELL = فروش　•　🟢 BUY = خرید", post)
        self.assertIn(
            "🛒 کمترین قیمت خرید: <b>والکس</b> <code>229,100</code> تومان",
            post,
        )
        self.assertIn(
            "💰 بیشترین قیمت فروش: <b>نوبیتکس</b>　<code>229,100</code> تومان",
            post,
        )
        self.assertIn("تهران", post)
        self.assertIn("قیمت‌ها صرفاً جهت اطلاع‌رسانی است.", post)


if __name__ == "__main__":
    unittest.main()
