"""Confirm Google News outlet aliases do not weaken publisher verification."""
import ast
from pathlib import Path
import sys
import types
import unittest
from urllib.parse import urlsplit

root = Path(__file__).resolve().parents[1]
selector = root / 'instagram-button-menu/selector_trial_runtime'
if not selector.is_dir():
    selector = Path(__file__).resolve().parents[2] / 'selector_trial_runtime'
sys.path.insert(0, str(selector))
from economy_news_picker import source_key

path = Path(__file__).with_name('automatic_ranked_news_images.py')
tree = ast.parse(path.read_text(encoding='utf-8'))
names = {'outlet_key', 'reviewed_publisher', 'approved_item'}
nodes = [node for node in tree.body
         if isinstance(node, ast.FunctionDef) and node.name in names]
aliases = next(node for node in tree.body if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == 'OUTLET_ALIASES'
                       for target in node.targets))
publishers = {'apnews.com': 'AP', 'reuters.com': 'Reuters', 'bbc.com': 'BBC'}
def base_publisher(url):
    host = (urlsplit(url).hostname or '').lower()
    return next((name for domain, name in publishers.items()
                 if host == domain or host.endswith('.' + domain)), None)
engine = types.SimpleNamespace(PUBLISHERS=publishers)
scope = {'source_key': source_key, 'urlsplit': urlsplit,
         'engine': engine, 'BASE_PUBLISHER': base_publisher}
exec(compile(ast.Module(body=[aliases] + nodes, type_ignores=[]), str(path), 'exec'), scope)
engine.publisher = scope['reviewed_publisher']


class AliasTests(unittest.TestCase):
    def test_google_ap_outlet_variants_are_eligible_for_source_check(self):
        for name in ('Associated Press', 'AP News', 'AP'):
            with self.subTest(name=name):
                item = types.SimpleNamespace(link='https://news.google.com/rss/articles/example', source=name)
                self.assertTrue(scope['approved_item'](item))

    def test_unrecognized_google_publisher_is_not_eligible(self):
        item = types.SimpleNamespace(link='https://news.google.com/rss/articles/example', source='Unreviewed Outlet')
        self.assertFalse(scope['approved_item'](item))

    def test_claimed_ap_label_does_not_approve_unrelated_destination(self):
        self.assertIsNone(scope['reviewed_publisher']('https://unreviewed.example/article'))
        self.assertEqual(scope['reviewed_publisher']('https://apnews.com/article/example'), 'AP')


if __name__ == '__main__':
    unittest.main()
