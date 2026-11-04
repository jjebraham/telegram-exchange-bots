#!/usr/bin/env python3
"""Check a few real soundtracks and decode them; never publish or use a model."""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', required=True, type=Path)
args = parser.parse_args()
sys.path.insert(0, str(args.runtime.resolve()))
import instagram_trial_music as music

if len(music.TRACKS) != 100 or len({t['title'] for t in music.TRACKS}) != 100:
    raise RuntimeError('Expected 100 distinct configured tracks.')
ffmpeg = shutil.which('ffmpeg')
if not ffmpeg:
    raise RuntimeError('ffmpeg is unavailable.')

samples = [
    next(t for t in music.TRACKS if t.get('mime', 'application/ogg') == 'application/ogg'),
    next(t for t in music.TRACKS if t.get('mime') == 'audio/mpeg' and t.get('license') == 'CC BY 4.0'),
    next(t for t in music.TRACKS if t.get('mime') == 'audio/mpeg' and t.get('license') == 'CC BY 3.0'
         and 'audionautix.com' in t.get('credit', '')),
]
with tempfile.TemporaryDirectory(prefix='kiani-music-pool-') as temp:
    for index, track in enumerate(samples):
        path = Path(temp) / f'sample-{index}.ogg'
        info = music.retrieve_track(track, path)
        if info['license'] not in music.caption_credit(info):
            raise RuntimeError('Music caption omitted its license.')
        subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-t', '2', '-f', 'null', '-'],
                       check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print('Verified and decoded:', info['name'], '|', info['license'], flush=True)
print('100 configured tracks; three representative downloads verified and decoded.')
print('No DeepSeek, Telegram, or Instagram request was made.')

