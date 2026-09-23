import io
import sys
import unittest
from datetime import datetime
from decimal import Decimal
from email.message import Message
from unittest.mock import patch
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from iran_fx_adonis import (  # noqa: E402
    fetch_adonis_try_sell_toman,
    parse_adonis_try_sell_toman,
    validate_adonis_page_freshness,
)


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


    def _dated_page(self, age="38 min ago", date="2026-09-23"):
        return (
            f"<html><body><h1>Daily Currency Rates</h1>"
            f"<p>{date}</p><div>Last update {age}</div>"
            f"<div>TRY-IRR Lira to Toman 4,727 4,465</div>"
            f"</body></html>"
        )

    def _now(self):
        return datetime(2026, 9, 23, 16, 54, tzinfo=ZoneInfo("Europe/Istanbul"))

    def test_current_page_age_is_accepted(self):
        validate_adonis_page_freshness(
            self._dated_page(), now=self._now()
        )

    def test_page_over_90_minutes_old_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_adonis_page_freshness(
                self._dated_page(age="91 min ago"), now=self._now()
            )

    def test_page_at_90_minute_boundary_is_accepted(self):
        validate_adonis_page_freshness(
            self._dated_page(age="90 min ago"), now=self._now()
        )

    def test_yesterday_page_fails_even_with_recent_relative_age(self):
        with self.assertRaisesRegex(ValueError, "date is not current"):
            validate_adonis_page_freshness(
                self._dated_page(date="2026-09-22"), now=self._now()
            )

    def test_missing_or_unknown_update_age_fails_closed(self):
        for age in ("", "earlier today"):
            with self.subTest(age=age):
                with self.assertRaisesRegex(ValueError, "unrecognized"):
                    validate_adonis_page_freshness(
                        self._dated_page(age=age), now=self._now()
                    )

    def test_missing_page_date_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "no dated"):
            validate_adonis_page_freshness(
                self._dated_page(date="unknown"), now=self._now()
            )

    def test_fetch_enforces_freshness_before_returning_price(self):
        class FakeResponse(io.BytesIO):
            def __init__(self, body):
                super().__init__(body.encode("utf-8"))
                self.headers = Message()

        today = datetime.now(ZoneInfo("Europe/Istanbul")).date().isoformat()
        stale_html = self._dated_page(age="3 hours ago", date=today)
        with patch(
            "iran_fx_adonis.urlopen",
            return_value=FakeResponse(stale_html),
        ):
            with self.assertRaisesRegex(ValueError, "stale"):
                fetch_adonis_try_sell_toman("https://example.test")


if __name__ == "__main__":
    unittest.main()
