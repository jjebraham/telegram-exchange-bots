from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import instagram_crypto_news as news


class InstagramNewsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / 'instagram.sqlite3'
        self.now = 1791570000.0

    def tearDown(self):
        self.tmp.cleanup()

    def story(self, url='https://example.com/article', title='Bitcoin security hack'):
        return dict(source_url=url, title_original=title,
                    title_fa='خبر مهم بیت‌کوین', summary_fa='خبر درباره امنیت بیت‌کوین است.',
                    telegram_posted_at=self.now-60, origin='telegram')

    def test_url_tracking_removed_without_removing_semantic_query(self):
        self.assertEqual(news.canonical_url('https://EXAMPLE.com/story/?utm_source=rss&id=12#part'),
                         'https://example.com/story?id=12')
        with self.assertRaises(news.NewsError):
            news.canonical_url('file:///etc/passwd')

    def test_time_window_excludes_future_old_and_manual(self):
        with news.database(self.db) as con:
            for offset, origin in ((-60, 'telegram'), (-86401, 'telegram'), (1, 'telegram'), (-2, 'manual')):
                story = self.story(f'https://example.com/{offset}')
                story.update(telegram_posted_at=self.now+offset, origin=origin)
                news.save_story(con, story, self.now)
            self.assertEqual(len(news.select_stories(con, 5, self.now)), 1)

    def test_existing_translations_imported_without_mutating_json(self):
        original = 'Bitcoin: A security update'
        history = {'entries': [{'title': original, 'url': 'https://example.com/a?utm_source=rss', 'timestamp': self.now-60}]}
        cache = {original+':first text': {'title': 'خبر قدیمی', 'summary': 'ترجمه قبلی.', 'timestamp': self.now-200},
                 original+':latest text': {'title': 'خبر جدید', 'summary': 'ترجمه جدید.', 'timestamp': self.now-61},
                 original+':future revision': {'title': 'آینده', 'summary': 'بعد از ارسال.', 'timestamp': self.now+200}}
        for name, payload in (('crypto_news_history.json', history), ('translation_cache.json', cache)):
            (self.root/name).write_text(json.dumps(payload), encoding='utf-8')
        before = [(self.root/name).read_bytes() for name in ('crypto_news_history.json','translation_cache.json')]
        with news.database(self.db) as con:
            self.assertEqual(news.sync_telegram(con, self.root, self.now)['imported'], 1)
            self.assertEqual(news.select_stories(con, now=self.now)[0]['title_fa'], 'خبر جدید')
            news.sync_telegram(con, self.root, self.now)
            self.assertEqual(con.execute('SELECT count(*) FROM instagram_news').fetchone()[0], 1)
        self.assertEqual(before, [(self.root/name).read_bytes() for name in ('crypto_news_history.json','translation_cache.json')])

    def test_missing_translation_is_skipped(self):
        (self.root/'crypto_news_history.json').write_text(json.dumps({'entries': [dict(title='Missing', url='https://example.com', timestamp=self.now-20)]}))
        (self.root/'translation_cache.json').write_text('{}')
        with news.database(self.db) as con:
            self.assertEqual(news.sync_telegram(con, self.root, self.now)['missing_translation'], 1)
            self.assertEqual(news.select_stories(con, now=self.now), [])

    def test_editorial_ranking_uses_importance_then_freshness(self):
        with news.database(self.db) as con:
            low = self.story('https://example.com/minor', 'Company introduces a new product')
            high = self.story('https://example.com/hack', 'Bitcoin exchange security hack')
            news.save_story(con, low, self.now)
            news.save_story(con, high, self.now)
            self.assertEqual(news.select_stories(con, now=self.now)[0]['source_url'], high['source_url'])

    def test_manual_metadata_preserved_when_item_is_imported_again(self):
        with news.database(self.db) as con:
            story = self.story()
            news.save_story(con, story, self.now)
            manual = dict(story, origin='manual', image_url='https://example.com/image.jpg', article_date='2026-10-09', highlights=[{'value':'90','label':'پرونده'}])
            news.save_story(con, manual, self.now)
            news.save_story(con, story, self.now)
            saved = news.select_stories(con, now=self.now)[0]
            self.assertEqual(saved['image_url'], manual['image_url'])
            self.assertEqual(saved['origin'], 'telegram')
            self.assertEqual(json.loads(saved['highlights_json']), manual['highlights'])

    def test_claim_blocks_duplicate_and_pending_attempts(self):
        with news.database(self.db) as con:
            news.save_story(con, self.story(), self.now)
            stories = news.select_stories(con, now=self.now)
            news.claim(con, stories, 'first', {})
            with self.assertRaises(news.NewsError):
                news.claim(con, stories, 'second', {})
            self.assertEqual(news.select_stories(con, now=self.now), [])

    def test_publish_success_and_unknown_result_recorded_separately(self):
        class FakeIG:
            fail = False
            def _public_image_url(self, path): return 'https://example.com/' + path.name
            def verify_public_image(self, url): pass
            def _create_container(self, fields): return 'container-1'
            def _wait_for_container(self, container): pass
            def _publish_container(self, container):
                if self.fail: raise TimeoutError()
                return 'media-1'
        fake = FakeIG()
        with news.database(self.db) as con:
            news.save_story(con, self.story(), self.now)
            stories = news.select_stories(con, now=self.now)
            self.assertEqual(news.publish(con, stories, [Path('one.jpg')], 'caption', fake, {}), 'media-1')
            row = con.execute('SELECT * FROM instagram_news_publications').fetchone()
            self.assertEqual(row['status'], 'published')
            self.assertEqual(row['media_id'], 'media-1')
            news.save_story(con, self.story('https://example.com/second'), self.now)
            stories = news.select_stories(con, now=self.now)
            fake.fail = True
            with self.assertRaises(TimeoutError):
                news.publish(con, stories, [Path('two.jpg')], 'caption', fake, {})
            self.assertEqual(con.execute("SELECT status FROM instagram_news_publications WHERE container_id='container-1' AND media_id IS NULL").fetchone()[0], 'needs_review')
            self.assertEqual(news.select_stories(con, now=self.now), [])

    def test_claim_is_atomic_across_a_group(self):
        with news.database(self.db) as con:
            news.save_story(con, self.story(), self.now)
            news.save_story(con, self.story('https://example.com/second'), self.now)
            stories = news.select_stories(con, 2, self.now)
            news.claim(con, [stories[1]], 'earlier', {})
            with self.assertRaises(news.NewsError):
                news.claim(con, stories, 'group', {})
            self.assertEqual(con.execute('SELECT count(*) FROM instagram_news_publications').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
