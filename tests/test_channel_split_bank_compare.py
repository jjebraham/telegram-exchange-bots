import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from bank_compare import BankQuote, build_usd_comparison_post, parse_comparison_html  # noqa: E402


SAMPLE = """
<table>
<tr><th>Banka</th><th>Alış</th><th>Satış</th><th>Makas</th></tr>
<tr><td>Kapalıçarşı</td><td>48,6900</td><td>48,7000</td><td>0,0100</td></tr>
<tr><td>Garanti BBVA</td><td>47,8320</td><td>49,1820</td><td>1,3500</td></tr>
<tr><td>İş Bankası</td><td>47,9100</td><td>49,1000</td><td>1,1900</td></tr>
<tr><td>Kuveyt Türk</td><td>48,2750</td><td>49,0550</td><td>0,7800</td></tr>
<tr><td>Ziraat Bankası</td><td>48,3000</td><td>49,0000</td><td>0,7000</td></tr>
</table>
"""


class BankComparisonTests(unittest.TestCase):
    def test_parse_target_rows_in_fixed_order(self):
        quotes = parse_comparison_html(SAMPLE)
        self.assertEqual([q.name for q in quotes], [
            "Kapalıçarşı",
            "Garanti BBVA",
            "İş Bankası",
            "Kuveyt Türk",
            "Ziraat Bankası",
        ])
        self.assertEqual(quotes[0].buy, Decimal("48.6900"))
        self.assertEqual(quotes[0].sell, Decimal("48.7000"))

    def test_post_is_compact_comparison_only(self):
        quotes = parse_comparison_html(SAMPLE)
        post = build_usd_comparison_post(quotes)
        self.assertIn("مقایسه نرخ دلار در ترکیه", post)
        self.assertIn("🇺🇸USD/🇹🇷TL", post)
        self.assertNotIn("🔴 SELL = فروش", post)
        self.assertIn("<pre>", post)
        self.assertIn("MARKET", post)
        self.assertIn("Δ24H", post)
        self.assertIn("🇺🇸KAPALI", post)
        self.assertIn("🇺🇸GARANTI", post)
        self.assertIn("🇺🇸ISBANK", post)
        self.assertIn("🇺🇸KUVEYT", post)
        self.assertIn("🇺🇸ZIRAAT", post)
        self.assertIn("48.7000", post)
        self.assertIn("48.6900", post)
        self.assertIn("—", post)
        self.assertNotIn("کمترین قیمت خرید", post)
        self.assertNotIn("بیشترین قیمت فروش", post)
        self.assertIn("💵 واحد: لیر ترکیه 🇹🇷", post)
        self.assertIn("استانبول", post)
        self.assertIn("قیمت‌ها صرفاً جهت اطلاع‌رسانی است.", post)

    def test_24h_change_uses_midpoint(self):
        current = [
            BankQuote("Kapalıçarşı", Decimal("49.0000"), Decimal("49.2000")),
        ]
        previous = {
            "Kapalıçarşı": (Decimal("48.0000"), Decimal("48.2000")),
        }

        post = build_usd_comparison_post(current, previous)
        # Previous midpoint 48.1 -> current midpoint 49.1 = +2.079...%
        self.assertIn("+2.08%", post)

    def test_missing_bank_fails_closed(self):
        broken = SAMPLE.replace(
            "<tr><td>Ziraat Bankası</td><td>48,3000</td><td>49,0000</td><td>0,7000</td></tr>",
            "",
        )
        with self.assertRaises(ValueError):
            parse_comparison_html(broken)


if __name__ == "__main__":
    unittest.main()
