#!/usr/bin/env python3
"""Local narration readiness; no synthesis, Telegram, Instagram or RunPod calls."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

import reel_local_settings as settings
import reel_narration_usage as usage
import reel_voice_credentials as credentials
import reel_voice_registry as registry


def main():
    home = Path.home()
    root = home / '.local/state'
    config = json.loads((home / '.config/kiani-instagram-manual-news/config.json').read_text())
    print('Active Reel revision:', config['installed_revision'])
    print('Staged voice code:', Path(__file__).resolve().parent.parent.name)
    local = settings.read()
    gpu_enabled = os.environ.get('REEL_RUNPOD_ENABLED', local.get('REEL_RUNPOD_ENABLED', 'false')) == 'true'
    print('Renderer:', 'managed on-demand Runpod GPU' if gpu_enabled else 'local CPU')
    print('CPU fallback:', local.get('REEL_LOCAL_RENDER_FALLBACK', 'true'))
    if gpu_enabled:
        from runpod_ephemeral import report
        print('Managed GPU compute:', json.dumps(report(home)))
    print('FFmpeg available:', bool(shutil.which('ffmpeg')))
    print('ffprobe available:', bool(shutil.which('ffprobe')))
    print('ElevenLabs key configured:', bool(credentials.get_secret('ELEVENLABS_API_KEY')))
    local = settings.read()
    print('Local narration flag:', local.get('REEL_ELEVENLABS_ENABLED', 'false'))
    print('Monthly submitted-character limit:', local.get('REEL_ELEVENLABS_MONTHLY_CHAR_LIMIT', 'not configured'))
    voice_db = root / 'kiani-instagram-voice-review/voices.sqlite3'
    if voice_db.is_symlink() or not voice_db.is_file():
        raise ValueError('The existing voice registry is missing or unsafe.')
    with closing(sqlite3.connect(voice_db.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.row_factory = sqlite3.Row
        eligible = []
        for row in registry.list_voices(con):
            allowed = registry.eligible(row)
            if allowed:
                eligible.append(row['name'])
            if row['voice_id']:
                print(row['name'], '| score:', row['score'], '| rating:', row.get('rating_status', 'final'),
                      '| evaluation:', bool(row.get('evaluation_enabled', 0)), '| eligible:', allowed)
    print('Eligible voices (evaluation or final approval):', ', '.join(eligible) or 'none; enrollment required')
    previews = root / 'kiani-instagram-voice-review/previews'
    verified = 0
    for meta in sorted(previews.glob('*/preview.json'), reverse=True)[:50]:
        if meta.is_symlink() or meta.stat().st_size > 2_000_000:
            continue
        try:
            data = json.loads(meta.read_text(encoding='utf-8'))
            video = meta.parent / 'preview.mp4'
            if (not video.is_symlink() and video.is_file() and video.stat().st_size <= 250_000_000
                    and data.get('video_sha256') == hashlib.sha256(video.read_bytes()).hexdigest()
                    and data.get('music_volume_multiplier') == .20 and data.get('music_ducking') is True
                    and len({i.get('sha256') for i in data.get('images', []) if i.get('sha256')}) >= 2):
                verified += 1
        except (OSError, ValueError, TypeError, KeyError):
            continue
    print('Saved multi-image previews with matching video checksums and 20% music:', verified)
    print('Current UTC-month narration usage:', json.dumps(usage.report(root / 'kiani-instagram-trial-reels/narration-cache.sqlite3')))
    print('Read-only readiness check complete. No service was contacted and no schedule was changed.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Local narration readiness stopped:', type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
