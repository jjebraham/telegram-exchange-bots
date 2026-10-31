#!/usr/bin/env python3
"""Private, offline preflight for menu selection, Story safety and Reel durations."""
import argparse
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--assets', type=Path, default=Path.home()/'kiani-instagram-publisher')
args = parser.parse_args()
runtime = args.runtime.resolve()
sys.path[:0] = [str(runtime), str(runtime / 'selector_trial_runtime')]
import instagram_news_menu as menu
import instagram_manual_news_intake as intake
import instagram_trial_reels as reel
from PIL import Image

with tempfile.TemporaryDirectory(prefix='kiani-menu-check-') as tmp:
    root = Path(tmp)
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE submissions (update_id INTEGER PRIMARY KEY, status TEXT)')
    menu.init(con)
    for num, (button, request) in enumerate((('reel', 'direct_reel'), ('trial', 'trial'),
            ('post', 'single'), ('slides', 'feed'), ('story', 'story')), 1):
        token = menu.create(con, update_id=num, admin_id='12345', chat_id='12345',
                            message_id=num, source_url='https://example.com/news',
                            source_key='key', now=100)
        state, row = menu.select(con, token=token, value=button, admin_id='12345', chat_id='12345', now=101)
        if button in {'reel', 'trial'}:
            assert state == 'length'
            state, row = menu.select(con, token=token, value='short', admin_id='12345', chat_id='12345', now=102)
            assert row['reel_length'] == 'short'
        assert state == 'ready' and row['request_type'] == request
        again, _ = menu.select(con, token=token, value=button, admin_id='12345', chat_id='12345', now=103)
        assert again == 'already_ready'
    print('Five menu formats, duration selection and duplicate taps verified.')

    con.execute("INSERT INTO submissions VALUES(100, 'processing')")
    image = root/'cover.jpg'
    Image.new('RGB', (1080, 1350), 'white').save(image)
    class FakeInstagram:
        def _public_image_url(self, path):
            with Image.open(path) as opened:
                assert opened.size == (1080, 1920)
            return 'https://example.com/image.jpg'
        def verify_public_image(self, url): pass
        def _create_container(self, fields):
            assert fields['media_type'] == 'STORIES'
            return 'container'
        def _wait_for_container(self, container): pass
        def _publish_container(self, container):
            assert con.execute('SELECT status FROM submissions WHERE update_id=100').fetchone()[0] == 'story_publishing'
            return 'fake-story-id'
    assert intake.publish_manual_story(con, {'update_id':100}, [image], root,
        'https://example.com', FakeInstagram(), lambda: None, time.time()) == 'fake-story-id'
    print('Story format and publishing state verified with a fake Instagram client.')

    reel.STATE = root
    assets = args.assets
    story = {'title_fa':'نمونه خبری برای بررسی ریل',
             'summary_fa':'این متن نمونه برای بررسی زمان نمایش در ریل ساخته شده است. این بخش دوم توضیح خبر را بیان می‌کند.',
             'source_name':'نمونه', 'story_type':'hard_news'}
    for length in ('short', 'long'):
        duration = reel.render_video(dict(story, reel_length=length), 'crypto',
                                     root/(length+'.mp4'), assets)
        assert (14.85 <= duration <= 30.15) if length == 'short' else (12 <= duration <= 90.15)
        print(length, 'Reel duration:', round(duration, 2), 'seconds')
    print('Offline preflight passed; no Telegram, DeepSeek or Instagram request was made.')
