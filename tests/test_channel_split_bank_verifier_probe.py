import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from probe_bank_verifier_sources import (  # noqa: E402
    AssetParser,
    _flatten_json,
    extract_context_snippets,
    extract_endpoint_candidates,
    extract_kuveyt_api_tokens,
)


class BankVerifierProbeTests(unittest.TestCase):
    def test_asset_parser_finds_scripts_iframes_and_preloaded_js(self):
        parser = AssetParser()
        parser.feed(
            """
            <html>
              <script src="/static/app.js"></script>
              <iframe src="https://forms.example.test/rates"></iframe>
              <link rel="preload" href="/assets/chunk.js">
            </html>
            """
        )

        self.assertEqual(parser.assets, ["/static/app.js", "/assets/chunk.js"])
        self.assertEqual(
            parser.iframes,
            ["https://forms.example.test/rates"],
        )

    def test_flatten_json_keeps_nested_config_paths(self):
        rows = dict(
            _flatten_json(
                {
                    "common": {
                        "convertCurrencyServicePath": "/api/convert",
                        "nested": {"url": "https://example.test"},
                    }
                }
            )
        )
        self.assertEqual(
            rows["common.convertCurrencyServicePath"],
            "/api/convert",
        )
        self.assertEqual(
            rows["common.nested.url"],
            "https://example.test",
        )

    def test_extract_kuveyt_api_tokens(self):
        text = (
            'exchangeRates:"ck0d84?AAA",'
            'financePortal:"ck0d84?BBB",'
            'parities:"ck0d84?CCC"'
        )
        self.assertEqual(
            extract_kuveyt_api_tokens(text),
            {
                "exchangeRates": "ck0d84?AAA",
                "financePortal": "ck0d84?BBB",
                "parities": "ck0d84?CCC",
            },
        )

    def test_endpoint_extractor_finds_fetch_and_url_property_calls(self):
        text = """
        fetch("/services/GetRates");
        const cfg = { url: "/data/MarketSummary" };
        xhr.open("GET", "/ajax/CurrencyList");
        """

        candidates = extract_endpoint_candidates(
            text,
            "https://bank.example.test/app/",
        )

        self.assertIn(
            "https://bank.example.test/services/GetRates",
            candidates,
        )
        self.assertIn(
            "https://bank.example.test/data/MarketSummary",
            candidates,
        )
        self.assertIn(
            "https://bank.example.test/ajax/CurrencyList",
            candidates,
        )

    def test_context_extractor_surfaces_rate_semantics(self):
        snippets = extract_context_snippets(
            'const payload={currency:"USD",alis:48.1,satis:49.2};'
        )
        joined = "\n".join(snippets)
        self.assertIn("currency", joined)
        self.assertIn("alis", joined)

    def test_endpoint_extractor_finds_absolute_and_relative_candidates(self):
        text = """
        const a = "https://api.example.test/currency/rates";
        const b = "/api/exchange/latest";
        const c = "/images/logo.svg";
        const d = "plain-unrelated-string";
        """

        candidates = extract_endpoint_candidates(
            text,
            "https://bank.example.test/app/index.html",
        )

        self.assertIn(
            "https://api.example.test/currency/rates",
            candidates,
        )
        self.assertIn(
            "https://bank.example.test/api/exchange/latest",
            candidates,
        )
        self.assertNotIn(
            "https://bank.example.test/images/logo.svg",
            candidates,
        )


if __name__ == "__main__":
    unittest.main()
