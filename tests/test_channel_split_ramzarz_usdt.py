import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from ramzarz_usdt import parse_ramzarz_usdt_html  # noqa: E402


class RamzarzUsdtTests(unittest.TestCase):
    def test_parse_exchange_table(self):
        html = """
        <table>
          <tr><th>صرافی</th><th>فروش به کاربر</th><th>خرید از کاربر</th></tr>
          <tr><td>Ramzinex رمزینکس</td><td>۲۳۰,۱۹۹ تومان</td><td>۲۳۰,۰۰۰ تومان</td></tr>
          <tr><td>Wallex والکس</td><td>۲۲۹,۱۰۰ تومان</td><td>۲۲۹,۰۰۰ تومان</td></tr>
          <tr><td>Nobitex نوبیتکس</td><td>۲۳۰,۱۸۷ تومان</td><td>۲۲۹,۸۴۴ تومان</td></tr>
          <tr><td>Tabdeal تبدیل</td><td>۲۲۹,۹۸۰ تومان</td><td>۲۲۹,۸۰۲ تومان</td></tr>
        </table>
        """

        quotes = parse_ramzarz_usdt_html(html)
        self.assertEqual(len(quotes), 4)
        nobitex = next(q for q in quotes if q.exchange == "نوبیتکس")
        self.assertEqual(nobitex.buy_toman, Decimal("230187"))
        self.assertEqual(nobitex.sell_toman, Decimal("229844"))

    def test_crossed_row_is_ignored(self):
        html = """
        <table>
          <tr><td>Wallex والکس</td><td>۲۲۹,۰۰۰ تومان</td><td>۲۲۹,۱۰۰ تومان</td></tr>
          <tr><td>Ramzinex رمزینکس</td><td>۲۳۰,۰۰۰ تومان</td><td>۲۲۹,۹۰۰ تومان</td></tr>
        </table>
        """
        quotes = parse_ramzarz_usdt_html(html)
        self.assertEqual([q.exchange for q in quotes], ["رمزینکس"])

    def test_missing_rows_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_ramzarz_usdt_html("<html><body>no table</body></html>")


if __name__ == "__main__":
    unittest.main()
