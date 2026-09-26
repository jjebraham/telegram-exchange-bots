import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from x_daily_rates import (
    build_alert_text,
    build_post_text,
    calculate_significant_changes,
    load_rate_state,
    save_rate_state,
)


class DailyXRatesTests(unittest.TestCase):
    def setUp(self):
        self.rates = {
            "buy_lira": Decimal("4910"),
            "sell_lira": Decimal("4690"),
            "buy_usdt": Decimal("236370"),
            "sell_usdt": Decimal("231690"),
            "lira_to_usdt": Decimal("49.63"),
            "usdt_to_lira": Decimal("47.69"),
        }

    def test_post_matches_customer_rate_direction_and_format(self):
        text = build_post_text(self.rates)
        self.assertIn("🇹🇷 فروش لیر به شما: 4,910", text)
        self.assertIn("🇹🇷 خرید لیر از شما: 4,690", text)
        self.assertIn("🪙 فروش تتر به شما: 236,370", text)
        self.assertIn("🪙 خرید تتر از شما: 231,690", text)
        self.assertIn("💲 لیر به تتر: 49.63", text)
        self.assertIn("💲 تتر به لیر: 47.69", text)

    def test_legacy_link_arguments_are_now_link_free(self):
        text = build_post_text(self.rates, include_link=True, include_whatsapp=True)
        self.assertIn("حواله روی خط واتسپ", text)
        self.assertNotIn("https://", text)
        self.assertNotIn("+905411603664", text)

    def test_link_free_post_contains_no_urls(self):
        text = build_post_text(
            self.rates,
            include_link=False,
            include_whatsapp=False,
            variant="morning",
        )
        self.assertIn("☀️ نرخ صبح صرافی کیانی", text)
        self.assertNotIn("https://", text)
        self.assertNotIn("wa.me", text)
        self.assertNotIn("miniapp.kiani.exchange", text)

    def test_variants_make_scheduled_posts_distinct(self):
        morning = build_post_text(self.rates, False, False, "morning")
        afternoon = build_post_text(self.rates, False, False, "afternoon")
        evening = build_post_text(self.rates, False, False, "evening")
        self.assertNotEqual(morning, afternoon)
        self.assertNotEqual(afternoon, evening)
        self.assertIn("📊 بروزرسانی نرخ صرافی کیانی", afternoon)
        self.assertIn("🌙 نرخ عصر صرافی کیانی", evening)

    def test_significant_change_threshold(self):
        current = dict(self.rates)
        current["buy_usdt"] = Decimal("238000")
        current["sell_usdt"] = Decimal("232000")
        changes = calculate_significant_changes(
            self.rates,
            current,
            Decimal("0.5"),
        )
        changed_keys = [item[0] for item in changes]
        self.assertIn("buy_usdt", changed_keys)
        self.assertNotIn("sell_usdt", changed_keys)

    def test_alert_text_is_link_free_and_contains_change(self):
        changes = [
            (
                "buy_usdt",
                Decimal("236370"),
                Decimal("238000"),
                Decimal("0.6896"),
            )
        ]
        now = datetime(2026, 9, 14, 16, 37, tzinfo=ZoneInfo("Europe/Istanbul"))
        text = build_alert_text(changes, now=now)
        self.assertIn("🚨 تغییر قابل توجه نرخ", text)
        self.assertIn("🪙 فروش تتر: 236,370 → 238,000 (+0.69٪)", text)
        self.assertIn("🕒 بروزرسانی: 16:37", text)
        self.assertNotIn("https://", text)

    def test_rate_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = str(Path(tmpdir) / "state.json")
            self.assertIsNone(load_rate_state(state_file))
            save_rate_state(state_file, self.rates)
            loaded = load_rate_state(state_file)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["buy_lira"], Decimal("4910"))
            self.assertEqual(loaded["buy_usdt"], Decimal("236370"))


if __name__ == "__main__":
    unittest.main()
