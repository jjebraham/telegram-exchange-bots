import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

import publish_channels  # noqa: E402


class DefaultUsdtPublisherTests(unittest.TestCase):
    def test_default_usdt_builder_uses_hybrid_board(self):
        with patch.object(
            publish_channels,
            "fetch_and_build_hybrid_usdt_post",
            return_value="HYBRID-SEVEN",
        ) as hybrid:
            result = publish_channels.build_default_alanchande_usdt_post()

        self.assertEqual(result, "HYBRID-SEVEN")
        hybrid.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
