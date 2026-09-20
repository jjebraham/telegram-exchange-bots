import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

import publish_channels  # noqa: E402


class DailyBundleCommandTests(unittest.TestCase):
    def test_daily_dry_run_builds_five_independent_posts(self):
        argv = [
            "publish_channels.py",
            "--post",
            "alanchande-daily",
            "--dry-run",
        ]

        with (
            patch.object(sys, "argv", argv),
            patch.object(publish_channels, "fetch_usd_comparison", return_value=["USD"]),
            patch.object(publish_channels, "fetch_eur_comparison", return_value=["EUR"]),
            patch.object(publish_channels, "fetch_turkish_gold_quotes", return_value=["TGOLD"]),
            patch.object(publish_channels, "fetch_iran_gold_market", return_value="IGOLD"),
            patch.object(publish_channels, "load_bank_fx_near_24h", return_value={}),
            patch.object(publish_channels, "load_turkey_gold_near_24h", return_value={}),
            patch.object(publish_channels, "load_iran_gold_near_24h", return_value={}),
            patch.object(publish_channels, "build_usd_comparison_post", return_value="BANK"),
            patch.object(publish_channels, "build_turkey_fx_pulse_post", return_value="PULSE"),
            patch.object(publish_channels, "build_turkish_gold_post", return_value="TURKEY-GOLD"),
            patch.object(publish_channels, "build_iran_gold_post", return_value="IRAN-GOLD"),
            patch.object(publish_channels, "build_default_alanchande_usdt_post", return_value="USDT"),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            result = publish_channels.main()

        self.assertEqual(result, 0)
        output = stdout.getvalue()
        self.assertIn("BANK", output)
        self.assertIn("PULSE", output)
        self.assertIn("TURKEY-GOLD", output)
        self.assertIn("IRAN-GOLD", output)
        self.assertIn("USDT", output)


if __name__ == "__main__":
    unittest.main()
