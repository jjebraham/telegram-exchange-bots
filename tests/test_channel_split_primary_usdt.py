import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from primary_usdt import build_primary_usdt_post  # noqa: E402


class PrimaryUsdtTests(unittest.TestCase):
    def test_direct_result_is_primary(self):
        fallback_fetcher = Mock(side_effect=AssertionError("fallback should not run"))
        fallback_builder = Mock(side_effect=AssertionError("fallback should not run"))

        result = build_primary_usdt_post(
            direct_builder=lambda: "DIRECT",
            fallback_fetcher=fallback_fetcher,
            fallback_builder=fallback_builder,
        )

        self.assertEqual(result, "DIRECT")

    def test_tgju_is_used_only_when_direct_quorum_fails(self):
        fallback_fetcher = Mock(return_value=["fixture"])
        fallback_builder = Mock(return_value="TGJU")

        def direct_failure():
            raise RuntimeError("Only 1 direct USDT source available")

        result = build_primary_usdt_post(
            direct_builder=direct_failure,
            fallback_fetcher=fallback_fetcher,
            fallback_builder=fallback_builder,
        )

        self.assertTrue(result.startswith("TGJU"))
        self.assertIn("منبع پشتیبان", result)
        fallback_fetcher.assert_called_once_with()
        fallback_builder.assert_called_once_with(["fixture"])


if __name__ == "__main__":
    unittest.main()
