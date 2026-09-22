import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from iran_fx_pashizi import (  # noqa: E402
    TARGET_CODES,
    parse_pashizi_currency_detail,
    parse_pashizi_fx_page,
)


class PashiziIranFxTests(unittest.TestCase):
    def test_parses_all_25_target_currencies_to_toman_midpoints(self):
        rows = []
        for index, code in enumerate(TARGET_CODES, start=1):
            sell = 2_000_000 + index * 10_000
            buy = sell - 2_000
            rows.append(
                f"<div><a>{code}</a>"
                f"<span>Sell (IRR){sell:,}</span>"
                f"<span>Buy (IRR){buy:,}</span></div>"
            )
        html = (
            "<html><body><div>last update: Wed 12:34</div>"
            + "".join(rows)
            + "</body></html>"
        )

        rates, updated = parse_pashizi_fx_page(html)

        self.assertEqual(len(rates), 25)
        self.assertEqual(updated, "Wed 12:34")
        self.assertEqual(
            rates["USD"],
            (Decimal("2010000") + Decimal("2008000")) / Decimal("20"),
        )

    def test_parses_currency_detail_title_and_update_time(self):
        raw = (
            "<html><head>"
            "<title>USD Price Today: 2,315,000 IRR | Iran Free Market Rate</title>"
            "</head><body>"
            "<div>last update: Tue 18:50</div>"
            "<h1>USD/IRR Exchange Rate &amp; Market Trends</h1>"
            "</body></html>"
        )

        rate, updated = parse_pashizi_currency_detail(raw, "USD")

        self.assertEqual(rate, Decimal("231500"))
        self.assertEqual(updated, "Tue 18:50")


    def test_missing_currency_fails_closed(self):
        html = (
            "<div>last update: Wed 12:34</div>"
            "<div>USD Sell (IRR)2,000,000 Buy (IRR)1,999,000</div>"
        )
        with self.assertRaisesRegex(ValueError, "missing required currencies"):
            parse_pashizi_fx_page(html)


if __name__ == "__main__":
    unittest.main()
