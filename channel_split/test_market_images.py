"""Regression fixtures for the five AlanChande picture templates.

Values here are samples only; they must never be posted as current market prices.
"""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_images import SUPPORTED_MARKETS, html_for_post, render_png, _jalali


SAMPLES = {
    "usdt": """💎 <b>قیمت تتر در صرافی‌های ایران</b>
<pre>‎EXCHANGE       SELL      BUY    Δ24H     Δ1M
‎Wallex         269,545  269,245 +0.28% +16.00%
‎Nobitex        269,545  269,245 +0.28% +16.00%
‎Ramzinex       269,545  269,245 -0.07% +16.00%
‎Bitpin         269,545  269,245 +0.28% +16.00%
‎Tabdeal        269,545  269,245 +0.28% +16.00%
‎Exir           269,545  269,245 +0.28% +16.00%
‎AbanTether     269,545  269,245 +0.28% +16.00%</pre>
⚖️ میانگین قیمت خرید: <code>269,545</code> تومان
⚖️ میانگین قیمت فروش: <code>269,245</code> تومان
🛒 کمترین قیمت خرید: <b>Exir</b> <code>269,545</code> تومان
💰 بیشترین قیمت فروش: <b>Bitpin</b>　<code>269,245</code> تومان""",
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
                self.assertIn("269,545" if kind=="usdt" else "<table" if kind != "fx-pulse" else "49.7900", html)
                self.assertNotIn("undefined", html)

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
