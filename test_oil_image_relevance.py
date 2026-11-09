"""Oil illustrations must show the industry, and exclude the rejected lab image."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image
import instagram_reel_commons as commons
import instagram_reel_stock as stock

STORY = {'title_original': 'As high oil prices curb demand, fresh signs of glut appear'}


def jpeg(color):
    stream = io.BytesIO()
    Image.new('RGB', (900, 500), color).save(stream, format='JPEG')
    return stream.getvalue()


class OilImages(unittest.TestCase):
    def test_barrels_are_the_first_search(self):
        self.assertEqual(stock.queries(STORY)[0], 'oil barrels')
        self.assertEqual(commons._topic(STORY), ('oil barrels', 'oil'))
        for title in ('WTI prices rise', 'Petroleum demand falls', 'Brent prices fall'):
            self.assertEqual(stock.queries({'title_original': title})[0], 'oil barrels')
            self.assertEqual(commons._topic({'title_original': title})[0], 'oil barrels')

    def test_exact_rejection_survives_encoding_renaming_and_thumb_urls(self):
        items = [
            {'title': 'File:Petroleum sample.jpg'},
            {'source_url': 'https://commons.wikimedia.org/wiki/File:Petroleum_sample.jpg'},
            {'source_url': 'https://commons.wikimedia.org/wiki/File%3APetroleum%20sample.jpg'},
            {'url': 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/Petroleum_sample.jpg/900px-Petroleum_sample.jpg'},
            {'title': 'File:Renamed oil barrels.jpg', 'sha1': next(iter(commons.REJECTED_IMAGE_SHA1))},
        ]
        for item in items:
            with self.subTest(item=item):
                self.assertTrue(commons.rejected_image(item))
                self.assertFalse(commons.oil_scene(dict(description='crude oil barrels', **item)))

    def test_recognizable_oil_scenes(self):
        for description in ('oil barrels, petroleum industry', 'Crude oil tanker at sea',
                            'Petroleum refinery', 'Oil pumpjack', 'Oil storage tanks',
                            'Offshore oil drilling rig', 'oil, barrel, industry', 'Crude oil pipeline'):
            with self.subTest(description=description):
                item = {'description': description}
                self.assertTrue(commons.oil_scene(item))
                self.assertTrue(stock._matches_story_topic(STORY, item))

    def test_generic_oil_lab_food_and_unrelated_scenes_rejected(self):
        for description in ('oil, liquid, brown', 'petroleum sample in laboratory glassware',
                            'Crude oil in a beaker beside oil barrels', 'oil bottle', 'essential oil bottle',
                            'olive oil barrels', 'oil, test tube', 'oil in a flask',
                            'military tank', 'beer barrels', 'oil demand chart', ''):
            with self.subTest(description=description):
                item = {'description': description}
                self.assertFalse(commons.oil_scene(item))
                self.assertFalse(stock._matches_story_topic(STORY, item))

    def test_other_topics_keep_their_own_relevance(self):
        story = {'title_original': 'Bitcoin adoption grows'}
        self.assertEqual(stock.queries(story)[0], 'bitcoin cryptocurrency')
        self.assertTrue(stock._matches_story_topic(story, {'description': 'bitcoin cryptocurrency'}))
        self.assertFalse(stock._matches_story_topic(story, {'description': 'oil barrels'}))

    def test_commons_rejected_before_download_and_license_guard_preserved(self):
        raw = jpeg('blue')
        pages = {}
        for index, (title, description, license_name) in enumerate([
            ('File:Petroleum sample.jpg', 'crude oil barrels', 'CC BY 4.0'),
            ('File:Laboratory.jpg', 'crude oil sample in a beaker', 'CC BY 4.0'),
            ('File:Oil chart.png', 'crude oil demand chart', 'CC BY 4.0'),
            ('File:Oil barrels.jpg', 'crude oil barrels at a refinery', 'CC BY 4.0'),
            ('File:Oil tanker.jpg', 'petroleum tanker at sea', 'CC BY 4.0'),
            ('File:Oil refinery.jpg', 'petroleum refinery', 'All rights reserved'),
        ]):
            pages[str(index)] = dict(index=index, title=title,
                categories=[{'title': 'Category:Petroleum industry'}], imageinfo=[dict(
                url=f'https://upload.wikimedia.org/test/{index}.jpg',
                descriptionurl='https://commons.wikimedia.org/wiki/' + title.replace(' ', '_'),
                mime='image/jpeg', size=len(raw), sha1=hashlib.sha1(raw).hexdigest(),
                extmetadata={key: {'value': value} for key, value in {
                    'LicenseShortName': license_name, 'LicenseUrl': commons.LICENSES['CC BY 4.0'],
                    'Artist': 'Test photographer', 'ImageDescription': description}.items()})])
        downloaded = []
        def read(url, limit, timeout):
            if url.startswith(commons.API):
                self.assertEqual(parse_qs(urlsplit(url).query)['gsrsearch'], ['oil barrels'])
                return json.dumps({'query': {'pages': pages}}).encode()
            downloaded.append(url)
            return raw
        with tempfile.TemporaryDirectory() as temp, patch.object(commons, '_read', side_effect=read):
            images = commons.collect(STORY, Path(temp), limit=4)
        self.assertEqual({x['title'] for x in images}, {'File:Oil barrels.jpg', 'File:Oil tanker.jpg'})
        self.assertEqual(set(downloaded), {'https://upload.wikimedia.org/test/3.jpg', 'https://upload.wikimedia.org/test/4.jpg'})
        self.assertTrue(all(x['license'] == 'CC BY 4.0' for x in images))

    def test_pixabay_cached_results_also_filtered_without_new_api_calls(self):
        raw = jpeg('green')
        data = {'hits': [dict(id=i, largeImageURL=f'https://pixabay.com/get/{i}.jpg',
                             pageURL=f'https://pixabay.com/photos/{i}/', user='Test photographer', tags=tags)
                         for i, tags in [(1, 'petroleum sample, laboratory'), (2, 'oil barrels'),
                                         (3, 'petroleum refinery')]]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with stock._database(root) as con:
                for query in stock.queries(STORY)[:2]:
                    con.execute('INSERT INTO search_cache VALUES(?,?,?,?)',
                                ('pixabay', hashlib.sha256(query.encode()).hexdigest(), time.time(), json.dumps(data)))
                con.commit()
            def read(url, **kwargs):
                self.assertNotIn('/api/', url, 'A valid 24h cache must not be refetched')
                self.assertNotIn('/1.jpg', url, 'Rejected laboratory image must not be downloaded')
                return raw
            with patch.object(stock, '_key', return_value='test-key-only'), patch.object(stock, '_read', side_effect=read) as request:
                images = stock.collect(STORY, root, origin='admin_link', state=root,
                                       provider_filter={'pixabay'}, limit=4)
            self.assertEqual({x['id'] for x in images}, {'2', '3'})
            self.assertEqual(request.call_count, 2)

    def test_scheduled_pixabay_policy_preserved(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(stock, '_key', return_value='test-key-only'), patch.object(stock, '_api') as api:
            images = stock.collect(STORY, Path(temp), origin='daily_news', state=Path(temp), provider_filter={'pixabay'})
            self.assertEqual(images, [])
            api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
