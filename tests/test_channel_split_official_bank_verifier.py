import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from official_bank_verifier import (  # noqa: E402
    _find_string_by_key,
    parse_garanti_quote,
    parse_isbank_midpoint,
    parse_kuveyt_quote,
    parse_ziraat_midpoint,
)


class OfficialBankVerifierTests(unittest.TestCase):
    def test_isbank_parses_official_bank_row(self):
        html = """
        <table>
          <tr><th>Döviz Cinsi</th><th>Banka Alış</th><th>Banka Satış</th></tr>
          <tr><td>USD Amerikan Doları</td><td>47,314</td><td>49,9294</td></tr>
          <tr><td>EUR Avrupa Para Birimi</td><td>54,9174</td><td>57,958</td></tr>
        </table>
        """
        self.assertEqual(
            parse_isbank_midpoint(html, "USD/TRY"),
            (Decimal("47.314") + Decimal("49.9294")) / Decimal("2"),
        )

    def test_garanti_config_key_can_be_nested_under_changed_wrapper(self):
        payload = {
            "runtime": {
                "config": {
                    "source": {
                        "app_properties": {
                            "common": {
                                "expandedCurrRateServicePath": (
                                    "https://customers.garantibbva.com.tr/"
                                    "currency-management-pb/example"
                                )
                            }
                        }
                    }
                }
            }
        }
        self.assertEqual(
            _find_string_by_key(
                payload,
                "expandedCurrRateServicePath",
            ),
            (
                "https://customers.garantibbva.com.tr/"
                "currency-management-pb/example"
            ),
        )

    def test_garanti_config_duplicate_service_keys_fail_closed(self):
        payload = {
            "a": {"expandedCurrRateServicePath": "https://a.example"},
            "b": {"expandedCurrRateServicePath": "https://b.example"},
        }
        with self.assertRaisesRegex(ValueError, "multiple"):
            _find_string_by_key(
                payload,
                "expandedCurrRateServicePath",
            )

    def test_garanti_parses_official_expanded_rate_row(self):
        payload = {
            "expandedCurrRateRespons": [
                {
                    "currCode": "USD",
                    "exchBuyRate": 47.675,
                    "exchSellRate": 49.675,
                },
                {
                    "currCode": "EUR",
                    "exchBuyRate": 54.9,
                    "exchSellRate": 57.1,
                },
            ]
        }

        self.assertEqual(
            parse_garanti_quote(payload, "USD/TRY"),
            (Decimal("47.675"), Decimal("49.675")),
        )

    def test_garanti_nested_response_is_supported(self):
        payload = {
            "data": {
                "result": {
                    "expandedCurrRateRespons": [
                        {
                            "currCode": "USD",
                            "exchBuyRate": "47.675",
                            "exchSellRate": "49.675",
                        }
                    ]
                }
            }
        }
        self.assertEqual(
            parse_garanti_quote(payload, "USD/TRY"),
            (Decimal("47.675"), Decimal("49.675")),
        )

    def test_garanti_missing_or_crossed_row_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "missing USD"):
            parse_garanti_quote(
                {"expandedCurrRateRespons": []},
                "USD/TRY",
            )

        with self.assertRaisesRegex(ValueError, "invalid"):
            parse_garanti_quote(
                {
                    "expandedCurrRateRespons": [
                        {
                            "currCode": "USD",
                            "exchBuyRate": 50,
                            "exchSellRate": 49,
                        }
                    ]
                },
                "USD/TRY",
            )

    def test_kuveyt_parses_official_exchange_rates_row(self):
        payload = [
            {
                "Title": "USD",
                "CurrencyCode": "USD",
                "BuyRate": 48.14757,
                "SellRate": 49.25438,
            },
            {
                "Title": "EUR",
                "CurrencyCode": "EUR",
                "BuyRate": 55.10406,
                "SellRate": 56.37895,
            },
        ]

        self.assertEqual(
            parse_kuveyt_quote(payload, "USD/TRY"),
            (Decimal("48.14757"), Decimal("49.25438")),
        )

    def test_kuveyt_missing_or_crossed_row_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "missing USD"):
            parse_kuveyt_quote([], "USD/TRY")

        with self.assertRaisesRegex(ValueError, "invalid"):
            parse_kuveyt_quote(
                [
                    {
                        "CurrencyCode": "USD",
                        "BuyRate": 50,
                        "SellRate": 49,
                    }
                ],
                "USD/TRY",
            )

    def test_ziraat_selects_official_channel_matching_displayed_row(self):
        html = """
        <table>
          <tr>
            <td>USD</td><td>AMERIKAN DOLARI</td>
            <td>48,2675</td><td>49,2893</td><td>48,1951</td><td>49,4372</td>
          </tr>
        </table>
        <table>
          <tr>
            <td>USD</td><td>AMERIKAN DOLARI</td>
            <td>47,3432</td><td>50,2255</td>
          </tr>
        </table>
        """
        primary = (Decimal("47.3432") + Decimal("50.2255")) / Decimal("2")
        self.assertEqual(
            parse_ziraat_midpoint(
                html,
                "USD/TRY",
                primary_midpoint=primary,
            ),
            primary,
        )

    def test_ziraat_rejects_page_when_no_channel_matches_displayed_rate(self):
        html = """
        <table>
          <tr>
            <td>USD</td><td>AMERIKAN DOLARI</td>
            <td>40,00</td><td>41,00</td>
          </tr>
        </table>
        """
        with self.assertRaisesRegex(ValueError, "matches"):
            parse_ziraat_midpoint(
                html,
                "USD/TRY",
                primary_midpoint=Decimal("49"),
                max_mapping_deviation_pct=Decimal("2"),
            )

    def test_missing_currency_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "no usable"):
            parse_isbank_midpoint(
                "<table><tr><td>GBP</td><td>60,1</td><td>62,2</td></tr></table>",
                "USD/TRY",
            )


if __name__ == "__main__":
    unittest.main()
