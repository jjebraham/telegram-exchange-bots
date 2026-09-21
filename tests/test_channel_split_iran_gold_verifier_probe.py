import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from probe_iran_gold_verifier_sources import (  # noqa: E402
    _context,
    _normalize_digits,
    _numbers,
)


class IranGoldVerifierProbeTests(unittest.TestCase):
    def test_normalizes_persian_and_arabic_digits(self):
        self.assertEqual(
            _normalize_digits("۱۲۳٤٥"),
            "12345",
        )

    def test_context_finds_label_case_insensitively(self):
        text = "prefix Emami Coin 232,000,000 suffix"
        snippet = _context(text, "emami", radius=40)
        self.assertIsNotNone(snippet)
        self.assertIn("232,000,000", snippet)

    def test_numbers_extract_grouped_prices(self):
        values = _numbers(
            "Emami 232,000,000 Toman 18K 23,459,070"
        )
        self.assertIn("232,000,000", values)
        self.assertIn("23,459,070", values)


if __name__ == "__main__":
    unittest.main()
