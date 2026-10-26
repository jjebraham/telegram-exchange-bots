"""Customer-direction, price-preservation and guarded Kiani deployment tests."""
import ast
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_kiani_images import BUILDERS, patch_publisher
from kiani_images import kiani_html, parse_customer_board, parse_try_board, parse_converter
from kiani_posts import build_kiani_toman_receive_post
from visual_kiani_images import samples, SAMPLE_TIME, SAMPLE_RATES

ROOT = Path(__file__).resolve().parent


class KianiImageTests(unittest.TestCase):
    def test_board_keeps_customer_buy_sell_and_cross_directions(self):
        text = samples()['kiani-rates']
        data = parse_customer_board(text)
        self.assertEqual((data.try_buy, data.try_sell), ('5,520', '5,350'))
        self.assertEqual((data.usdt_buy, data.usdt_sell), ('274,060', '268,640'))
        self.assertEqual((data.lira_to_usdt, data.usdt_to_lira), ('50.66', '48.68'))
        html = kiani_html('kiani-rates', text, now=SAMPLE_TIME)
        for key, value in (('try-buy', '5,520'), ('try-sell', '5,350'), ('usdt-buy', '274,060'), ('usdt-sell', '268,640')):
            self.assertIn('data-field="' + key + '" data-value="' + value + '"', html)
        self.assertIn('از ما می‌خرید', html)
        self.assertIn('به ما می‌فروشید', html)
        self.assertIn('۱۴:۱۰', html)

    def test_try_card_keeps_latin_large_prices_and_exact_contact_numbers(self):
        data = parse_try_board(samples()['kiani-try'])
        self.assertEqual((data.buy, data.sell, data.clock), ('5,520', '5,350', '14:10:00'))
        html = kiani_html('kiani-try', samples()['kiani-try'], now=SAMPLE_TIME)
        self.assertIn('>5,520</span>', html)
        self.assertIn('>5,350</span>', html)
        self.assertIn('t.me/TL905411603664', html)
        self.assertIn('+90 539 290 56 86', html)
        self.assertIn('خرید لیر از ما', html)
        self.assertIn('فروش لیر به ما', html)

    def test_both_calculators_preserve_producer_rows_without_recalculating(self):
        for kind in ('kiani-examples', 'kiani-examples-reverse'):
            with self.subTest(kind=kind):
                data = parse_converter(kind, samples()[kind])
                html = kiani_html(kind, samples()[kind], now=SAMPLE_TIME)
                for index, (receive, pay) in enumerate(data.rows):
                    self.assertIn('data-field="pay-' + str(index) + '" data-value="' + pay + '"', html)
                    self.assertIn('data-field="receive-' + str(index) + '" data-value="' + receive + '"', html)
                self.assertIn('واریز می‌کنید', html)
                self.assertIn('دریافت می‌کنید', html)
        rounded = build_kiani_toman_receive_post({**SAMPLE_RATES, 'sell_lira': Decimal('4600')})
        data = parse_converter('kiani-examples-reverse', rounded)
        self.assertEqual(data.rows[-1], ('500,000,000', '108,700'))
        self.assertEqual(data.basis, '4,600')

    def test_malformed_missing_repeated_or_wrong_direction_source_fails(self):
        board = samples()['kiani-rates']
        for broken in (board.replace('5,520', '0'), board.replace('274,060', 'NaN'), board + '\n' + board):
            with self.subTest(broken=broken[:30]), self.assertRaises(ValueError):
                parse_customer_board(broken)
        with self.assertRaises(ValueError):
            parse_try_board(samples()['kiani-try'].replace('https://wa.me/', 'http://wa.me/'))
        with self.assertRaises(ValueError):
            parse_converter('kiani-examples', samples()['kiani-examples-reverse'])
        with self.assertRaises(ValueError):
            parse_converter('kiani-examples', samples()['kiani-examples'].replace('50,000', '51,000'))

    def test_assets_are_embedded_and_illustrative_mode_is_visible(self):
        for kind, text in samples().items():
            html = kiani_html(kind, text, now=SAMPLE_TIME, demo=True)
            self.assertIn('نمونه آزمایشی — قیمت‌ها واقعی نیستند', html)
            self.assertIn('data:image/svg+xml;base64,', html)
            self.assertNotIn('src="https://', html)
            self.assertNotIn('<script', html)
        with self.assertRaises(ValueError):
            kiani_html('kiani-rates', samples()['kiani-rates'], now=datetime(2026, 10, 26))

    def test_guarded_patch_is_idempotent_and_preserves_pricing_function_bytes(self):
        original = (ROOT / 'publish_channels.py').read_bytes()
        changed = patch_publisher(original)
        self.assertEqual(patch_publisher(changed), changed)
        before_tree, after_tree = ast.parse(original), ast.parse(changed)
        before = next(node for node in ast.walk(before_tree) if isinstance(node, ast.FunctionDef) and node.name == 'get_rates')
        after = next(node for node in ast.walk(after_tree) if isinstance(node, ast.FunctionDef) and node.name == 'get_rates')
        self.assertEqual(ast.get_source_segment(original.decode(), before), ast.get_source_segment(changed.decode(), after))
        keys = {}
        for node in ast.walk(after_tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'add_kiani' and node.args:
                child = node.args[0]
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in BUILDERS:
                    keys[child.func.id] = node.args[1].value
        self.assertEqual(keys, BUILDERS)
        with self.assertRaises(ValueError):
            patch_publisher(original.replace(b'add_kiani(build_kiani_rate_post(get_rates()), "kiani-rates")', b'add_kiani(build_kiani_rate_post(get_rates()), "wrong")'))

    def test_disposable_install_backs_up_and_does_not_activate_image_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'repo/channel_split'
            folder.mkdir(parents=True)
            for name in ('publish_channels.py', 'market_images.py', 'kiani_posts.py'):
                (folder / name).write_bytes((ROOT / name).read_bytes())
            alan = subprocess.run([sys.executable, str(ROOT / 'deploy_market_images.py'), '--repo', str(folder.parent),
                                   '--backup-dir', str(Path(temp) / 'alan-backup'), '--apply'],
                                  capture_output=True, text=True, timeout=20)
            self.assertEqual(alan.returncode, 0, alan.stderr)
            (folder / '.env').write_text('KIANI_POST_FORMAT=text\nOTHER=preserved\n')
            original = (folder / 'publish_channels.py').read_bytes()
            backup = Path(temp) / 'backup'
            command = [sys.executable, str(ROOT / 'deploy_kiani_images.py'), '--repo', str(folder.parent), '--backup-dir', str(backup)]
            dry = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertEqual((folder / 'publish_channels.py').read_bytes(), original)
            self.assertFalse(backup.exists())
            applied = subprocess.run(command + ['--apply'], capture_output=True, text=True, timeout=20)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            saved = list(backup.iterdir())
            self.assertEqual(len(saved), 1)
            self.assertEqual((saved[0] / 'publish_channels.py').read_bytes(), original)
            self.assertEqual((folder / '.env').read_text(), 'KIANI_POST_FORMAT=text\nOTHER=preserved\n')
            self.assertTrue((folder / 'kiani_image_assets/kiani-logo.svg').is_file())
            again = subprocess.run(command + ['--apply'], capture_output=True, text=True, timeout=20)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(len(list(backup.iterdir())), 1)


if __name__ == '__main__':
    unittest.main()
