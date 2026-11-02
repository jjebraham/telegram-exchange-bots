"""Offline checks for required, distinct news slide images."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

import instagram_news_slide_images as slides


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.story = dict(source_url='https://example.com/news', image_url='hero',
                          image_urls=['hero','duplicate','second'], title_original='Bitcoin',
                          title_fa='بیت کوین', summary_fa='متن فارسی')

    def tearDown(self):
        self.temp.cleanup()

    def modules(self, colors, stock=None, commons=None):
        source = types.ModuleType('instagram_reel_source_image')
        def fetch(engine, article, url, path, timeout=20):
            if url not in colors:
                raise ValueError('Unavailable')
            Image.new('RGB', (900,500), colors[url]).save(path)
            return path
        source.fetch = fetch
        st = types.ModuleType('instagram_reel_stock')
        st.collect = lambda *args, **kwargs: list(stock or [])
        co = types.ModuleType('instagram_reel_commons')
        co.collect = lambda *args, **kwargs: list(commons or [])
        return {'instagram_reel_source_image':source, 'instagram_reel_stock':st,
                'instagram_reel_commons':co}

    def test_distinct_article_images_and_duplicate_rejected(self):
        modules = self.modules({'hero':'red','duplicate':'red','second':'blue'})
        with patch.dict(sys.modules, modules):
            found = slides.collect(None, self.story, self.root, origin='manual')
        self.assertEqual(len(found), 2)
        self.assertNotEqual(slides.image_key(found[0]['path']), slides.image_key(found[1]['path']))

    def test_second_image_can_be_licensed_and_credited(self):
        stock_path = self.root/'stock.jpg'
        Image.new('RGB',(900,500),'blue').save(stock_path)
        item = dict(path=stock_path,kind='illustrative',provider='pixabay',id='1',
                    author='Artist',source_url='https://pixabay.com/example')
        with patch.dict(sys.modules, self.modules({'hero':'red'}, stock=[item])):
            found = slides.collect(None, self.story, self.root, origin='manual')
        self.assertEqual(len(found),2)
        credit = slides.caption_credit(found)
        self.assertIn('نمادین', credit)
        self.assertIn('Artist', credit)
        self.assertIn('https://pixabay.com/example', credit)

    def test_fewer_than_two_stops_carousel(self):
        with patch.dict(sys.modules, self.modules({'hero':'red'})):
            with self.assertRaises(slides.SlideImageError):
                slides.collect(None, self.story, self.root, origin='manual')

    def test_single_image_format_can_use_one(self):
        with patch.dict(sys.modules, self.modules({'hero':'red'})):
            found = slides.collect(None, self.story, self.root, origin='manual', minimum=1)
        self.assertEqual(len(found),1)

    def test_automatic_news_discovers_additional_article_figures(self):
        self.story.pop('image_urls')
        modules = self.modules({'hero':'red', 'second':'blue'})
        with patch.dict(sys.modules, modules), patch.object(slides, 'discover_figures', return_value=['second']):
            found = slides.collect(None, self.story, self.root, origin='automatic')
        self.assertEqual(len(found),2)

    def test_figure_parser_excludes_images_outside_articles(self):
        parser = slides.ArticleFigures()
        parser.feed('<img src="advert.jpg"><article><figure><img src="story.jpg"></figure></article>')
        self.assertEqual(parser.urls, ['story.jpg'])

    def test_asset_management_story_finds_finance_not_unrelated_bitcoin(self):
        import instagram_reel_stock as stock
        import instagram_reel_commons as commons
        story = {'title_original':'Animoca Brands expands asset management business with Abu Dhabi approval'}
        self.assertIn('investment finance', stock.queries(story))
        self.assertTrue(stock._matches_story_topic(story, {'description':'business finance investment'}))
        self.assertFalse(stock._matches_story_topic(story, {'description':'bitcoin cryptocurrency mining'}))
        self.assertEqual(commons._topic(story)[0], 'investment management finance')

    def test_ai_topic_does_not_become_a_bitcoin_search(self):
        import instagram_reel_stock as stock
        story = {'title_original':'ChatGPT and Claude chatbot restrictions'}
        self.assertIn('artificial intelligence', stock.queries(story))
        self.assertFalse(stock._matches_story_topic(story, {'description':'bitcoin cryptocurrency mining'}))

    def test_article_slug_supplies_missing_asset_management_topic(self):
        import instagram_reel_stock as stock
        import instagram_reel_commons as commons
        story = {'title_original':'Animoca Brands obtains approval',
                 'source_url':'https://cointelegraph.com/news/animoca-brands-expands-asset-management-business-with-abu-dhabi-approval'}
        self.assertIn('investment finance', stock.queries(story))
        self.assertTrue(stock._matches_story_topic(story, {'description':'business finance investment'}))
        self.assertFalse(stock._matches_story_topic(story, {'description':'bitcoin cryptocurrency mining'}))
        self.assertEqual(commons._topic(story)[0], 'investment management finance')

    def test_slug_cannot_override_a_recognized_ai_title(self):
        import instagram_reel_stock as stock
        story = {'title_original':'ChatGPT and Claude chatbot restrictions',
                 'source_url':'https://example.com/news/bitcoin-asset-management'}
        self.assertEqual(stock.queries(story)[0], 'artificial intelligence')
        self.assertFalse(stock._matches_story_topic(story, {'description':'bitcoin cryptocurrency mining'}))


if __name__ == '__main__':
    unittest.main()

