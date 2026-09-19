from decimal import Decimal

from gold_prices import build_turkish_gold_post, parse_buy_sell
from iran_gold import build_iran_gold_post, parse_tgju_home
from iran_usdt import (
    build_usdt_exchange_post,
    parse_usdt_comparison_html,
    select_preferred_quotes,
)


def test_turkish_gold_pair_parser_and_formatter():
    html = """
    <html><body>
      <div>Alış / Satış</div>
      <div>6.805,42 / 6.811,71</div>
    </body></html>
    """
    buy, sell = parse_buy_sell(html)
    assert buy == Decimal("6805.42")
    assert sell == Decimal("6811.71")


def test_iran_gold_parses_rial_rows_and_builds_toman_post():
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
    assert market.coin_prices_rial["سکه امامی"] == Decimal("2375000000")
    assert market.bubble_values_rial["حباب سکه امامی"] == Decimal("-2050000")
    assert market.gold18_rial == Decimal("239392400")
    assert market.mesghal_rial == Decimal("1037000000")

    post = build_iran_gold_post(market)
    assert "<code>237,500,000</code>" in post
    assert "<code>23,939,240</code>" in post
    assert "<code>-205,000</code>" in post


def _usdt_row(name, sell, buy, change, date_time):
    return (
        f"<tr><td>{name}</td><td>{sell} ریال</td><td>{buy} ریال</td>"
        f"<td>{change}</td><td>2,400,000 ریال</td><td>2,200,000 ریال</td>"
        f"<td>{date_time}</td></tr>"
    )


def test_usdt_comparison_filters_stale_and_outlier_rows():
    html = "<table>" + "".join(
        [
            _usdt_row("والکس", "2,291,210", "2,291,190", "20,490 (0.9%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۳۰"),
            _usdt_row("نوبیتکس", "2,292,000", "2,291,600", "23,020 (1%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۳۰"),
            _usdt_row("رمزینکس", "2,290,500", "0", "26,132 (1.15%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۲۹"),
            _usdt_row("بیت پین", "2,289,430", "0", "20,390 (0.9%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۲۹"),
            _usdt_row("آبان تتر", "2,298,630", "2,284,210", "28,530 (1.26%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۲۸"),
            _usdt_row("تبدیل", "2,291,980", "0", "27,480 (1.21%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۲۶"),
            _usdt_row("تترلند", "2,291,500", "0", "24,500 (1.08%)", "۱۴۰۵/۰۶/۲۸ - ۱۵:۵۸"),
            # Same date, but extreme unit/error outlier.
            _usdt_row("اکسیر", "229,832", "0", "2,860 (1.26%)", "۱۴۰۵/۰۶/۲۸ - ۱۶:۲۵"),
            # Old-date stale row.
            _usdt_row("پینگی", "1,944,020", "0", "36,640 (1.92%)", "۱۴۰۵/۰۵/۰۷ - ۱۸:۰۴"),
        ]
    ) + "</table>"

    quotes = parse_usdt_comparison_html(html)
    selected = select_preferred_quotes(quotes)
    names = [q.exchange for q in selected]
    assert "والکس" in names
    assert "آبان تتر" in names
    assert "تترلند" in names
    assert "اکسیر" not in names

    post = build_usdt_exchange_post(quotes)
    assert "قیمت تتر در صرافی‌های ایران" in post
    assert "<code>229,121</code>" in post
    assert "➗ <b>میانگین</b>" in post
