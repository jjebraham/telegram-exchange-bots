from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UiCopyTests(unittest.TestCase):
    def test_site_name_and_cache_buster_are_current(self):
        html = (ROOT / "dist" / "index.html").read_text(encoding="utf-8")
        self.assertIn("الان چنده؟", html)
        self.assertNotIn("الان چند؟", html)
        self.assertIn('app.js?v=8', html)
        self.assertIn('styles.css?v=6', html)
        self.assertIn('https://wordpress.org/plugins/tomanify/', html)
        self.assertIn('زمان ثبت نسخه در گیت‌هاب', html)

        app = (ROOT / "dist" / "app.js").read_text(encoding="utf-8")
        self.assertIn('from "./model.js?v=8";', app)

