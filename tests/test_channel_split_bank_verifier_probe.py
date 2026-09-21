import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from probe_bank_verifier_sources import (  # noqa: E402
    AssetParser,
    extract_endpoint_candidates,
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
