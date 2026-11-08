"""Offline checks for the automatic-news Wikimedia illustration pool."""
from io import BytesIO
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote, parse_qs, urlsplit

from PIL import Image

path = Path(__file__).with_name('instagram_reel_commons.py')
spec = importlib.util.spec_from_file_location('news_commons_test', path)
commons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commons)


def image_bytes(color):
    buf = BytesIO()
    Image.new('RGB', (800, 450), color).save(buf, format='JPEG', quality=85)
    return buf.getvalue()


def page(title, raw, *, license_name='CC BY 4.0', description='Bitcoin cryptocurrency'):
    return {
        'title': title, 'categories': [{'title': 'Category:Bitcoin'}],
        'imageinfo': [{
            'sha1': hashlib.sha1(raw).hexdigest(), 'size': len(raw), 'mime': 'image/jpeg',
            'url': 'https://upload.wikimedia.org/' + quote(title),
            'descriptionurl': 'https://commons.wikimedia.org/wiki/' + quote(title.replace(' ', '_')),
            'extmetadata': {
                'LicenseShortName': {'value': license_name},
                'LicenseUrl': {'value': 'https://creativecommons.org/licenses/by/4.0/'},
                'Artist': {'value': 'Artist'},
                'ImageDescription': {'value': description},
            },
        }],
    }


class CommonsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='news-commons-')
        self.root = Path(self.temp.name)
        self.p1 = page('File:Bitcoin Illustration One.jpg', image_bytes('red'))
        self.p2 = page('File:Bitcoin Illustration Two.jpg', image_bytes('blue'))
        self.images = {p['imageinfo'][0]['url']: image_bytes(color)
                       for p, color in ((self.p1, 'red'), (self.p2, 'blue'))}
        self.curated = {'bitcoin cryptocurrency': {
            self.p1['title']: self.p1['imageinfo'][0]['sha1'],
        }}
        self.curated_pages = [self.p1]
        self.search_pages = [self.p1, self.p2]
        self.downloads = []

    def tearDown(self):
        self.temp.cleanup()

    def read(self, url, limit, timeout):
        if url.startswith(commons.API):
            params = parse_qs(urlsplit(url).query)
            pages = self.curated_pages if 'titles' in params else self.search_pages
            return json.dumps({'query': {'pages': {str(i): p for i, p in enumerate(pages)}}}).encode()
        self.downloads.append(url)
        return self.images[url]

    def collect(self, title='Bitcoin market update'):
        with patch.object(commons, 'CURATED', self.curated), patch.object(commons, '_read', side_effect=self.read):
            return commons.collect({'title_original': title}, self.root, limit=3, seconds=15)

    def test_curated_and_search_images_are_distinct_and_credited(self):
        result = self.collect()
        self.assertEqual({item['title'] for item in result}, {self.p1['title'], self.p2['title']})
        self.assertEqual(len(self.downloads), 2)
        self.assertTrue(all(item['kind'] == 'illustrative' and item['author'] == 'Artist'
                            and item['license'] == 'CC BY 4.0' for item in result))

    def test_changed_curated_file_is_not_used_even_from_search(self):
        self.curated['bitcoin cryptocurrency'][self.p1['title']] = '0' * 40
        self.search_pages = [self.p1]
        self.assertEqual(self.collect(), [])
        self.assertEqual(self.downloads, [])

    def test_unsupported_license_is_rejected(self):
        self.p1['imageinfo'][0]['extmetadata']['LicenseShortName']['value'] = 'CC BY-SA 4.0'
        self.search_pages = []
        self.assertEqual(self.collect(), [])
        self.assertEqual(self.downloads, [])

    def test_tampered_download_is_rejected(self):
        self.images[self.p1['imageinfo'][0]['url']] = image_bytes('green')
        self.search_pages = []
        self.assertEqual(self.collect(), [])

    def test_curated_image_survives_optional_search_failure(self):
        real_read = self.read
        def read(url, limit, timeout):
            if url.startswith(commons.API) and 'generator=search' in url:
                raise OSError('offline')
            return real_read(url, limit, timeout)
        with patch.object(commons, 'CURATED', self.curated), patch.object(commons, '_read', side_effect=read):
            result = commons.collect({'title_original': 'Bitcoin market update'}, self.root,
                                     limit=3, seconds=15)
        self.assertEqual([item['title'] for item in result], [self.p1['title']])

    def test_ai_story_does_not_use_bitcoin_image(self):
        self.curated = {}
        self.assertEqual(self.collect('ChatGPT and Claude restrictions'), [])
        self.assertEqual(self.downloads, [])

    def test_topic_matching_and_precedence(self):
        cases = {
            'ChatGPT AI news about bitcoin': 'artificial intelligence',
            'Crypto exchange hacked by attackers': 'cybersecurity',
            'Bitcoin market update': 'bitcoin cryptocurrency',
            'US midterm election': 'election ballot voting',
            'Central bank changes interest rates': 'central banking',
            'Foreign exchange rate moves': 'currency exchange',
            'Stock exchange falls': 'stock market',
        }
        for title, query in cases.items():
            with self.subTest(title=title):
                self.assertEqual(commons._topic({'title_original': title})[0], query)

    def test_absent_or_irrelevant_topic_has_no_images(self):
        self.assertEqual(self.collect('A new local restaurant opens'), [])
        self.assertEqual(self.downloads, [])


if __name__ == '__main__':
    unittest.main()
