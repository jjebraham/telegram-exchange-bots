#!/usr/bin/env python3
"""Offline cover and mobile-layout preflight; no external service calls."""
import argparse
from pathlib import Path
import shutil
import sys
import tempfile

from PIL import Image, ImageDraw

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--assets', type=Path, default=Path.home() / 'kiani-instagram-publisher')
args = parser.parse_args()
runtime = args.runtime.resolve()
sys.path[:0] = [str(runtime), str(runtime / 'selector_trial_runtime')]
import instagram_trial_reels as trial
import instagram_reel_motion as motion

assets = args.assets.resolve()
ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
if not ffmpeg or not ffprobe:
    raise SystemExit('ffmpeg and ffprobe are required.')

with tempfile.TemporaryDirectory(prefix='kiani-cover-check-') as tmp:
    root = Path(tmp)
    trial.STATE = root
    picture = root / 'sample.jpg'
    im = Image.new('RGB', (1000, 600), '#183E64')
    ImageDraw.Draw(im).rectangle((100, 100, 450, 500), fill='#13B9AA')
    im.save(picture, 'JPEG')
    media = [{'path': picture, 'kind': 'publisher'}]
    title = 'نمونه آزمایشی خبر برای نمایش کامل عنوان روی جلد ریل'
    img = motion.grid_cover(trial, title, 'crypto', assets, media)
    if img.size != (1080, 1920):
        raise RuntimeError('Unexpected cover size.')
    video = root / 'preview.mp4'
    motion.render(trial, title, 'منبع آزمایشی', 'crypto', 'hard_news',
                  ['این متن آزمایشی برای بررسی جای تصویر و نوشته است.',
                   'این هم بخش دوم برای بررسی فاصله متن از پایین صفحه است.'],
                  video, assets, media, None, ffmpeg)
    duration = trial._probe_video(video, ffprobe)
    print('Cover and Reel without narration verified:', round(duration, 2), 'seconds')
    print('No Azure, DeepSeek or Instagram request was made.')
