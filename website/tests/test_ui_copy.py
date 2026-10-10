from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UiCopyTests(unittest.TestCase):
    def test_site_name_and_cache_buster_are_current(self):
        html = (ROOT / "dist" / "index.html").read_text(encoding="utf-8")
        self.assertIn("الان چنده؟", html)
        self.assertNotIn("الان چند؟", html)
        self.assertIn('app.js?v=9', html)
        self.assertIn('styles.css?v=8', html)
        self.assertIn('theme.js?v=1', html)
        self.assertIn('https://wordpress.org/plugins/tomanify/', html)
        self.assertIn('زمان ثبت نسخه در گیت‌هاب', html)
        self.assertIn('به روز شده', html)
        self.assertIn('به روز نشده', html)
        self.assertNotIn('قدیمی', html)
        self.assertNotIn('منقضی', html)

        app = (ROOT / "dist" / "app.js").read_text(encoding="utf-8")
        self.assertIn('from "./model.js?v=8";', app)
        self.assertIn('status === "fresh" ? "به روز شده" : "به روز نشده"', app)

        ids = set(re.findall(r'\bid="([^"]+)"', html))
        references = set(re.findall(r'byId\("([^"]+)"\)', app))
        self.assertFalse(references - ids, f"missing app mount points: {references - ids}")

        for asset in ("app.js", "model.js", "styles.css", "theme.js"):
            self.assertTrue((ROOT / "dist" / asset).is_file(), asset)

