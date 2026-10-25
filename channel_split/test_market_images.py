"""Regression fixtures for the five AlanChande picture templates.

Values here are samples only; they must never be posted as current market prices.
"""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import sys
import unittest
import re
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_images import SUPPORTED_MARKETS, html_for_post, render_png, _jalali, _fa_num, _usdt_percent

SAMPLE_TIME = datetime(2026, 10, 25, 21, 30, tzinfo=ZoneInfo("Asia/Tehran"))


SAMPLES = {
    "usdt": """💎 <b>قیمت تتر در صرافی‌های ایران</b>
<pre>‎EXCHANGE       SELL      BUY    Δ24H     Δ1M
‎Nobitex        269,545  269,245 +0.28% +16.00%
‎Wallex         269,062  269,035 +0.37% +15.67%
‎Tabdeal        269,190  269,180 +0.30% +16.18%
‎Ramzinex       268,800  268,797 -0.07% +15.57%
‎Raastin        269,499  268,675 +0.14% —
‎Exir           268,500  268,400 -0.15% +15.68%
‎Bitpin         269,300  269,266 +0.35% +15.79%</pre>
⚖️ میانگین قیمت خرید: <code>269,128</code> تومان
⚖️ میانگین قیمت فروش: <code>268,943</code> تومان
🛒 کمترین قیمت خرید: <b>Exir</b> <code>268,500</code> تومان
💰 بیشترین قیمت فروش: <b>Bitpin</b>　<code>269,266</code> تومان""",
    "iran-fx": (
        "💱 <b>نرخ ارز آزاد ایران</b>\n<pre>‎CURRENCY TOMAN Δ24H Δ1M\n"
        + "\n".join(
            "‎🇺🇸 " + code + " 269,600 +0.41% +15.12%"
            for code in "USD EUR GBP CHF CAD AUD SEK NOK RUB THB SGD HKD AZN DKK AED TRY CNY SAR INR MYR AFN KWD BHD OMR QAR".split()
        )
        + "</pre>"
    ),
    "iran-gold": """🪙 <b>طلا و سکه ایران</b>
🌕 <b>سکه امامی</b>　<code>264,460,000</code>　+10.19%
🌕 <b>سکه بهار آزادی</b>　<code>256,080,000</code>　+8.47%
🟡 <b>نیم سکه</b>　<code>139,130,000</code>　+13.11%
🟡 <b>ربع سکه</b>　<code>74,500,000</code>　+14.62%
🪙 <b>سکه گرمی</b>　<code>38,000,000</code>　+11.76%
✨ <b>طلا</b>
✨ <b>طلای ۱۸ عیار</b>　<code>26,063,300</code>　+8.04%
⚖️ <b>مثقال طلا</b>　<code>112,901,000</code>　+8.04%""",
    "turkey-gold": """🥇 <b>قیمت طلای ترکیه | Kapalıçarşı</b>
<pre>🌕GOLD       SELL       BUY     Δ24H
🌕GRAM       6,458.99  6,451.39 0.00%
🌕CEYREK    10,560.44 10,322.22 -3.49%
🌕YARIM     21,120.88 20,579.93 0.00%
🌕TAM       42,113.58 41,288.88 —</pre>""",
    "fx-pulse": """📊 <b>نبض بازار ارز ترکیه | 24H</b>
<pre>MARKET    RATE Δ24H
🇺🇸USD/TL 49.7900 0.00%
🇪🇺EUR/TL 55.5750 —</pre>""",
}


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 25, 21, 0, tzinfo=ZoneInfo("Asia/Tehran"))

    def test_date(self):
        self.assertEqual(_jalali(self.now), "یکشنبه 3 آبان 1405")

    def test_all_five_templates(self):
        self.assertEqual(set(SAMPLES), SUPPORTED_MARKETS)
        for kind, sample in SAMPLES.items():
            with self.subTest(kind=kind):
                html = html_for_post(kind, sample, now=self.now)
                self.assertIn("یکشنبه ۳ آبان ۱۴۰۵", html)
                self.assertIn("@alanchande_com", html)
                self.assertIn("۲۶۹,۵۴۵" if kind=="usdt" else "<table" if kind != "fx-pulse" else "49.7900", html)
                self.assertNotIn("undefined", html)

    def test_illustrated_usdt_template(self):
        html = html_for_post("usdt", SAMPLES["usdt"], now=self.now)
        for expected in (
            "tether-icon", "exchange-logo", "usdt-summary-grid",
            "avg-buy", "avg-sell", "lowest-buy", "highest-sell",
            "۲۶۸,۵۰۰", "۲۶۹,۲۶۶", "−", "نوبیتکس", "راستین", "AlanVazir",
        ):
            self.assertIn(expected, html)

    def test_numeral_and_percentage_formatting_preserves_values(self):
        self.assertEqual(_fa_num("269,545"), "۲۶۹,۵۴۵")
        self.assertEqual(_fa_num("—"), "—")
        self.assertEqual(_fa_num("+0.28%", percent=True), "+۰٫۲۸٪")
        for raw, style, sign, digits in (
            ("+0.28%", "up", "+", "۰٫۲۸"),
            ("-0.07%", "down", "−", "۰٫۰۷"),
            ("−12.34%", "down", "−", "۱۲٫۳۴"),
            ("0.00%", "muted", "", "۰٫۰۰"),
        ):
            with self.subTest(raw=raw):
                html = _usdt_percent(raw)
                self.assertIn(f'class="{style} num percentage"', html)
                self.assertIn(f'<span class="sign">{sign}</span>', html)
                self.assertIn(digits, html)
        self.assertEqual(_usdt_percent("—"), '<span class="muted num">—</span>')

    def test_real_publisher_contract_including_persian_summary_names(self):
        from hybrid_usdt_compare import HybridUsdtQuote, build_hybrid_usdt_post
        names = ("نوبیتکس", "والکس", "تبدیل", "رمزینکس", "بیت پین")
        quotes = [HybridUsdtQuote(name, Decimal(269100 + i), Decimal(268900 + i), None, "fixture")
                  for i, name in enumerate(names)]
        approved = build_hybrid_usdt_post(quotes)
        html = html_for_post("usdt", approved, now=self.now)
        rows = re.findall(r'<tr data-exchange="[^"]+">(.*?)</tr>', html)
        self.assertEqual(len(rows), 5)
        for i, row in enumerate(rows):
            self.assertIn(f'class="buy num" dir="ltr">{_fa_num(f"{269100+i:,}")}', row)
            self.assertIn(f'class="sell num" dir="ltr">{_fa_num(f"{268900+i:,}")}', row)
        self.assertIn('summary-brand">نوبیتکس', html)
        self.assertIn('summary-brand">بیت‌پین', html)

    def test_absent_sell_data_stays_missing(self):
        from hybrid_usdt_compare import HybridUsdtQuote, build_hybrid_usdt_post
        quotes = [HybridUsdtQuote(name, Decimal(269100), None, None, "fixture")
                  for name in ("نوبیتکس", "والکس", "تبدیل", "رمزینکس", "بیت پین")]
        html = html_for_post("usdt", build_hybrid_usdt_post(quotes), now=self.now)
        self.assertEqual(html.count('class="sell num" dir="ltr">—'), 5)
        for variant in ("avg-sell", "highest-sell"):
            card = html.split(f'class="usdt-summary {variant}"', 1)[1].split('</div></div>', 1)[0]
            self.assertIn('dir="ltr">—', card)

    def test_reject_duplicate_exchange_and_invalid_summary(self):
        for corrupt in (
            SAMPLES['usdt'].replace('Wallex ', 'Nobitex '),
            SAMPLES['usdt'].replace('<b>Exir</b>', '<b>Unknown</b>'),
            SAMPLES['usdt'].replace('<code>269,128</code>', '<code>not-a-price</code>'),
        ):
            with self.assertRaises(ValueError):
                html_for_post('usdt', corrupt, now=self.now)

    def test_approved_timestamp_and_missing_timestamp(self):
        html = html_for_post('usdt', SAMPLES['usdt'] + '\n🕒 <code>07:09</code> تهران')
        self.assertIn('class="time" dir="ltr">۰۷:۰۹', html)
        html = html_for_post('usdt', SAMPLES['usdt'])
        self.assertIn('class="time" dir="ltr">—', html)
        with self.assertRaises(ValueError):
            html_for_post('usdt', SAMPLES['usdt'], now=datetime(2026, 10, 25))

    def test_repeatable_sample_and_no_external_assets(self):
        html = html_for_post('usdt', SAMPLES['usdt'], now=SAMPLE_TIME)
        self.assertEqual(html, html_for_post('usdt', SAMPLES['usdt'], now=SAMPLE_TIME))
        self.assertNotIn('src="http', html)
        self.assertNotIn('url("http', html)

    def test_variable_row_count_layout_and_demo_banner(self):
        if __import__('os').environ.get('RENDER_PNG_TESTS') != '1':
            self.skipTest('Enable RENDER_PNG_TESTS=1 for browser layout checks')
        from playwright.sync_api import sync_playwright
        from market_images import _fit_dynamic_fields, _validate_layout
        import tempfile
        import struct
        import shutil
        import os
        rows = re.search(r'(<pre>[^\n]+\n)(.*?)(</pre>)', SAMPLES['usdt'], re.S)
        original_rows = rows.group(2).splitlines()
        original_rows.append('‎AbanTether 999,999,999 999,999,998 +123.45% −12.34%')
        with sync_playwright() as playwright:
            executable = os.environ.get('ALANCHANDE_CHROMIUM_PATH') or shutil.which('chromium') or shutil.which('google-chrome')
            browser = playwright.chromium.launch(executable_path=executable, args=['--no-sandbox'])
            try:
                for count in range(5, 9):
                    sample = SAMPLES['usdt'][:rows.start(2)] + '\n'.join(original_rows[:count]) + SAMPLES['usdt'][rows.end(2):]
                    # Five-row variant excludes Exir/Bitpin; keep fixture summaries
                    # associated with rows actually present.
                    sample = sample.replace('<b>Exir</b>', '<b>Nobitex</b>').replace('<b>Bitpin</b>', '<b>Wallex</b>')
                    with self.subTest(rows=count):
                        page = browser.new_page(viewport={'width':1200, 'height':1800})
                        page.route('**/*', lambda route: route.abort())
                        page.set_content(html_for_post('usdt', sample, now=SAMPLE_TIME))
                        page.evaluate('document.fonts.ready')
                        _fit_dynamic_fields(page)
                        _validate_layout(page)
                        self.assertEqual(page.locator('tbody tr').count(), count)
                        self.assertEqual(page.locator('.canvas').bounding_box()['height'], 1500 + 90 * (count-7))
                        page.close()
            finally:
                browser.close()
        with tempfile.TemporaryDirectory() as directory:
            target = render_png('usdt', SAMPLES['usdt'], Path(directory)/'demo.png', demo=True, now=SAMPLE_TIME)
            width, height = struct.unpack('>II', target.read_bytes()[16:24])
            self.assertEqual((width,height), (2400,3080))

    def test_reject_incomplete_usdt(self):
        with self.assertRaises(ValueError):
            html_for_post("usdt", "<pre>garbled</pre>", now=self.now)

    def test_reject_unknown_currency(self):
        corrupt = SAMPLES["iran-fx"].replace("USD 269,600", "AAA 269,600")
        with self.assertRaises(ValueError):
            html_for_post("iran-fx", corrupt, now=self.now)

    def test_reject_incomplete_gold(self):
        with self.assertRaises(ValueError):
            html_for_post("turkey-gold", "<pre>GOLD PRICE</pre>", now=self.now)

    def test_no_html_injection(self):
        dangerous = SAMPLES["iran-gold"].replace("سکه امامی", "<script>alert(1)</script>")
        html = html_for_post("iran-gold", dangerous, now=self.now)
        self.assertNotIn("<script>", html)

    def test_png_render_if_requested(self):
        if __import__("os").environ.get("RENDER_PNG_TESTS") != "1":
            self.skipTest("Enable RENDER_PNG_TESTS=1 for browser screenshots")
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            for kind, sample in SAMPLES.items():
                with self.subTest(kind=kind):
                    target = render_png(kind, sample, Path(directory) / (kind+".png"))
                    self.assertGreater(target.stat().st_size, 5000)


    def test_isolated_python_worker(self):
        if __import__("os").environ.get("RENDER_PNG_TESTS") != "1":
            self.skipTest("Enable RENDER_PNG_TESTS=1 for browser screenshots")
        import os
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "iran-gold-worker.png"
            with patch.dict(os.environ, {
                "ALANCHANDE_RENDER_FORCE_WORKER": "1",
                "ALANCHANDE_RENDER_PYTHON": sys.executable,
            }):
                render_png("iran-gold", SAMPLES["iran-gold"], target)
            self.assertGreater(target.stat().st_size, 5000)


if __name__ == "__main__":
    unittest.main()
