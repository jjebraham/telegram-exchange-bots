import ast
import importlib.util
import sys
import tempfile
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if 'fcntl' not in sys.modules:
    try:
        import fcntl
    except ImportError:
        sys.modules['fcntl'] = types.ModuleType('fcntl')

import instagram_reel_source_image as source
spec = importlib.util.spec_from_file_location('test_auto_reels', ROOT/'instagram_trial_reels.py')
reel = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reel
spec.loader.exec_module(reel)

class Checks(unittest.TestCase):
    def test_publisher_specific_cdn_mapping(self):
        sources = {'www.cnbc.com':'CNBC', 'www.tradingview.com':'Reuters via TradingView',
                   'abcnews.com':'ABC News US'}
        engine = types.SimpleNamespace(checked_url=lambda url, **kw:url,
                 publisher=lambda url:sources.get(urlsplit(url).hostname))
        for article, image in (
            ('https://www.cnbc.com/a', 'https://image.cnbcfm.com/a.jpg'),
            ('https://www.tradingview.com/news/reuters.com,a', 'https://s.tradingview.com/a.jpg'),
            ('https://abcnews.com/a', 'https://i.abcnewsfe.com/a.jpg'),
        ):
            self.assertEqual(source._checked(engine, article, image), image)
        with self.assertRaises(ValueError):
            source._checked(engine, 'https://www.cnbc.com/a', 'https://s.tradingview.com/a.jpg')

    def test_image_filter_tries_another_source_in_same_group(self):
        tree = ast.parse((ROOT/'instagram_ranked_news.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'material_for')
        class NewsError(Exception): pass
        class SourceUnavailable(Exception): pass
        Item = lambda link, name: types.SimpleNamespace(link=link, source=name, published=1, title='title')
        group = types.SimpleNamespace(lead=types.SimpleNamespace(id='a'), items=[
            Item('https://first.example/a','first'), Item('https://second.example/b','second')])
        scope = {'urlsplit':urlsplit, 'approved_item':lambda i:True, 'outlet_key':lambda s:s,
                 'source_weight':lambda s:1, 'canonical_url':lambda s:s, 'resolve_google':lambda s:s,
                 'NewsError':NewsError, 'SourceUnavailable':SourceUnavailable,
                 'coverage':lambda g:set(), 'engine':types.SimpleNamespace(
                    source_material=lambda row,now:dict(row))}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'material', 'exec'), scope)
        def image_filter(row):
            if 'first.example' in row['source_url']:
                raise NewsError('Image unavailable')
        result = scope['material_for'](group, {}, 'economy', set(), 0, material_filter=image_filter)
        self.assertEqual(result['source_url'], 'https://second.example/b')

    def test_automatic_checks_before_ranking_and_reuses_validated_image(self):
        class NewsError(Exception): pass
        class Con:
            def execute(self, query, *args):
                class Result:
                    def __iter__(self): return iter([])
                return Result()
        class Ranked(types.ModuleType):
            SOURCES = {'crypto':'crypto.db', 'economy':'economy.db'}
            def configure_engine(self, kind): pass
            def rank_events(self, con, kind, now, **kwargs):
                self.test.assertTrue(kwargs['trial_relaxed'])
                row = {'source_url':'https://'+kind+'.example/news',
                       'image_url':'https://'+kind+'.example/image.jpg',
                       'title_original':'title', 'source_name':'source',
                       'trial_score':2 if kind == 'crypto' else 1,
                       'article_published_at':now, 'assessment':{'story_type':'hard_news'}}
                kwargs['material_filter'](row)
                return [row], {}
            def select_main_stories(self, con, rows, kind, limit, now, audit, checkpoint): return rows
            def translate(self, con, row): return ('title', 'summary')
            def locks(self, kind): return nullcontext()
        ranked = Ranked('instagram_ranked_news')
        ranked.test = self
        engine = types.ModuleType('crypto_news_trial')
        engine.init_trial = lambda con:None
        news = types.ModuleType('instagram_crypto_news')
        news.NewsError = NewsError
        news.database = lambda path:nullcontext(Con())
        translation = types.ModuleType('economy_news_translation')
        translation.load_translation_env = lambda path:None
        intake = types.ModuleType('instagram_manual_news_intake')
        intake.load_publish_env = lambda:None
        image_mod = types.ModuleType('instagram_reel_source_image')
        def fetch(engine, article, image, dest, timeout):
            Path(dest).write_bytes(b'checked-image')
        image_mod.fetch = fetch
        modules = {'instagram_ranked_news':ranked, 'crypto_news_trial':engine,
                   'instagram_crypto_news':news, 'economy_news_translation':translation,
                   'instagram_manual_news_intake':intake, 'instagram_reel_source_image':image_mod}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, modules), \
             patch.object(reel, 'STATE', Path(tmp)), patch.object(reel, '_slot_due', return_value=True), \
             patch.object(reel, '_connect', side_effect=lambda:nullcontext(Con())), \
             patch.object(reel, 'publisher_lock', side_effect=lambda:nullcontext()), \
             patch.object(reel, '_reserve_auto_slot', return_value=True), \
             patch.object(reel, '_source_key', side_effect=lambda x:x), \
             patch.object(reel, '_live_guard') as guard:
            paths = []
            def create(story, kind, **kwargs):
                path = Path(kwargs['_validated_image'])
                self.assertEqual(path.read_bytes(), b'checked-image')
                paths.append(path)
                return 'reel-id'
            with patch.object(reel, 'create_reel', side_effect=create):
                result = reel._run_scheduled(Path(tmp), Path(tmp), '11:00', 'trial')
            self.assertEqual(result, 'reel-id')
            self.assertEqual(guard.call_count, 1)
            self.assertFalse(paths[0].exists())

if __name__ == '__main__':
    unittest.main()
