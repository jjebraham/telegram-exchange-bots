import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from iran_fx_adonis import parse_adonis_try_sell_toman  # noqa: E402


class AdonisTryTests(unittest.TestCase):
    def test_parses_try_sell_toman(self):
        html = """
        <html><body>
          <div>TRY-IRR Lira to Toman 4,741 4,479</div>
        </body></html>
        """
        self.assertEqual(
            parse_adonis_try_sell_toman(html),
            Decimal("4741"),
        )

    def test_missing_try_row_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "no parseable TRY"):
            parse_adonis_try_sell_toman("<html><body>USD only</body></html>")


if __name__ == "__main__":
    unittest.main()
