import io
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

import publish_channels  # noqa: E402


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class TelegramSendTests(unittest.TestCase):
    def test_channel_posts_are_sent_silently(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakeResponse(b'{"ok": true, "result": {"message_id": 1}}')

        with patch.object(
            publish_channels,
            "urlopen",
            side_effect=fake_urlopen,
        ):
            result = publish_channels.telegram_send(
                "fake-token",
                "@example",
                "hello",
            )

        self.assertTrue(result["ok"])
        payload = parse_qs(
            captured["request"].data.decode("utf-8"),
            keep_blank_values=True,
        )
        self.assertEqual(payload["disable_notification"], ["true"])
        self.assertEqual(payload["disable_web_page_preview"], ["true"])
        self.assertEqual(payload["parse_mode"], ["HTML"])


if __name__ == "__main__":
    unittest.main()
