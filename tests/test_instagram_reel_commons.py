import hashlib
import ast
import io
import json
import tempfile
import unittest
from pathlib import Path
from html.parser import HTMLParser
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
from PIL import Image
import instagram_reel_commons as commons

class CommonsChecks(unittest.TestCase):
    def test_article_images_are_bounded_and_come_from_figures(self):
        source = (Path(__file__).resolve().parents[1]/'crypto_news_trial.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        node = next(n for n in tree.body if getattr(n, 'name', '') == 'ReelArticleFigures')
        scope = {'HTMLParser': HTMLParser}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'figures', 'exec'), scope)
        parser = scope['ReelArticleFigures']()
        parser.feed('<img src="/outside.jpg"><article>' +
                    ''.join(f'<figure><img data-lazy-src="/photo{i}.jpg"></figure>' for i in range(20)) +
                    '</article>')
        self.assertEqual(len(parser.urls), 16)
        self.assertEqual(parser.urls[0], '/photo0.jpg')

    def setUp(self):
        buf = io.BytesIO()
        Image.effect_noise((600, 400), 100).convert('RGB').save(buf, 'JPEG', quality=80)
        self.raw = buf.getvalue()
        self.meta = {'LicenseShortName':{'value':'CC BY 4.0'},
                     'LicenseUrl':{'value':'https://creativecommons.org/licenses/by/4.0/'},
                     'Artist':{'value':'Example Photographer'},
                     'ImageDescription':{'value':'A photograph of a Bitcoin coin.'}}
        self.page = {'title':'File:Bitcoin example.jpg', 'index':1,
                     'categories':[{'title':'Category:Bitcoin'}],
                     'imageinfo':[{'mime':'image/jpeg', 'size':len(self.raw),
                        'sha1':hashlib.sha1(self.raw).hexdigest(),
                        'url':'https://upload.wikimedia.org/example.jpg',
                        'descriptionurl':'https://commons.wikimedia.org/wiki/File:Bitcoin_example.jpg',
                        'extmetadata':self.meta}]}
    def read(self, payload):
        def fake(url, limit, timeout):
            return json.dumps(payload).encode() if 'w/api.php?' in url else self.raw
        return fake

    def test_verified_image_and_search_continuation(self):
        payload = {'continue':{'gsroffset':15}, 'query':{'pages':{'1':self.page}}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(commons, '_read', self.read(payload)):
            items = commons.collect({'title_original':'Bitcoin market update'}, Path(tmp), limit=1)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['kind'], 'illustrative')
            self.assertEqual(items[0]['author'], 'Example Photographer')
            self.assertTrue(items[0]['path'].is_file())

    def test_unlicensed_wrong_host_and_incomplete_categories_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.meta['LicenseShortName']['value'] = 'unknown'
            payload = {'query':{'pages':{'1':self.page}}}
            with patch.object(commons, '_read', self.read(payload)):
                self.assertEqual(commons.collect({'title_original':'Bitcoin update'}, Path(tmp)), [])
            self.meta['LicenseShortName']['value'] = 'CC BY 4.0'
            self.page['imageinfo'][0]['url'] = 'https://attacker.example/file.jpg'
            with patch.object(commons, '_read', self.read(payload)):
                self.assertEqual(commons.collect({'title_original':'Bitcoin update'}, Path(tmp)), [])
            payload['continue'] = {'clcontinue':'x'}
            with patch.object(commons, '_read', self.read(payload)):
                self.assertEqual(commons.collect({'title_original':'Bitcoin update'}, Path(tmp)), [])

    def test_unknown_topic_makes_no_request(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(commons, '_read') as read:
            self.assertEqual(commons.collect({'title_original':'Unrelated topic'}, Path(tmp)), [])
            read.assert_not_called()

if __name__ == '__main__':
    unittest.main()



