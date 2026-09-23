import sys
import unittest
from decimal import Decimal
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from gold_prices import GoldQuote, build_turkish_gold_post, parse_buy_sell  # noqa: E402
import iran_gold  # noqa: E402
from iran_gold import (  # noqa: E402
    IranGoldMarket,
    build_iran_gold_post,
    parse_tgju_home,
    parse_tgju_profile_current,
)
from iran_usdt import (  # noqa: E402
    build_usdt_exchange_post,
    parse_usdt_comparison_html,
    select_preferred_quotes,
)


class MarketPostTests(unittest.TestCase):
    def test_turkish_gold_pair_parser(self):
        html = """
        <html><body>
          <div>Alış / Satış</div>
          <div>6.805,42 / 6.811,71</div>
        </body></html>
        """
        buy, sell = parse_buy_sell(html)
        self.assertEqual(buy, Decimal("6805.42"))
        self.assertEqual(sell, Decimal("6811.71"))

    def test_turkish_gold_post_is_compact_table(self):
        quotes = [
            GoldQuote("gram", "گرم طلا", "https://example.test/gram", Decimal("6826.39"), Decimal("6834.09")),
            GoldQuote("quarter", "ربع سکه", "https://example.test/quarter", Decimal("10922.22"), Decimal("11173.73")),
            GoldQuote("half", "نیم سکه", "https://example.test/half", Decimal("21776.17"), Decimal("22347.46")),
            GoldQuote("tam", "تمام سکه", "https://example.test/tam", Decimal("44332"), Decimal("44638")),
        ]

        post = build_turkish_gold_post(quotes)
        self.assertIn("<pre>", post)
        self.assertIn("🌕GOLD", post)
        self.assertIn("SELL", post)
        self.assertIn("BUY", post)
        self.assertIn("Δ24H", post)
        self.assertIn("🌕GRAM", post)
        self.assertIn("🌕CEYREK", post)
        self.assertIn("🌕YARIM", post)
        self.assertIn("🌕TAM", post)
        self.assertNotIn("Republic", post)
        self.assertIn("6,834.09", post)
        self.assertIn("6,826.39", post)
        self.assertIn("—", post)
        self.assertIn("💵 واحد: لیر ترکیه 🇹🇷", post)
        self.assertIn("استانبول", post)
        self.assertIn("قیمت‌ها صرفاً جهت اطلاع‌رسانی است.", post)

    def test_turkish_gold_24h_change_uses_midpoint(self):
        quotes = [
            GoldQuote(
                "gram",
                "گرم طلا",
                "https://example.test/gram",
                Decimal("7000"),
                Decimal("7020"),
            ),
        ]
        previous = {
            "gram": (Decimal("6800"), Decimal("6820")),
        }

        post = build_turkish_gold_post(quotes, previous)
        # Previous midpoint 6810 -> current midpoint 7010 = +2.936...%
        self.assertIn("+2.94%", post)

    def test_iran_gold_profile_parser_reads_current_rate(self):
        html = """
        <html><body>
          <h1>سکه امامی</h1>
          <div>نرخ فعلی:: 2,390,050,000 -</div>
          <div>واحد پولی : ریال</div>
        </body></html>
        """
        self.assertEqual(
            parse_tgju_profile_current(html),
            Decimal("2390050000"),
        )

    def test_iran_gold_fetch_falls_back_to_dedicated_profiles(self):
        values = {
            "sekee": "2,390,050,000",
            "sekeb": "2,351,000,000",
            "nim": "1,220,000,000",
            "rob": "650,000,000",
            "gerami": "330,000,000",
            "geram18": "241,814,000",
            "mesghal": "1,047,490,000",
        }

        def fake_fetch(url, timeout):
            if url.endswith("/home"):
                return "<html><body>homepage layout changed</body></html>"
            slug = url.rsplit("/", 1)[-1]
            value = values[slug]
            return (
                "<html><body>"
                f"<h1>{slug}</h1>"
                f"<div>نرخ فعلی:: {value} -</div>"
                "</body></html>"
            )

        with patch.object(
            iran_gold,
            "_fetch_tgju_html",
            side_effect=fake_fetch,
        ):
            market = iran_gold.fetch_iran_gold_market()

        self.assertEqual(
            market.coin_prices_rial["سکه امامی"],
            Decimal("2390050000"),
        )
        self.assertEqual(
            market.gold18_rial,
            Decimal("241814000"),
        )
        self.assertEqual(market.bubble_values_rial, {})

    def test_iran_gold_post_omits_bubbles_when_fallback_has_none(self):
        market = IranGoldMarket(
            coin_prices_rial={
                "سکه امامی": Decimal("2390050000"),
                "سکه بهار آزادی": Decimal("2351000000"),
                "نیم سکه": Decimal("1220000000"),
                "ربع سکه": Decimal("650000000"),
                "سکه گرمی": Decimal("330000000"),
            },
            bubble_values_rial={},
            gold18_rial=Decimal("241814000"),
            mesghal_rial=Decimal("1047490000"),
        )

        post = build_iran_gold_post(market)

        self.assertIn("سکه امامی", post)
        self.assertIn("طلای ۱۸ عیار", post)
        self.assertNotIn("🎈 <b>حباب سکه</b>", post)

    def test_iran_gold_parses_rial_rows_and_builds_toman_post(self):
        html = """
        <table>
          <tr><td>سکه امامی</td><td>2,375,000,000</td><td>0</td></tr>
          <tr><td>سکه بهار آزادی</td><td>2,330,000,000</td><td>0</td></tr>
          <tr><td>نیم سکه</td><td>1,210,000,000</td><td>0</td></tr>
          <tr><td>ربع سکه</td><td>645,000,000</td><td>0</td></tr>
          <tr><td>سکه گرمی</td><td>330,000,000</td><td>0</td></tr>

          <tr><td>حباب سکه امامی</td><td>-2,050,000</td><td>0</td></tr>
          <tr><td>حباب سکه بهار آزادی</td><td>19,800,000</td><td>0</td></tr>
          <tr><td>حباب نیم سکه</td><td>118,983,000</td><td>0</td></tr>
          <tr><td>حباب ربع سکه</td><td>59,613,000</td><td>0</td></tr>
          <tr><td>حباب سکه گرمی</td><td>163,680,000</td><td>0</td></tr>

          <tr><td>طلای 18 عیار</td><td>239,392,400</td><td>0</td></tr>
          <tr><td>مثقال طلا</td><td>1,037,000,000</td><td>0</td></tr>
        </table>
        """
        market = parse_tgju_home(html)
        self.assertEqual(market.coin_prices_rial["سکه امامی"], Decimal("2375000000"))
        self.assertEqual(market.bubble_values_rial["حباب سکه امامی"], Decimal("-2050000"))
        self.assertEqual(market.gold18_rial, Decimal("239392400"))
        self.assertEqual(market.mesghal_rial, Decimal("1037000000"))

        post = build_iran_gold_post(market)
        self.assertNotIn("<pre>", post)
        self.assertIn("سکه امامی", post)
        self.assertIn("سکه بهار آزادی", post)
        self.assertIn("نیم سکه", post)
        self.assertIn("ربع سکه", post)
        self.assertIn("سکه گرمی", post)
        self.assertIn("طلای ۱۸ عیار", post)
        self.assertIn("مثقال طلا", post)
        self.assertNotIn("حباب سکه", post)
        self.assertIn("Δ24H", post)
        self.assertIn("—", post)
        self.assertIn("237,500,000", post)
        self.assertIn("23,939,240", post)
        self.assertNotIn("-205,000", post)
        self.assertNotIn("IMAMI", post)
        self.assertNotIn("GOLD18", post)
        self.assertIn("قیمت‌ها صرفاً جهت اطلاع‌رسانی است.", post)

    def test_iran_gold_24h_change_uses_price_history(self):
        market = parse_tgju_home(
            """
            <table>
              <tr><td>سکه امامی</td><td>2,400,000,000</td></tr>
              <tr><td>سکه بهار آزادی</td><td>2,300,000,000</td></tr>
              <tr><td>نیم سکه</td><td>1,200,000,000</td></tr>
              <tr><td>ربع سکه</td><td>600,000,000</td></tr>
              <tr><td>سکه گرمی</td><td>300,000,000</td></tr>
              <tr><td>حباب سکه امامی</td><td>10,000,000</td></tr>
              <tr><td>حباب سکه بهار آزادی</td><td>10,000,000</td></tr>
              <tr><td>حباب نیم سکه</td><td>10,000,000</td></tr>
              <tr><td>حباب ربع سکه</td><td>10,000,000</td></tr>
              <tr><td>حباب سکه گرمی</td><td>10,000,000</td></tr>
              <tr><td>طلای 18 عیار</td><td>240,000,000</td></tr>
              <tr><td>مثقال طلا</td><td>1,000,000,000</td></tr>
            </table>
            """
        )
        previous = {
            "سکه امامی": Decimal("2300000000"),
            "سکه بهار آزادی": Decimal("2300000000"),
            "نیم سکه": Decimal("1200000000"),
            "ربع سکه": Decimal("600000000"),
            "سکه گرمی": Decimal("300000000"),
            "طلای ۱۸ عیار": Decimal("230000000"),
            "مثقال طلا": Decimal("1000000000"),
        }

        post = build_iran_gold_post(market, previous)
        self.assertIn("+4.35%", post)
        self.assertNotIn("<code>+4.35%</code>", post)
        self.assertNotIn("<code>0.00%</code>", post)

    @staticmethod
    def _usdt_row(name, sell, buy, change, date_time):
        return (
            f"<tr><td>{name}</td><td>{sell} ریال</td><td>{buy} ریال</td>"
            f"<td>{change}</td><td>2,400,000 ریال</td><td>2,200,000 ریال</td>"
            f"<td>{date_time}</td></tr>"
        )

    def test_usdt_comparison_filters_stale_and_outlier_rows(self):
        html = "<table>" + "".join(
            [
                self._usdt_row("والکس", "2,291,210", "2,291,190", "20,490 (0.9%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۳۰"),
                self._usdt_row("نوبیتکس", "2,292,000", "2,291,600", "23,020 (1%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۳۰"),
                self._usdt_row("رمزینکس", "2,290,500", "0", "26,132 (1.15%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۲۹"),
                self._usdt_row("بیت پین", "2,289,430", "0", "20,390 (0.9%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۲۹"),
                self._usdt_row("آبان تتر", "2,298,630", "2,284,210", "28,530 (1.26%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۲۸"),
                self._usdt_row("تبدیل", "2,291,980", "0", "27,480 (1.21%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۲۶"),
                self._usdt_row("تترلند", "2,291,500", "0", "24,500 (1.08%)", "۱۴۰۵/۰۶/۲۸ - ۱۵:۵۸"),
                # Same date but wrong unit / extreme outlier.
                self._usdt_row("اکسیر", "229,832", "0", "2,860 (1.26%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۲۵"),
                # Old-date stale row.
                self._usdt_row("پینگی", "1,944,020", "0", "36,640 (1.92%)", "۱۴۰۵/۰۵/۰۷ - ۱۸:۰۴"),
            ]
        ) + "</table>"

        quotes = parse_usdt_comparison_html(html)
        selected = select_preferred_quotes(quotes)
        names = [q.exchange for q in selected]

        self.assertIn("والکس", names)
        self.assertIn("آبان تتر", names)
        self.assertIn("تترلند", names)
        self.assertNotIn("اکسیر", names)

        post = build_usdt_exchange_post(quotes)
        self.assertIn("قیمت تتر در صرافی‌های ایران", post)
        self.assertIn("<code>229,121</code>", post)
        self.assertIn("➗ <b>میانگین</b>", post)


if __name__ == "__main__":
    unittest.main()
