import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from iran_gold_external_verifier import (  # noqa: E402
    parse_dolarchand_iran_gold,
    parse_dolarchand_updated_at,
)


class IranGoldExternalVerifierTests(unittest.TestCase):
    def _html(self, updated: str = "Sep 21, 2026, 9:34 PM") -> str:
        return f"""
        <html><body>
          Last updated {updated}
          Gold Mesghal (Bazaar) -1.15% Buy 102,800,000 Sell 102,800,000
          Gold 18K -1.15% Buy 23,731,470 Sell 23,731,470
          Emami -2.09% Buy 234,000,000 Sell 234,000,000
          Azadi -2.13% Buy 230,000,000 Sell 230,000,000
          ½ Azadi -1.64% Buy 120,000,000 Sell 120,000,000
          ¼ Azadi -3.08% Buy 63,000,000 Sell 63,000,000
          Gerami -5.71% Buy 33,000,000 Sell 33,000,000
        </body></html>
        """

    def test_parses_all_seven_toman_values(self):
        values = parse_dolarchand_iran_gold(
            self._html(),
            now=datetime(2026, 9, 21, 23, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(
            values["سکه امامی"],
            Decimal("234000000"),
        )
        self.assertEqual(
            values["سکه بهار آزادی"],
            Decimal("230000000"),
        )
        self.assertEqual(values["نیم سکه"], Decimal("120000000"))
        self.assertEqual(values["ربع سکه"], Decimal("63000000"))
        self.assertEqual(values["سکه گرمی"], Decimal("33000000"))
        self.assertEqual(
            values["طلای ۱۸ عیار"],
            Decimal("23731470"),
        )
        self.assertEqual(values["مثقال طلا"], Decimal("102800000"))

    def test_midpoint_is_used_when_buy_sell_differ(self):
        html = self._html().replace(
            "Buy 234,000,000 Sell 234,000,000",
            "Buy 233,000,000 Sell 235,000,000",
        )
        values = parse_dolarchand_iran_gold(
            html,
            now=datetime(2026, 9, 21, 23, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            values["سکه امامی"],
            Decimal("234000000"),
        )

    def test_missing_required_row_fails_closed(self):
        html = self._html().replace(
            "Gerami -5.71% Buy 33,000,000 Sell 33,000,000",
            "",
        )
        with self.assertRaisesRegex(ValueError, "سکه گرمی"):
            parse_dolarchand_iran_gold(
                html,
                now=datetime(2026, 9, 21, 23, 0, tzinfo=timezone.utc),
            )

    def test_stale_page_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            parse_dolarchand_iran_gold(
                self._html("Sep 20, 2026, 9:34 PM"),
                now=datetime(2026, 9, 21, 23, 0, tzinfo=timezone.utc),
                max_age_minutes=240,
            )

    def test_parses_public_update_timestamp_as_utc(self):
        self.assertEqual(
            parse_dolarchand_updated_at(
                "Last updated Sep 21, 2026, 9:34 PM Gold Mesghal"
            ),
            datetime(2026, 9, 21, 21, 34, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
