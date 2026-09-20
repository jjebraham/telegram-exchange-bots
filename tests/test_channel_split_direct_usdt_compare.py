import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from direct_usdt_compare import (  # noqa: E402
    DirectUsdtQuote,
    build_direct_usdt_comparison_post,
    collect_direct_usdt_quotes,
    filter_direct_usdt_outliers,
)


class DirectUsdtComparisonTests(unittest.TestCase):
    def test_one_source_failure_does_not_kill_comparison(self):
        def wallex():
            return DirectUsdtQuote(
                exchange="والکس",
                buy_toman=Decimal("229000"),
                sell_toman=Decimal("228800"),
            )

        def exir():
            raise TimeoutError("temporary")

        def ramzinex():
            return DirectUsdtQuote(
                exchange="رمزینکس",
                buy_toman=Decimal("229300"),
                sell_toman=Decimal("229100"),
            )

        quotes, errors = collect_direct_usdt_quotes(
            (
                ("Wallex", wallex),
                ("Exir", exir),
                ("Ramzinex", ramzinex),
            )
        )

        self.assertEqual([q.exchange for q in quotes], ["والکس", "رمزینکس"])
        self.assertIn("Exir", errors)

    def test_fewer_than_two_sources_fails_closed(self):
        def ok():
            return DirectUsdtQuote(
                exchange="والکس",
                buy_toman=Decimal("229000"),
                sell_toman=Decimal("228800"),
            )

        def fail():
            raise TimeoutError("temporary")

        with self.assertRaises(RuntimeError):
            collect_direct_usdt_quotes(
                (
                    ("Wallex", ok),
                    ("Exir", fail),
                    ("Ramzinex", fail),
                )
            )

    def test_extreme_midpoint_outlier_is_removed(self):
        quotes = [
            DirectUsdtQuote("والکس", Decimal("229000"), Decimal("228800")),
            DirectUsdtQuote("رمزینکس", Decimal("229300"), Decimal("229100")),
            DirectUsdtQuote("اکسیر", Decimal("400000"), Decimal("399000")),
        ]

        filtered = filter_direct_usdt_outliers(quotes)
        self.assertEqual(
            [q.exchange for q in filtered],
            ["والکس", "رمزینکس"],
        )

    def test_build_post_uses_customer_buy_sell_semantics(self):
        quotes = [
            DirectUsdtQuote("والکس", Decimal("229000"), Decimal("228800")),
            DirectUsdtQuote("رمزینکس", Decimal("229300"), Decimal("229100")),
            DirectUsdtQuote("اکسیر", Decimal("229600"), Decimal("228500")),
        ]

        post = build_direct_usdt_comparison_post(quotes)

        self.assertIn("خرید شما", post)
        self.assertIn("فروش شما", post)
        self.assertIn("<code>229,000</code>", post)
        self.assertIn("<code>228,800</code>", post)
        self.assertIn("منابع فعال: <b>3/3</b>", post)


if __name__ == "__main__":
    unittest.main()
