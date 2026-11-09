import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

import preview_voice_reel as preview
import reel_voice_registry as voices


class PreviewTests(unittest.TestCase):
    def test_candidates_prefer_unseen_then_allow_previously_used_without_duplicates(self):
        rows = [
            {'source_url': 'https://example.com/old'},
            {'source_url': 'https://example.com/new'},
            {'source_url': 'https://example.com/new?utm_source=test'},
        ]
        chosen = preview.preview_candidates(rows, {('example.com', '/old')})
        self.assertEqual([(r['source_url'], reused) for r, reused in chosen], [
            ('https://example.com/new', False), ('https://example.com/old', True)])
        fallback = preview.preview_candidates(rows[:1], {('example.com', '/old')})
        self.assertEqual(len(fallback), 1)
        self.assertTrue(fallback[0][1])

    def test_private_preview_uses_saved_story_and_never_contacts_instagram(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            runtime = home / '.local/state/kiani-instagram-manual-news/source' / ('a' * 40)
            runtime.mkdir(parents=True)
            state = home / '.local/state/kiani-instagram-voice-review'
            state.mkdir(parents=True)
            previous = state / 'previews/previous'
            previous.mkdir(parents=True)
            (previous / 'preview.json').write_text(json.dumps({'source_url': 'https://example.com/old'}))
            db = voices.connect(state / 'voices.sqlite3')
            voices.seed(db)
            voices.refresh_access(db, [{'name': 'Sahar - voice', 'voice_id': 'lIfJn0EyB8lHm00xiGY8'}])
            db.close()
            reel_db = home / 'reels.sqlite3'
            now = time.time()
            con = sqlite3.connect(reel_db)
            con.execute('''CREATE TABLE trial_reels(status TEXT,article_published_at REAL,published_at REAL,
                kind TEXT,source_url TEXT,title_original TEXT,title_fa TEXT,summary_fa TEXT,music_json TEXT,created_at REAL)''')
            con.execute('INSERT INTO trial_reels VALUES(?,?,?,?,?,?,?,?,?,?)',
                        ('published', now - 60, now - 30, 'crypto', 'https://example.com/news',
                         'Saved news', 'خبر آزمایشی', 'متن آزمایشی خبر.', None, now - 90))
            con.execute('INSERT INTO trial_reels VALUES(?,?,?,?,?,?,?,?,?,?)',
                        ('published', now - 60, now - 20, 'crypto', 'https://example.com/old',
                         'Earlier news', 'خبر آزمایشی', 'متن آزمایشی خبر.', None, now - 80))
            con.commit()
            con.close()
            calls = []
            trial = types.ModuleType('instagram_trial_reels')
            trial.DB = reel_db
            trial.STATE = home
            trial._font = lambda assets, size: None
            trial._narrated_chunks = lambda text, assets, has_images: [text]
            trial._prepare_narration = lambda story, folder, voice, assets, has_images: [
                {'path': folder / 'title.wav', 'duration': 2, 'word_starts': [0, .5]},
                {'path': folder / 'body.wav', 'duration': 2, 'word_starts': [0, .5, 1]},
            ]
            def render(story, kind, path, assets, **kwargs):
                calls.append(('render', kwargs['narration']))
                path.write_bytes(b'\0\0\0\x18ftyp' + b'x' * 100_000)
                return 15.0
            trial.render_video = render
            ranked = types.ModuleType('instagram_ranked_news')
            ranked.configure_engine = lambda kind: calls.append(('configure', kind))
            engine = types.ModuleType('crypto_news_trial')
            engine.source_material = lambda row, now, admin_override: dict(row, image_urls=['https://example.com/a.jpg'])
            image = types.ModuleType('instagram_reel_source_image')
            image.fetch = lambda engine, source, url, path, timeout: path.write_bytes(b'image')
            stock = types.ModuleType('instagram_reel_stock')
            stock.collect = lambda *args, **kwargs: []
            commons = types.ModuleType('instagram_reel_commons')
            commons.collect = lambda *args, **kwargs: []
            preview_images = types.ModuleType('reel_preview_images')
            def collect_images(story, material, folder, *args, **kwargs):
                folder.mkdir(parents=True)
                a, b = folder / 'a.jpg', folder / 'b.jpg'
                a.write_bytes(b'first')
                b.write_bytes(b'second')
                return [{'path': a, 'kind': 'publisher'}, {'path': b, 'kind': 'illustrative', 'provider': 'pixabay'}]
            preview_images.collect = collect_images
            preview_images.image_credits = lambda media: 'Pixabay image credit'
            music = types.ModuleType('instagram_trial_music')
            music.select_order = lambda story, recent: ['licensed']
            def retrieve(candidate, path):
                path.write_bytes(b'audio')
                return {'title': 'licensed'}
            music.retrieve_track = retrieve
            music.caption_credit = lambda track: 'Licensed music attribution'
            music.classify_story = lambda story: {'mood': 'energetic', 'source': 'headline', 'signals': ['growth']}
            telegram = types.ModuleType('reel_voice_telegram')
            telegram.verify_destination = lambda token: calls.append(('verified', True))
            def deliver(con, token, output, caption):
                calls.append(('telegram', caption))
                return {'status': 'sent'}
            telegram.deliver_video = deliver
            modules = {'instagram_trial_reels': trial, 'instagram_ranked_news': ranked,
                       'crypto_news_trial': engine, 'instagram_reel_source_image': image,
                       'instagram_reel_stock': stock, 'instagram_reel_commons': commons,
                       'instagram_trial_music': music, 'reel_voice_telegram': telegram,
                       'reel_preview_images': preview_images}
            args = ['preview', '--runtime', str(runtime), '--voice', 'Sahar', '--send']
            with patch.object(Path, 'home', return_value=home), patch.object(sys, 'argv', args), \
                    patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'test',
                                            'KIANI_VOICE_TEST_BOT_TOKEN': '123456789:abcdefghijklmnopqrstuvwx'}), \
                    patch.dict(sys.modules, modules):
                preview.main()
            self.assertEqual([c[0] for c in calls], ['configure', 'verified', 'render', 'telegram'])
            metadata = [p for p in (state / 'previews').glob('*/preview.json') if p.parent != previous]
            self.assertEqual(len(metadata), 1)
            data = json.loads(metadata[0].read_text(encoding='utf-8'))
            self.assertEqual(data['rendering'], 'local libx264; not RunPod')
            self.assertEqual(data['model'], 'eleven_v4')
            self.assertEqual(data['source_url'], 'https://example.com/news')
            self.assertIn('Licensed music attribution', calls[-1][1])
            self.assertIn('Pixabay image credit', calls[-1][1])
            self.assertEqual(len(data['images']), 2)
            self.assertFalse(data['reused_preview_article'])

            # All available URLs are now in prior previews. Reuse one rather
            # than stopping before image collection.
            calls.clear()
            with patch.object(Path, 'home', return_value=home), patch.object(sys, 'argv', args), \
                    patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'test',
                                            'KIANI_VOICE_TEST_BOT_TOKEN': '123456789:abcdefghijklmnopqrstuvwx'}), \
                    patch.dict(sys.modules, modules):
                preview.main()
            self.assertEqual([c[0] for c in calls], ['configure', 'verified', 'render', 'telegram'])
            metadata = [p for p in (state / 'previews').glob('*/preview.json') if p.parent != previous]
            self.assertEqual(len(metadata), 2)
            self.assertTrue(any(json.loads(p.read_text(encoding='utf-8'))['reused_preview_article'] for p in metadata))

            # Exact source matching ignores tracking parameters and refreshes
            # only the private preview. Published records remain unchanged.
            calls.clear()
            before_db = reel_db.read_bytes()
            revised = dict(source_url='https://example.com/news', kind='crypto',
                           title_fa='عنوان روشن و تازه', summary_fa='خلاصه روشن و تازه خبر.')
            comparison = {'stored': {'title_fa': 'خبر آزمایشی', 'summary_fa': 'متن آزمایشی خبر.'},
                          'title_original': 'Saved news', 'revised': {k: revised[k] for k in ('title_fa', 'summary_fa')}}
            targeted = args + ['--source-url', 'https://example.com/news?utm_source=test', '--refresh-translation']
            with patch.object(Path, 'home', return_value=home), patch.object(sys, 'argv', targeted), \
                    patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'test', 'KIANI_VOICE_TEST_BOT_TOKEN': '123456789:abcdefghijklmnopqrstuvwx'}, clear=True), \
                    patch.dict(sys.modules, modules), \
                    patch.object(preview, 'refresh_translation', return_value=(revised, comparison)) as refresh:
                preview.main()
            self.assertEqual(refresh.call_count, 1)
            self.assertEqual(refresh.call_args.args[0]['source_url'], 'https://example.com/news')
            self.assertEqual(reel_db.read_bytes(), before_db)
            comparisons = list((state / 'previews').glob('*/language-comparison.json'))
            self.assertEqual(len(comparisons), 1)
            data = json.loads((comparisons[0].parent / 'preview.json').read_text(encoding='utf-8'))
            self.assertEqual(data['title_fa'], 'عنوان روشن و تازه')
            self.assertEqual(data['language_comparison']['stored']['title_fa'], 'خبر آزمایشی')


if __name__ == '__main__':
    unittest.main()
