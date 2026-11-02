import sys
import gc
import types
import tempfile
import time
import unittest
from contextlib import contextmanager, nullcontext
import sqlite3
from pathlib import Path
from unittest.mock import patch
from PIL import Image

sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))
sys.path.insert(0, str(Path(__file__).parent / 'selector_trial_runtime'))
import instagram_manual_news_intake as intake
import economy_news_translation as translation


class IntakeMenuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.patches = [
            patch.object(intake, 'STATE', self.state),
            patch.object(intake, 'DB', self.state / 'intake.sqlite3'),
            patch.object(intake, 'canonical_url', side_effect=lambda url: url),
        ]
        for p in self.patches:
            p.start()
        self.con = intake.open_database()

    def tearDown(self):
        self.con.close()
        for p in reversed(self.patches):
            p.stop()
        gc.collect()
        self.tmp.cleanup()

    def message(self, update_id, text, who=12345):
        return {'update_id': update_id, 'message': {
            'message_id': update_id, 'from': {'id': who},
            'chat': {'id': who, 'type': 'private'}, 'text': text}}

    def tap(self, update_id, token, value, who=12345):
        return {'update_id': update_id, 'callback_query': {
            'id': str(update_id), 'from': {'id': who}, 'data': 'nm:' + token + ':' + value,
            'message': {'chat': {'id': who, 'type': 'private'}}}}

    def test_link_waits_then_reel_length_queues_once(self):
        intake.ingest(self.con, [self.message(1, 'https://example.com/article')], {'12345'})
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM submissions').fetchone()[0], 0)
        token = self.con.execute('SELECT token FROM news_menu').fetchone()[0]
        intake.ingest(self.con, [self.tap(2, token, 'reel')], {'12345'})
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM submissions').fetchone()[0], 0)
        intake.ingest(self.con, [self.tap(3, token, 'short'), self.tap(4, token, 'short')], {'12345'})
        rows = self.con.execute('SELECT request_type,reel_length,status FROM submissions').fetchall()
        self.assertEqual([tuple(row) for row in rows], [('direct_reel', 'short', 'received')])

    def test_formats_are_distinct_and_reject_untrusted_taps(self):
        for index, (button, expected) in enumerate(
                [('post', 'single'), ('slides', 'feed'), ('story', 'story')]):
            intake.ingest(self.con, [self.message(10 + index, 'https://example.com/' + button)], {'12345'})
            token = self.con.execute('SELECT token FROM news_menu WHERE update_id=?', (10+index,)).fetchone()[0]
            intake.ingest(self.con, [self.tap(20 + index, token, button, who=99999)], {'12345'})
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM submissions').fetchone()[0], index)
            intake.ingest(self.con, [self.tap(30 + index, token, button)], {'12345'})
            self.assertEqual(self.con.execute('SELECT request_type FROM submissions WHERE update_id=?', (10+index,)).fetchone()[0], expected)

    def test_existing_command_still_queues_directly(self):
        intake.ingest(self.con, [self.message(1, '/trial https://example.com/news')], {'12345'})
        self.assertEqual(self.con.execute('SELECT request_type FROM submissions').fetchone()[0], 'trial')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM news_menu').fetchone()[0], 0)

    def test_selected_blockchain_news_is_enabled_only_for_admin_worker(self):
        engine = types.SimpleNamespace(PUBLISHERS={})
        intake.configure_admin_source(engine, 'https://blockchain.news/news/example')
        self.assertEqual(engine.PUBLISHERS, {'blockchain.news': 'Blockchain.News'})
        other = types.SimpleNamespace(PUBLISHERS={})
        intake.configure_admin_source(other, 'https://blockchain.news.example/news')
        self.assertEqual(other.PUBLISHERS, {})

    def test_unapproved_source_gets_an_explanatory_message(self):
        class NewsError(Exception):
            pass
        def blocked(*args, **kwargs):
            raise NewsError('Publisher is outside the reviewed trial allowlist.')
        engine = types.SimpleNamespace(NewsError=NewsError, source_material=blocked)
        with self.assertRaises(intake.IntakeError) as caught:
            intake.read_manual_source(engine, {'source_url': 'https://example.com'}, 0, relaxed=True)
        self.assertIn('منبع', str(caught.exception))

    def test_admin_forecast_accepts_zero_relevance(self):
        material = {'source_url': 'https://example.com/forecast'}
        assessment = {'story_type': 'forecast', 'certainty': 'unknown',
                      'relevance': {'points': 0}}
        engine = types.SimpleNamespace(grade=lambda con, rows, now: [dict(rows[0], assessment=assessment)])
        ranked = types.SimpleNamespace(configure_engine=lambda kind: None)
        kind, row = intake.classify(engine, ranked, None, material, 0, trial_relaxed=True)
        self.assertEqual(kind, 'crypto')
        self.assertEqual(row['assessment']['story_type'], 'forecast')

    def test_admin_forecast_render_does_not_require_a_publication_timestamp(self):
        calls = []
        def render(stories, output, asset_root, **kwargs):
            calls.append((stories, kwargs))
            return ['cover.jpg', 'slide.jpg'], 'caption', {}
        renderer = types.SimpleNamespace(metadata=lambda story: story, render_news=render)
        ranked = types.SimpleNamespace(translate=lambda con, row: ('عنوان فارسی', 'متن فارسی'))
        row = dict(source_url='https://example.com/news', source_name='Example', image_url=None,
                   article_date='', title_original='Price prediction for crypto',
                   assessment={'story_type': 'forecast'}, article_published_at=0)
        with patch.dict(sys.modules, {'instagram_news_renderer': renderer}):
            saved, paths, _, manifest = intake.prepare_admin_news(None, row, 'crypto', self.state, self.state, ranked)
        self.assertEqual(saved['article_date'], '')
        self.assertEqual(len(paths), 2)
        self.assertEqual(calls[0][1]['news_label'], 'تحلیل و پیش‌بینی')
        self.assertTrue(calls[0][1]['adaptive_body'])
        self.assertNotIn('news_v2_ranking', manifest)

    def test_manual_feed_formats_publish_admin_forecast_without_automatic_gates(self):
        calls = []
        material = dict(source_url='https://example.com/news', source_name='Example', image_url=None,
                        article_date='', title_original='Crypto price prediction', source_text='Facts',
                        article_published_at=0)
        assessment = {'story_type': 'forecast', 'certainty': 'unknown', 'relevance': {'points': 0}}
        engine = types.ModuleType('crypto_news_trial')
        engine.PUBLISHERS = {}
        engine.init_trial = lambda con: None
        engine.grade = lambda con, rows, now: [dict(rows[0], assessment=assessment)]
        ranked = types.ModuleType('instagram_ranked_news')
        ranked.configure_engine = lambda kind: None
        ranked.histories = lambda now: (set(), [])
        ranked.locks = lambda kind: nullcontext()
        ranked.SOURCES = {'crypto': self.state/'production.sqlite3', 'economy': self.state/'economy.sqlite3'}
        ranked.translate = lambda con, row: ('عنوان فارسی', 'متن فارسی')
        renderer = types.ModuleType('instagram_news_renderer')
        renderer.metadata = lambda story: story
        renderer.hero_image = lambda story, cache: None
        renderer.render_news = lambda *args, **kwargs: (['cover.jpg', 'body.jpg'], 'caption', {})
        crypto = types.ModuleType('instagram_crypto_news')
        crypto.NewsError = type('NewsError', (Exception,), {})

        @contextmanager
        def database(path):
            connection = sqlite3.connect(':memory:')
            connection.row_factory = sqlite3.Row
            connection.execute('CREATE TABLE instagram_news (id TEXT, title_fa TEXT)')
            try:
                yield connection
            finally:
                connection.close()

        def save_story(con, saved):
            con.execute('INSERT INTO instagram_news VALUES (?,?)', ('id', saved['title_fa']))
            return 'id'

        def publish(con, stories, paths, caption, ig, manifest):
            calls.append(('feed', len(paths), manifest['manual_telegram_intake']['category']))
            return ig._publish_container('fake-container')

        crypto.database, crypto.save_story, crypto.publish = database, save_story, publish
        batch = types.ModuleType('instagram_news_batch')
        batch.guard = lambda: {'reserved_units': 4}
        ig = types.ModuleType('instagram_daily_rates')
        ig._publish_container = lambda container: 'fake-media'
        old_is_dir = Path.is_dir
        def is_dir(path):
            return True if path.name == 'kiani-instagram-publisher' else old_is_dir(path)
        def read_source(engine, story, now, *, relaxed=False):
            self.assertTrue(relaxed)
            return dict(material)
        modules = {'crypto_news_trial': engine, 'instagram_ranked_news': ranked,
                   'instagram_news_renderer': renderer, 'instagram_crypto_news': crypto,
                   'instagram_news_batch': batch, 'instagram_daily_rates': ig}
        with patch.dict(sys.modules, modules), patch.object(Path, 'is_dir', is_dir), \
             patch.object(intake, 'read_manual_source', side_effect=read_source), \
             patch.object(intake, 'publish_manual_story', return_value='fake-story') as story:
            for index, request in enumerate(('single', 'feed', 'story'), 1):
                self.con.execute('DELETE FROM submissions')
                self.con.execute("INSERT INTO submissions(update_id,admin_id,chat_id,message_id,source_url,source_key,received_at,status,request_type,response,reply_sent) VALUES(?,?,?,?,?,?,?,'received',?,'',0)",
                                 (index,'12345','12345',index,material['source_url'],'key',time.time(),request))
                record = dict(self.con.execute('SELECT * FROM submissions WHERE update_id=?', (index,)).fetchone())
                _, _, media = intake.process_submission(self.con, record, self.state)
                self.assertEqual(media, 'fake-story' if request == 'story' else 'fake-media')
            self.assertEqual(calls, [('feed', 1, 'crypto'), ('feed', 2, 'crypto')])
            self.assertEqual(story.call_args.args[-1], 0)

    def test_manual_reel_formats_accept_old_forecast_without_hard_news_gate(self):
        material = dict(source_url='https://example.com/news', source_name='Example', image_url=None,
                        image_urls=[], article_date='', title_original='Crypto price prediction',
                        source_text='Facts', article_published_at=0)
        assessment = {'story_type': 'forecast', 'certainty': 'unknown', 'relevance': {'points': 0}}
        engine = types.ModuleType('crypto_news_trial')
        engine.PUBLISHERS = {}
        engine.NewsError = type('NewsError', (Exception,), {})
        engine.init_trial = lambda con: None
        engine.grade = lambda con, rows, now: [dict(rows[0], assessment=assessment)]
        ranked = types.ModuleType('instagram_ranked_news')
        ranked.configure_engine = lambda kind: None
        ranked.locks = lambda kind: nullcontext()
        ranked.translate = lambda con, row: ('عنوان فارسی', 'متن فارسی')
        crypto = types.ModuleType('instagram_crypto_news')
        crypto.NewsError = engine.NewsError
        crypto.database = lambda path: nullcontext()
        batch = types.ModuleType('instagram_news_batch')
        batch.guard = lambda: {}
        reel = types.ModuleType('instagram_trial_reels')
        reel.TrialReelError = type('TrialReelError', (Exception,), {})
        reel.check_admin_daily_limit = lambda *args: None
        collected = []
        def create(story, kind, **kwargs):
            collected.append((story, kind, kwargs))
            return 'fake-reel-id'
        reel.create_trial = reel.create_reel = create
        old_is_dir = Path.is_dir
        def is_dir(path):
            return True if path.name == 'kiani-instagram-publisher' else old_is_dir(path)
        def read_source(engine, story, now, *, relaxed=False):
            self.assertTrue(relaxed)
            return dict(material)
        modules = {'crypto_news_trial': engine, 'instagram_ranked_news': ranked,
                   'instagram_crypto_news': crypto, 'instagram_news_batch': batch,
                   'instagram_trial_reels': reel}
        with patch.dict(sys.modules, modules), patch.object(Path, 'is_dir', is_dir), \
             patch.object(intake, 'read_manual_source', side_effect=read_source):
            for index, request, process in (
                    (1, 'trial', intake.process_trial_submission.__wrapped__),
                    (2, 'direct_reel', intake.process_direct_reel_submission.__wrapped__)):
                self.con.execute('DELETE FROM submissions')
                self.con.execute("INSERT INTO submissions(update_id,admin_id,chat_id,message_id,source_url,source_key,received_at,status,request_type,response,reply_sent) VALUES(?,?,?,?,?,?,?,'received',?,'',0)",
                                 (index,'12345','12345',index,material['source_url'],'key',time.time(),request))
                record = dict(self.con.execute('SELECT * FROM submissions WHERE update_id=?', (index,)).fetchone())
                self.assertEqual(process(self.con, record, self.state)[2], 'fake-reel-id')
        self.assertEqual(len(collected), 2)
        self.assertTrue(all(story['story_type'] == 'forecast' and story['article_published_at'] == 0
                            for story, _, _ in collected))

    def test_story_uses_story_container_and_records_uncertain_publish(self):
        intake.ingest(self.con, [self.message(1, '/trial https://example.com/news')], {'12345'})
        picture = self.state / 'cover.jpg'
        Image.new('RGB', (1080, 1350), 'white').save(picture)
        calls = []

        class Instagram:
            def _public_image_url(self, path):
                with Image.open(path) as photo:
                    self.assert_size = photo.size
                return 'https://example.com/image.jpg'

            def verify_public_image(self, url):
                calls.append(('verified', url))

            def _create_container(self, fields):
                calls.append(('container', fields))
                return 'container'

            def _wait_for_container(self, container):
                calls.append(('ready', container))

            def _publish_container(self, container):
                calls.append(('publish', container))
                raise RuntimeError('response lost')

        api = Instagram()
        with self.assertRaises(RuntimeError):
            intake.publish_manual_story(self.con, {'update_id': 1}, [picture], self.state,
                'https://example.com', api, lambda: None, 0)
        self.assertEqual(api.assert_size, (1080, 1920))
        self.assertEqual(calls[1][1]['media_type'], 'STORIES')
        self.assertEqual(self.con.execute('SELECT status FROM submissions WHERE update_id=1').fetchone()[0], 'story_publishing')
        intake.recover_interrupted(self.con)
        self.assertEqual(self.con.execute('SELECT status FROM submissions WHERE update_id=1').fetchone()[0], 'needs_review')

    def test_short_summary_keeps_source_number_check(self):
        material = {'title_original': 'Company announced 5 products', 'source_text': 'There were 5 products.'}
        title = 'شرکت از ۵ محصول جدید رونمایی کرد'
        summary = 'شرکت اعلام کرد که ۵ محصول جدید را معرفی کرده است.'
        good = translation.Completion('{"summary_fa":"شرکت از ۵ محصول جدید رونمایی کرد."}')
        bad = translation.Completion('{"summary_fa":"شرکت از ۹۹ محصول جدید رونمایی کرد."}')
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'dummy'}), patch.object(translation, 'request_completion', return_value=good):
            self.assertIn('۵', intake.short_reel_summary(title, summary, material))
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'dummy'}), patch.object(translation, 'request_completion', return_value=bad):
            result = intake.short_reel_summary(title, summary, material)
            self.assertEqual(result, summary)
            self.assertNotIn('۹۹', result)

    def test_short_summary_fallback_preserves_complete_sentences(self):
        first = 'این نخستین جمله خبر است و اطلاعات اصلی را بیان می‌کند.'
        rest = 'این جمله دوم توضیحات تکمیلی را شرح می‌دهد و اطلاعات بیشتری ارائه می‌کند.'
        result = intake.extractive_short_summary(first + ' ' + rest, limit=len(first) + 1)
        self.assertEqual(result, first)
        self.assertIsNone(intake.extractive_short_summary('کلمه ' * 100, limit=100))

    def test_long_summary_packs_sentences_without_losing_words(self):
        from instagram_trial_reels import _chunks
        summary = ' '.join('این جمله شماره {} درباره خبر است.'.format(n) for n in range(1, 13))
        chunks = _chunks(summary)
        self.assertLess(len(chunks), 12)
        self.assertEqual(' '.join(chunks).split(), summary.split())
        self.assertTrue(all(len(chunk) <= 170 for chunk in chunks))

    def test_long_reel_can_use_more_than_eight_complete_cards(self):
        import instagram_trial_reels as reel
        original = ' '.join(('واژه' + str(i) + 'ب' * 135) for i in range(10))
        captured = []
        def render(t, title, source, kind, story_type, chunks, destination, *args, **kwargs):
            captured.extend(chunks)
            Path(destination).write_bytes(b'x' * 100001)
        fake_motion = types.SimpleNamespace(render=render)
        story = {'title_fa':'عنوان فارسی خبر', 'summary_fa':original,
                 'source_name':'Example', 'reel_length':'long'}
        with patch.dict(sys.modules, {'instagram_reel_motion':fake_motion}), \
             patch.object(reel, '_probe_video', return_value=30):
            reel.render_video(story, 'crypto', self.state/'out.mp4', self.state,
                              ffmpeg='fake', ffprobe='fake')
        self.assertGreater(len(captured), 8)
        self.assertEqual(' '.join(captured).split(), original.split())

    def test_short_summary_only_retries_when_no_safe_extract_exists(self):
        long_sentence = 'متن ' * 100
        material = {'title_original':'Example', 'source_text':long_sentence}
        bad = translation.Completion('{bad json')
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY':'dummy'}), \
             patch.object(translation, 'request_completion', return_value=bad) as call:
            with self.assertRaises(intake.IntakeError):
                intake.short_reel_summary('عنوان فارسی خبر', long_sentence, material)
        self.assertEqual(call.call_count, 2)


if __name__ == '__main__':
    unittest.main()

