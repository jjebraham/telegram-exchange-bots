import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from price_proxy import _proxy_url, _redacted_proxy, _safe_error, _split_items  # noqa: E402


class PriceProxyTests(unittest.TestCase):
    def test_split_items_matches_kiani_backend_format(self):
        self.assertEqual(
            _split_items("proxy1:8000, proxy2:8000;proxy3:8000"),
            ["proxy1:8000", "proxy2:8000", "proxy3:8000"],
        )

    def test_proxy_url_keeps_credentials_separate_and_encoded(self):
        url = _proxy_url("proxy.example.net:8080", "user@example", "p@ss word")
        self.assertEqual(
            url,
            "http://user%40example:p%40ss%20word@proxy.example.net:8080",
        )

    def test_proxy_url_strips_embedded_credentials(self):
        url = _proxy_url(
            "http://old:secret@proxy.example.net:8080",
            "new-user",
            "new-secret",
        )
        self.assertEqual(
            url,
            "http://new-user:new-secret@proxy.example.net:8080",
        )

    def test_redaction_never_exposes_credentials(self):
        url = "http://user:secret@proxy.example.net:8080"
        self.assertEqual(_redacted_proxy(url), "http://proxy.example.net:8080")
        safe = _safe_error(RuntimeError(f"failed via {url}"), url)
        self.assertNotIn("user", safe)
        self.assertNotIn("secret", safe)


if __name__ == "__main__":
    unittest.main()
