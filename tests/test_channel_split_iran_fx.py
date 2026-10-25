import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from iran_fx import CURRENCY_ROWS, build_iran_fx_post, parse_tgju_currency_page, fetch_iran_open_market_fx  # noqa: E402


class IranFxTests(unittest.TestCase):
    def _response(self, body: str):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = body.encode("utf-8")
        return response

    def test_empty_cache_response_retries_same_source_once(self):
        with patch("iran_fx.urlopen", side_effect=[self._response(""), self._response(self._fixture_html())]) as request:
            rates = fetch_iran_open_market_fx("https://www.tgju.org/currency?language=fa",timeout=7)
        self.assertEqual(len(rates),25)
        self.assertEqual(rates["USD"],Decimal("228600"))
        self.assertEqual(request.call_count,2)
        first, second = [call.args[0] for call in request.call_args_list]
        self.assertEqual(first.full_url,"https://www.tgju.org/currency?language=fa")
        retry = urlsplit(second.full_url)
        self.assertEqual((retry.scheme,retry.netloc,retry.path),("https","www.tgju.org","/currency"))
        self.assertEqual(parse_qs(retry.query)["language"],["fa"])
        self.assertIn("_alanchande_refresh",parse_qs(retry.query))
        self.assertEqual(second.get_header("Cache-control"),"no-cache")
        self.assertTrue(all(call.kwargs["timeout"]==7 for call in request.call_args_list))

    def test_two_empty_responses_fail_without_inventing_rates(self):
        with patch("iran_fx.urlopen",side_effect=[self._response(""),self._response(" \n")]) as request:
            with self.assertRaisesRegex(RuntimeError,"empty response twice"):
                fetch_iran_open_market_fx()
        self.assertEqual(request.call_count,2)

    def test_nonempty_missing_rows_still_fail_without_retry(self):
        with patch("iran_fx.urlopen",return_value=self._response(self._fixture_html(omit="QAR"))) as request:
            with self.assertRaisesRegex(ValueError,"QAR"):
                fetch_iran_open_market_fx()
        self.assertEqual(request.call_count,1)

    def test_nonempty_challenge_page_is_not_treated_as_empty_cache(self):
        with patch("iran_fx.urlopen",return_value=self._response("<html><title>Unavailable</title></html>")) as request:
            with self.assertRaisesRegex(ValueError,"missing required rows"):
                fetch_iran_open_market_fx()
        self.assertEqual(request.call_count,1)

    def test_http_errors_are_not_retried_or_replaced_with_fixtures(self):
        with patch("iran_fx.urlopen",side_effect=HTTPError("https://www.tgju.org/currency",503,"Unavailable",{},None)) as request:
            with self.assertRaisesRegex(RuntimeError,"HTTP 503"):
                fetch_iran_open_market_fx()
        self.assertEqual(request.call_count,1)

    def test_usable_first_response_is_not_requested_again(self):
        with patch("iran_fx.urlopen",return_value=self._response(self._fixture_html())) as request:
            self.assertEqual(len(fetch_iran_open_market_fx()),25)
        self.assertEqual(request.call_count,1)

    def _fixture_html(self, *, omit: str | None = None) -> str:
        values = {
            "USD": "2,286,000",
            "EUR": "2,624,000",
            "GBP": "3,061,000",
            "CHF": "2,779,000",
            "CAD": "1,633,000",
            "AUD": "1,628,000",
            "SEK": "232,000",
            "NOK": "242,000",
            "RUB": "27,170",
            "THB": "68,570",
            "SGD": "1,791,000",
            "HKD": "291,000",
            "AZN": "1,345,000",
            "DKK": "351,000",
            "AED": "622,000",
            "TRY": "46,890",
            "CNY": "341,000",
            "SAR": "608,000",
            "INR": "23,850",
            "MYR": "559,000",
            "AFN": "35,420",
            "KWD": "7,414,000",
            "BHD": "6,081,000",
            "OMR": "5,937,000",
            "QAR": "628,000",
        }
        rows = []
        for code, _flag, name, labels in CURRENCY_ROWS:
            if code == omit:
                continue
            label = labels[0]
            rows.append(
                f"<tr><td>{label}</td><td>{values[code]}</td><td>0%</td></tr>"
            )
        return "<table>" + "".join(rows) + "</table>"

    def test_parses_required_free_market_rows_and_converts_rial_to_toman(self):
        rates = parse_tgju_currency_page(self._fixture_html())
        self.assertEqual(len(rates), 25)
        self.assertEqual(rates["USD"], Decimal("228600"))
        self.assertEqual(rates["TRY"], Decimal("4689"))
        self.assertEqual(rates["KWD"], Decimal("741400"))

    def test_missing_required_currency_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "QAR"):
            parse_tgju_currency_page(self._fixture_html(omit="QAR"))

    def test_build_post_uses_new_compact_format(self):
        rates = parse_tgju_currency_page(self._fixture_html())
        post = build_iran_fx_post(
            rates,
            {"USD": Decimal("1.25"), "TRY": Decimal("-0.50")},
            {"USD": Decimal("8.75"), "TRY": Decimal("3.20")},
        )
        self.assertIn("نرخ ارز آزاد ایران", post)
        self.assertIn("<pre>", post)
        self.assertIn("\u200eCURRENCY", post)
        self.assertIn("🇺🇸 USD", post)
        self.assertIn("228,600", post)
        self.assertIn("Δ24H", post)
        self.assertIn("Δ1M", post)
        self.assertIn("+1.25%", post)
        self.assertIn("+8.75%", post)
        self.assertIn("🇹🇷 TRY", post)
        self.assertIn("4,689", post)
        self.assertIn("💵 واحد: تومان 🇮🇷", post)
        self.assertNotIn("= دلار آمریکا", post)


    def test_build_post_can_mark_explicit_currency_unavailable(self):
        rates = parse_tgju_currency_page(self._fixture_html())
        rates.pop("AFN")

        post = build_iran_fx_post(
            rates,
            {"USD": Decimal("0.25")},
            {},
            unavailable_codes={"AFN"},
        )

        afn_line = next(
            line for line in post.splitlines() if "🇦🇫 AFN" in line
        )
        self.assertIn("—", afn_line)
        self.assertNotIn("3,542", afn_line)
        self.assertIn(
            "نرخ AFN به‌دلیل اختلاف منابع موقتاً نمایش داده نمی‌شود.",
            post,
        )

    def test_build_post_still_fails_for_unexplained_missing_currency(self):
        rates = parse_tgju_currency_page(self._fixture_html())
        rates.pop("AFN")

        with self.assertRaisesRegex(ValueError, "AFN"):
            build_iran_fx_post(rates)


if __name__ == "__main__":
    unittest.main()
