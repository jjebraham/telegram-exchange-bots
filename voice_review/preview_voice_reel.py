#!/usr/bin/env python3
"""Make a private local-rendered voice preview from an already published news Reel.

This is preliminary: it does not exercise RunPod or contact Instagram.
"""
import argparse
from contextlib import closing
import getpass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid
import warnings
from urllib.parse import urlsplit


def secret(name, prompt):
    from reel_voice_credentials import get_secret
    value = get_secret(name)
    if value:
        return value
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        value = getpass.getpass(prompt).strip()
    if not value:
        raise RuntimeError('A required private credential was not supplied.')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--voice', default='Sahar')
    parser.add_argument('--send', action='store_true')
    args = parser.parse_args()
    home = Path.home()
    source_root = (home / '.local/state/kiani-instagram-manual-news/source').resolve()
    runtime = args.runtime.resolve()
    if runtime.parent != source_root or not runtime.is_dir():
        raise RuntimeError('The staged Reel runtime path is invalid.')
    sys.path[:0] = [str(runtime), str(runtime / 'selector_trial_runtime'), str(runtime / 'voice_review')]
    import instagram_trial_reels as trial
    import instagram_ranked_news as ranked
    import crypto_news_trial as engine
    import instagram_reel_source_image as source_image
    import instagram_trial_music as music
    import reel_narration_timing as timing
    import reel_voice_registry as voices
    import reel_voice_telegram as telegram

    state = home / '.local/state/kiani-instagram-voice-review'
    registry_path = state / 'voices.sqlite3'
    if registry_path.is_symlink() or not registry_path.is_file():
        raise RuntimeError('The private voice review registry is unavailable.')
    with closing(voices.connect(registry_path)) as voice_db:
        voice = voice_db.execute('SELECT * FROM voices WHERE name=?', (args.voice,)).fetchone()
        if not voice or not voice['voice_id'] or not voice['available'] or not voice['verified']:
            raise RuntimeError('The requested preview voice is not verified and available.')
        voice = dict(voice)
    if trial.DB.is_symlink() or not trial.DB.is_file():
        raise RuntimeError('The existing Reel history is unavailable.')
    now = time.time()
    with closing(sqlite3.connect(trial.DB.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(row) for row in con.execute('''SELECT * FROM trial_reels WHERE status='published'
            AND article_published_at BETWEEN ? AND ? ORDER BY published_at DESC LIMIT 50''', (now - 86400, now))]
        history = con.execute("SELECT music_json FROM trial_reels WHERE music_json IS NOT NULL ORDER BY created_at DESC LIMIT 50").fetchall()
    recent = []
    for row in history:
        try:
            title = json.loads(row['music_json']).get('title')
            if isinstance(title, str):
                recent.append(title)
        except (ValueError, TypeError, AttributeError):
            continue
    if not rows:
        raise RuntimeError('No recently published verified news Reel is available for this preview.')
    def article_key(url):
        parts = urlsplit(str(url or ''))
        return ((parts.hostname or '').lower(), parts.path.rstrip('/'))
    previous = set()
    previews = state / 'previews'
    if previews.is_dir() and not previews.is_symlink():
        for metadata_path in list(previews.glob('*/preview.json'))[-200:]:
            try:
                if not metadata_path.is_symlink() and metadata_path.stat().st_size < 1_000_000:
                    previous.add(article_key(json.loads(metadata_path.read_text(encoding='utf-8')).get('source_url')))
            except (OSError, ValueError, AttributeError):
                continue
    assets = home / 'kiani-instagram-publisher'
    trial._font(assets, 56)
    trial._font(assets, 48)
    folder = state / 'previews' / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(folder, 0o700)
    story, media = None, []
    for row in rows:
        try:
            if article_key(row['source_url']) in previous:
                continue
            sections = [row['title_fa']] + trial._narrated_chunks(row['summary_fa'], assets, has_images=True)
            for text in sections:
                timing.build_script(text)
            ranked.configure_engine(row['kind'])
            material = engine.source_material(row, now, admin_override=False)
            image_urls = material.get('image_urls') or []
            for image_url in image_urls[:8]:
                image_path = folder / ('article-' + str(len(media)) + '.jpg')
                try:
                    source_image.fetch(engine, material['source_url'], image_url, image_path, timeout=8)
                    media.append({'path': image_path, 'kind': 'publisher'})
                except Exception:
                    continue
            if media:
                story = dict(row)
                story['reel_length'] = 'long'
                break
        except Exception:
            continue
    if story is None:
        raise RuntimeError('No different recent published article with a complete-sentence layout and accessible source image was found.')
    for text in [story['title_fa']] + trial._narrated_chunks(story['summary_fa'], assets, has_images=bool(media)):
        timing.build_script(text)
    track, music_file = None, folder / 'music.ogg'
    for candidate in music.select_order(story, recent)[:10]:
        try:
            track = music.retrieve_track(candidate, music_file)
            break
        except Exception:
            if music_file.is_file() and not music_file.is_symlink():
                music_file.unlink()
    if not track:
        raise RuntimeError('No verified licensed music track could be prepared.')
    match = music.classify_story(story)
    print('Music selection:', track.get('name', track.get('title', 'verified track')),
          '| topic mood:', match.get('mood') or 'unclear', flush=True)
    credit = music.caption_credit(track)
    caption = ('Private local-rendered preview | ' + voice['name'] + ' | eleven_v4 | 1.5x\n' +
               'Source: ' + story['source_url'] + '\n\n' + credit)
    if len(caption) > 1024:
        raise RuntimeError('The private preview caption cannot contain the required music credit.')
    token = None
    if args.send:
        token = secret('KIANI_VOICE_TEST_BOT_TOKEN', 'Private test bot token (hidden): ')
        telegram.verify_destination(token)
    key = secret('ELEVENLABS_API_KEY', 'ElevenLabs API key (hidden): ')
    os.environ['ELEVENLABS_API_KEY'] = key
    os.environ['ELEVENLABS_MODEL'] = voices.MODEL
    os.environ['REEL_NARRATION_SPEED'] = str(voices.SPEED)
    os.environ['REEL_MUSIC_VOLUME'] = '0.20'
    os.environ['REEL_AUDIO_DUCKING_ENABLED'] = 'true'
    voice_dir = folder / 'narration'
    voice_dir.mkdir(mode=0o700)
    print('Generating narration for the private preview; ElevenLabs charges may apply.', flush=True)
    started = time.monotonic()
    segments = trial._prepare_narration(story, voice_dir, voice['voice_id'], assets, has_images=bool(media))
    output = folder / 'preview.mp4'
    duration = trial.render_video(story, story['kind'], output, assets,
                                  music_path=music_file, media=media, narration=segments)
    os.chmod(output, 0o600)
    metadata = {'rendering': 'local libx264; not RunPod', 'created_at': time.time(),
                'duration_seconds': duration, 'elapsed_seconds': time.monotonic() - started,
                'voice_name': voice['name'], 'voice_id': voice['voice_id'], 'model': voices.MODEL,
                'speed': voices.SPEED, 'source_url': story['source_url'], 'title_fa': story['title_fa'],
                'summary_fa': story['summary_fa'], 'music_credit': credit,
                'music_match': match, 'music_track': track.get('title'),
                'music_volume_multiplier': 0.20, 'music_ducking': True,
                'sections': [{'path': str(s['path']), 'duration': s['duration'],
                              'word_starts': s['word_starts']} for s in segments],
                'video_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
    meta = folder / 'preview.json'
    meta.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.chmod(meta, 0o600)
    print('Private local preview:', output)
    print('Private preview metadata:', meta)
    if args.send:
        with closing(voices.connect(registry_path)) as voice_db:
            result = telegram.deliver_video(voice_db, token, output, caption)
        print('Private Telegram result:', result['status'])
    print('No Instagram request was made. RunPod has not been tested by this preview.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            print('Private preview stopped:', str(exc), file=sys.stderr)
        else:
            print('Private preview stopped:', type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)

