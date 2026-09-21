import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from aggregator_bank_verifier import (  # noqa: E402
    parse_canlidoviz_garanti_quote,
)

ISTANBUL = ZoneInfo("Europe/Istanbul")


class AggregatorBankVerifierTests(unittest.TestCase):
    def test_canlidoviz_parses_garanti_usd_row(self):
        html = """
        <html><body>
          <div>PİYASA: AÇIK 22/09/2026 10:05:00</div>
          <table>
            <tr><th>DÖVİZ ADI</th><th>ALIŞ FİYATI</th><th>SATIŞ FİYATI</th></tr>
            <tr>
              <td><a>USD Dolar 10:04:51</a></td>
              <td>47.6750</td>
              <td>49.6750 0.11 %0.23</td>
            </tr>
            <tr>
              <td><a>EUR Euro 10:04:51</a></td>
              <td>54.9000</td>
              <td>57.1000 0.02 %0.03</td>
            </tr>
          </table>
        </body></html>
        """

        quote = parse_canlidoviz_garanti_quote(
            html,
            "USD/TRY",
            now=datetime(2026, 9, 22, 10, 10, tzinfo=ISTANBUL),
        )
        self.assertEqual(
            quote,
            (Decimal("47.6750"), Decimal("49.6750")),
        )

    def test_canlidoviz_stale_page_fails_closed(self):
        html = """
        <html><body>
          <div>PİYASA: AÇIK 21/09/2026 10:05:00</div>
          <table>
            <tr>
              <td>USD Dolar</td>
              <td>47.6750</td>
              <td>49.6750</td>
            </tr>
          </table>
        </body></html>
        """

        with self.assertRaisesRegex(ValueError, "stale"):
            parse_canlidoviz_garanti_quote(
                html,
                "USD/TRY",
                now=datetime(2026, 9, 22, 10, 10, tzinfo=ISTANBUL),
                max_age_minutes=180,
            )

    def test_canlidoviz_crossed_quote_fails_closed(self):
        html = """
        <html><body>
          <div>PİYASA: AÇIK 22/09/2026 10:05:00</div>
          <table>
            <tr>
              <td>USD Dolar</td>
              <td>50.0000</td>
              <td>49.0000</td>
            </tr>
          </table>
        </body></html>
        """

        with self.assertRaisesRegex(ValueError, "crossed"):
            parse_canlidoviz_garanti_quote(
                html,
                "USD/TRY",
                now=datetime(2026, 9, 22, 10, 10, tzinfo=ISTANBUL),
            )


if __name__ == "__main__":
    unittest.main()
