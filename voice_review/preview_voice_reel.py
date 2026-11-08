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


def article_key(url):
    parts = urlsplit(str(url or ''))
    return ((parts.hostname or '').lower(), parts.path.rstrip('/'))


def preview_candidates(rows, previous, limit_per_group=5):
    """Prefer different stories, then reuse earlier previews as a fallback."""
    fresh, reused, seen = [], [], set()
    for row in rows:
        key = article_key(row.get('source_url'))
        if not all(key) or key in seen:
            continue
        seen.add(key)
        (reused if key in previous else fresh).append(row)
    return [(row, False) for row in fresh[:limit_per_group]] + [
        (row, True) for row in reused[:limit_per_group]]


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
    import instagram_reel_stock as stock
    import instagram_reel_commons as commons
    import instagram_trial_music as music
    import reel_narration_timing as timing
    import reel_voice_registry as voices
    import reel_voice_telegram as telegram
    import reel_preview_images as preview_images

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
            AND article_published_at BETWEEN ? AND ? ORDER BY published_at DESC LIMIT 50''', (now - 7 * 86400, now))]
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
    attempted = 0
    reused_story = False
    for row, reused in preview_candidates(rows, previous):
        attempted += 1
        stage = 'text layout'
        try:
            if reused:
                print('Trying a previously previewed article with a new image search.', flush=True)
            sections = [row['title_fa']] + trial._narrated_chunks(row['summary_fa'], assets, has_images=True)
            for text in sections:
                timing.build_script(text)
            stage = 'article retrieval'
            ranked.configure_engine(row['kind'])
            # This is a private preview of an already-published story, not
            # permission to publish an old article or alter live freshness rules.
            historical = now - row['article_published_at'] > 86400
            material = engine.source_material(row, now, admin_override=historical)
            if historical:
                print('Using an older already-published story for this private test.', flush=True)
            stage = 'image collection'
            candidate_media = preview_images.collect(
                row, material, folder / ('images-' + str(attempted)), engine, source_image,
                state=trial.STATE, stock_collector=stock.collect, commons_collector=commons.collect)
            print('Verified distinct images for candidate:', len(candidate_media), flush=True)
            if len(candidate_media) >= 2:
                story = dict(row)
                story['reel_length'] = 'long'
                media = candidate_media
                reused_story = reused
                break
        except Exception as exc:
            print('Preview candidate unavailable:', stage, type(exc).__name__, flush=True)
            continue
    if story is None:
        raise RuntimeError('No eligible saved article supplied two distinct relevant images and a complete-sentence layout; no narration was requested.')
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
    def caption_for(items):
        image_credit = preview_images.image_credits(items)
        return ('Private local-rendered preview | ' + voice['name'] + ' | eleven_v4 | 1.5x\n' +
                ('Older news, private test only\n' if historical else '') +
                'Source: ' + story['source_url'] + '\n\n' + credit +
                ('\n\nIllustrative images:\n' + image_credit if image_credit else ''))
    caption = caption_for(media)
    while len(caption) > 1024 and len(media) > 2:
        media.pop()
        caption = caption_for(media)
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
                'reused_preview_article': reused_story,
                'historical_preview_article': historical,
                'music_match': match, 'music_track': track.get('title'),
                'music_volume_multiplier': 0.20, 'music_ducking': True,
                'images': [{'kind': item.get('kind'), 'provider': item.get('provider', 'publisher'),
                            'source_url': item.get('source_url'), 'path': str(item['path']),
                            'sha256': hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()}
                           for item in media],
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
