import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from publish_channels import build_resilient_market_bundle  # noqa: E402


class ResilientMarketBundleTests(unittest.TestCase):
    def test_one_failed_market_does_not_drop_healthy_posts(self):
        def broken():
            raise RuntimeError("temporary source failure")

        posts, failures = build_resilient_market_bundle(
            [
                ("turkey-gold", lambda: "TURKEY"),
                ("iran-gold", broken),
                ("usdt", lambda: "USDT"),
            ]
        )

        self.assertEqual(
            posts,
            [
                ("turkey-gold", "TURKEY"),
                ("usdt", "USDT"),
            ],
        )
        self.assertIn("iran-gold", failures)
        self.assertIn("RuntimeError", failures["iran-gold"])

    def test_all_failures_are_reported_without_fake_posts(self):
        def broken_a():
            raise TimeoutError("gold timeout")

        def broken_b():
            raise ValueError("bad payload")

        posts, failures = build_resilient_market_bundle(
            [
                ("turkey-gold", broken_a),
                ("usdt", broken_b),
            ]
        )

        self.assertEqual(posts, [])
        self.assertEqual(set(failures), {"turkey-gold", "usdt"})


if __name__ == "__main__":
    unittest.main()
