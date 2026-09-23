import io
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from official_bank_verifier import (  # noqa: E402
    _discover_garanti_expanded_rate_url,
    _find_string_by_key,
    _garanti_public_request_headers,
    _fetch_json_post,
    fetch_garanti_quote,
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

    def test_garanti_flattened_config_discovers_exact_property(self):
        endpoint = (
            "https://customers.garantibbva.com.tr/"
            "currency-management-pb/expanded-rates"
        )
        payload = {
            "source": {
                "app_properties.common.expandedCurrRateServicePath": endpoint,
                "app_properties.common.baseUrl": "https://example.invalid",
            }
        }
        self.assertEqual(
            _find_string_by_key(payload, "expandedCurrRateServicePath"),
            endpoint,
        )
        with patch("official_bank_verifier._fetch_json", return_value=payload):
            self.assertEqual(_discover_garanti_expanded_rate_url(), endpoint)

    def test_garanti_flattened_config_still_rejects_unofficial_host(self):
        payload = {
            "source": {
                "app_properties.common.expandedCurrRateServicePath": (
                    "https://unrelated.example/expanded-rates"
                )
            }
        }
        with patch("official_bank_verifier._fetch_json", return_value=payload):
            with self.assertRaisesRegex(ValueError, "escaped official host"):
                _discover_garanti_expanded_rate_url()

    def test_garanti_flattened_key_requires_exact_segment(self):
        payload = {
            "source": {
                "app_properties.common.notexpandedCurrRateServicePath": (
                    "https://customers.garantibbva.com.tr/incorrect"
                )
            }
        }
        with self.assertRaisesRegex(ValueError, "missing"):
            _find_string_by_key(payload, "expandedCurrRateServicePath")

    def test_garanti_conflicting_flat_and_nested_keys_fail_closed(self):
        payload = {
            "source": {
                "app_properties.common.expandedCurrRateServicePath": (
                    "https://customers.garantibbva.com.tr/a"
                )
            },
            "fallback": {
                "expandedCurrRateServicePath": (
                    "https://customers.garantibbva.com.tr/b"
                )
            },
        }
        with self.assertRaisesRegex(ValueError, "multiple"):
            _find_string_by_key(payload, "expandedCurrRateServicePath")

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

    def _garanti_public_config(self):
        return {
            "source": {
                "app_properties.common.expandedCurrRateServicePath": (
                    "https://customers.garantibbva.com.tr/"
                    "currency-management-pb/currency-management-public/"
                    "v0/expanded-curr-rate/curr-rate"
                ),
                "app_properties.application.components.authentication.clientId": (
                    "public-config-client-id"
                ),
            }
        }

    def test_garanti_public_headers_use_config_and_ephemeral_ids(self):
        config = self._garanti_public_config()
        first = _garanti_public_request_headers(config)
        second = _garanti_public_request_headers(config)
        self.assertEqual(first["client-id"], "public-config-client-id")
        self.assertEqual(first["Accept"], "application/json")
        self.assertEqual(first["Accept-Language"], "en-GB,en;q=0.8")
        self.assertIn("Chrome/153.0.0.0", first["User-Agent"])
        self.assertEqual(first["Authorization"], "")
        self.assertEqual(first["state"], "")
        self.assertEqual(first["tenant-app-id"], "")
        self.assertEqual(first["channel"], "Internet")
        self.assertEqual(first["client-type"], "ArkClient")
        self.assertEqual(first["dialect"], "TR")
        self.assertEqual(first["ip"], "127.0.0.1")
        self.assertEqual(first["tenant-company-id"], "GAR")
        self.assertEqual(first["tenant-geolocation"], "TUR")
        self.assertEqual(first["guid"], first["x-client-trace-id"])
        self.assertEqual(len(first["guid"]), 32)
        self.assertEqual(len(first["client-session-id"].split("-")), 5)
        self.assertNotEqual(first["guid"], second["guid"])
        self.assertNotEqual(
            first["client-session-id"], second["client-session-id"]
        )
        self.assertNotIn("Cookie", first)
        self.assertEqual(first["Authorization"], "")

    def test_garanti_missing_public_client_id_fails_closed(self):
        config = {
            "source": {
                "app_properties.common.expandedCurrRateServicePath": (
                    "https://customers.garantibbva.com.tr/rates"
                )
            }
        }
        with patch("official_bank_verifier._fetch_json", return_value=config):
            with patch("official_bank_verifier._fetch_json_post") as post:
                with self.assertRaisesRegex(ValueError, "missing clientId"):
                    fetch_garanti_quote("USD/TRY")
                post.assert_not_called()

    def test_garanti_live_fetch_builds_public_request_metadata(self):
        config = self._garanti_public_config()
        official_response = {
            "expandedCurrRateRespons": [
                {
                    "currCode": "USD",
                    "exchBuyRate": "48.01",
                    "exchSellRate": "49.21",
                }
            ]
        }
        with patch("official_bank_verifier._fetch_json", return_value=config) as get:
            with patch(
                "official_bank_verifier._fetch_json_post",
                return_value=official_response,
            ) as post:
                self.assertEqual(
                    fetch_garanti_quote("USD/TRY"),
                    (Decimal("48.01"), Decimal("49.21")),
                )
        get.assert_called_once()
        args, kwargs = post.call_args
        self.assertTrue(args[0].startswith("https://customers.garantibbva.com.tr/"))
        self.assertEqual(args[1]["parityParamName"], "DOVIZ_PUBLIC")
        self.assertEqual(args[1]["latencyValue"], 1800)
        self.assertEqual(kwargs["referer"], "https://webforms.garantibbva.com.tr/")
        self.assertEqual(kwargs["extra_headers"]["client-id"], "public-config-client-id")
        self.assertEqual(
            kwargs["extra_headers"]["guid"],
            kwargs["extra_headers"]["x-client-trace-id"],
        )

    def test_post_passes_public_headers_without_cookies_or_auth(self):
        payload = {"parityParamName": "DOVIZ_PUBLIC"}
        extra = _garanti_public_request_headers(self._garanti_public_config())
        fake_reply = io.BytesIO(b'{"ok": true}')
        with patch("official_bank_verifier.urlopen", return_value=fake_reply) as send:
            result = _fetch_json_post(
                "https://customers.garantibbva.com.tr/test",
                payload,
                extra_headers=extra,
                origin="https://webforms.garantibbva.com.tr",
                referer="https://webforms.garantibbva.com.tr/",
            )
        self.assertEqual(result, {"ok": True})
        request = send.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), payload)
        self.assertEqual(headers["client-id"], "public-config-client-id")
        self.assertEqual(headers["guid"], headers["x-client-trace-id"])
        self.assertEqual(headers["ip"], "127.0.0.1")
        self.assertEqual(headers["authorization"], "")
        self.assertEqual(headers["state"], "")
        self.assertEqual(headers["tenant-app-id"], "")
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["accept-language"], "en-GB,en;q=0.8")
        self.assertIn("Chrome/153.0.0.0", headers["user-agent"])
        self.assertNotIn("cookie", headers)

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
