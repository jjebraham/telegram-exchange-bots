#!/usr/bin/env python3
"""Inspect speech-only Persian vowels; optionally make one cached DeepSeek pass."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--live', action='store_true', help='Use the existing DeepSeek key for the latest saved Reel. Model charges may apply.')
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    source_root = (Path.home() / '.local/state/kiani-instagram-manual-news/source').resolve()
    if runtime.parent != source_root or not re.fullmatch('[0-9a-f]{40}', runtime.name):
        raise ValueError('Expected the pinned staged Reel runtime.')
    sys.path[:0] = [str(runtime), str(runtime / 'selector_trial_runtime'), str(runtime / 'voice_review')]
    from reel_narration_timing import apply_diacritics, build_script
    original = 'احتمال در اختیار داشتن کلید توسط سارق'
    script, tokens = build_script(original)
    marked = original.replace('احتمال', 'احتمالِ', 1)
    _, mapped = apply_diacritics(script, tokens, marked)
    assert [t.text for t in mapped] == original.split()
    print('Display text:', original)
    print('Speech-only example:', marked)
    print('Visible words and timing-token count preserved:', len(mapped))
    if not args.live:
        print('Offline mapping check passed; no service was contacted.')
        return
    import instagram_trial_reels as trial
    import reel_local_settings as settings
    from reel_persian_pronunciation import prepare
    from economy_news_translation import load_translation_env
    settings.load()
    load_translation_env(Path.home() / 'sub/.env')
    if not os.environ.get('DEEPSEEK_API_KEY', '').strip():
        raise RuntimeError('The existing DeepSeek translation key is not available.')
    if trial.DB.is_symlink() or not trial.DB.is_file():
        raise ValueError('Saved Reel history is unavailable.')
    with closing(sqlite3.connect(trial.DB.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM trial_reels WHERE status='published' ORDER BY published_at DESC LIMIT 1").fetchone()
    if not row:
        raise ValueError('No saved published Reel was found.')
    story = dict(row)
    sections = [story['title_fa']] + trial._narrated_chunks(story['summary_fa'], Path.home() / 'kiani-instagram-publisher', has_images=True)
    marked, status = prepare(sections, trial.STATE / 'pronunciation-cache.sqlite3', context=story.get('title_original', ''))
    print('Saved Reel:', story['trial_id'])
    print('Pronunciation pass:', status)
    if status not in ('prepared', 'cached'):
        raise RuntimeError('No verified DeepSeek pronunciation result was prepared; keep the current production runtime.')
    for index, (text, spoken) in enumerate(zip(sections, marked), 1):
        print('\nSection', index)
        print('Display:', text)
        print('Speech:', spoken)
    print('\nOnly pronunciation marks were permitted. No ElevenLabs, Telegram or Instagram request was made.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Pronunciation check stopped:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
