"""Offline tests for the verified AlanChande daily market digest."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from daily_market_digest import (  # noqa: E402
    CRYPTO_DISPLAY,
    FX_DISPLAY,
    GOLD_DISPLAY,
    build_digest_post,
    parse_dolarchand_iqd100_toman,
    parse_dolarchand_toman_rate,
    parse_dolarchand_xau_usd,
)


class DailyMarketDigestTests(unittest.TestCase):
    def _values(self) -> dict[str, Decimal]:
        values = {
            "USD": Decimal("231300"),
            "EUR": Decimal("265700"),
            "USDT": Decimal("230800"),
            "AED": Decimal("62970"),
            "TRY": Decimal("4810"),
            "CNY": Decimal("34640"),
            "CAD": Decimal("165400"),
            "AUD": Decimal("164800"),
            "GBP": Decimal("306700"),
            "IQD100": Decimal("14780"),
            "AFN": Decimal("3575"),
            "COIN_EMAMI": Decimal("239000000"),
            "COIN_AZADI": Decimal("235000000"),
            "COIN_HALF": Decimal("122000000"),
            "COIN_QUARTER": Decimal("65000000"),
            "MESGHAL": Decimal("104400000"),
            "GOLD18": Decimal("24100840"),
            "XAUUSD": Decimal("4378.12"),
            "BTC": Decimal("81179"),
            "ETH": Decimal("2620"),
            "BNB": Decimal("759.9"),
            "TRX": Decimal("0.33456"),
            "SHIB": Decimal("0.0000055"),
            "ADA": Decimal("0.227"),
            "DOGE": Decimal("0.0866"),
            "GRAM": Decimal("1.600"),
            "NOT": Decimal("0.00048"),
            "SOL": Decimal("109.4"),
            "XRP": Decimal("1.402"),
        }
        self.assertEqual(
            len(values),
            len(FX_DISPLAY) + len(GOLD_DISPLAY) + len(CRYPTO_DISPLAY),
        )
        return values

    def test_full_post_contains_all_29_prices_and_fits_telegram(self):
        values = self._values()
        changes = {key: Decimal("0.52") for key in values}
        changes["BTC"] = Decimal("-0.79")
        now = datetime(2026, 9, 24, 12, 5, tzinfo=ZoneInfo("Asia/Tehran"))
        post = build_digest_post(values, changes, now=now)
        post = post.translate(dict.fromkeys(map(ord, "\u200f\u2066\u2069")))
        for key, _flag, label in (*FX_DISPLAY, *GOLD_DISPLAY, *CRYPTO_DISPLAY):
            self.assertIn(label, post)
        self.assertIn("گرام (تون کوین)", post)
        self.assertIn("<b>بیت کوین</b> (BTC)", post)
        self.assertIn("<b>اتریوم</b> (ETH)", post)
        self.assertIn("<b>ترون</b> (TRX)", post)
        self.assertIn("<b>شیبا</b> (SHIB)", post)
        self.assertIn("<b>گرام (تون کوین)</b> (GRAM)", post)
        self.assertIn("🔼 %0.52", post)
        self.assertIn("🔻 %0.79", post)
        self.assertIn("@alanchande_com", post)
        self.assertLessEqual(len(post), 4096)

    def test_missing_price_is_rejected(self):
        values = self._values()
        del values["BTC"]
        with self.assertRaisesRegex(ValueError, "BTC"):
            build_digest_post(values)

    def test_rtl_rows_keep_all_prices_and_latin_tokens_isolated(self):
        values = self._values()
        changes = {key: Decimal("0.52") for key in values}
        changes["BTC"] = Decimal("-0.79")
        post = build_digest_post(values, changes)
        for line in post.splitlines():
            if line:
                self.assertTrue(line.startswith("\u200f"))
                self.assertEqual(line.count("\u2066"), line.count("\u2069"))
        self.assertEqual(post.count("\u2066<code>"), len(values))
        self.assertEqual(post.count("</code>\u2069"), len(values))
        self.assertIn("\u2066(BTC)\u2069", post)
        self.assertIn("\u2066<code>81,179$</code>\u2069", post)
        self.assertIn("\u2066🔼 %0.52\u2069", post)
        self.assertIn("\u2066🔻 %0.79\u2069", post)
        self.assertIn("\u2066➖ —\u2069", build_digest_post(values))
        self.assertLessEqual(len(post), 4096)

    def test_no_history_renders_dash_not_fake_change(self):
        post = build_digest_post(self._values())
        self.assertIn("➖ —", post)

    def test_dolarchand_fx_parser(self):
        html = "<div>Sell rate for US Dollar to Toman 232,900</div>"
        self.assertEqual(parse_dolarchand_toman_rate(html), Decimal("232900"))

    def test_dolarchand_iqd_parser_does_not_capture_literal_100(self):
        html = """
        <h1>100 Iraqi Dinar</h1>
        <div>Sell rate for 100 Iraqi Dinar to Toman 15,080</div>
        """
        self.assertEqual(
            parse_dolarchand_iqd100_toman(html),
            Decimal("15080"),
        )

    def test_dolarchand_xau_parser(self):
        html = """
        <div>Sell rate for Gold Ounce (Global) to USD 4,284.49</div>
        """
        self.assertEqual(
            parse_dolarchand_xau_usd(html),
            Decimal("4284.49"),
        )


if __name__ == "__main__":
    unittest.main()
