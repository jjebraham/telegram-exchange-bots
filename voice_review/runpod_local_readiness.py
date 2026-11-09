#!/usr/bin/env python3
"""Inspect local watchdog readiness and run a short CPU-only encoding benchmark."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def managed_previews(home):
    root = home / '.local/state/kiani-instagram-voice-review/previews'
    if root.is_symlink() or not root.is_dir():
        return []
    metadata_paths = []
    for metadata in root.glob('*/preview.json'):
        try:
            if not metadata.is_symlink() and not metadata.parent.is_symlink():
                metadata_paths.append((metadata.stat().st_mtime, metadata))
        except OSError:
            continue
    for modified, metadata in sorted(metadata_paths, key=lambda row: row[0], reverse=True)[:20]:
        try:
            video = metadata.parent / 'preview.mp4'
            if (metadata.is_symlink() or metadata.parent.is_symlink() or video.is_symlink() or
                    not video.is_file() or video.stat().st_size > 250_000_000):
                continue
            data = json.loads(metadata.read_text(encoding='utf-8'))
            expected = data.get('video_sha256')
            if not isinstance(expected, str) or len(expected) != 64:
                continue
            with video.open('rb') as stream:
                checksum = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    checksum.update(block)
                digest = checksum.hexdigest()
            if digest == expected:
                return [(modified, video, digest)]
        except (OSError, ValueError, TypeError):
            continue
    return []


def benchmark(home, ffmpeg):
    candidates = managed_previews(home)
    if not candidates:
        return {'status': 'unavailable', 'reason': 'no verified private preview'}
    _, source, digest = candidates[0]
    command = [ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error', '-i', str(source),
               '-t', '3', '-map', '0:v:0', '-an', '-c:v', 'libx264', '-preset', 'veryfast',
               '-threads', '2', '-f', 'null', '-']
    started = time.monotonic()
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=90)
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'video_sha256': digest}
    except OSError:
        return {'status': 'unavailable', 'reason': 'ffmpeg could not start'}
    if result.returncode:
        return {'status': 'failed', 'video_sha256': digest}
    return {'status': 'ok', 'source_seconds': 3, 'elapsed_seconds': round(time.monotonic() - started, 2),
            'encoder': 'libx264', 'preset': 'veryfast', 'threads': 2, 'video_sha256': digest}


def main():
    print('Local watchdog service manager:')
    try:
        result = subprocess.run(['systemctl', '--user', 'is-active', 'timers.target'],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=8)
        print('  user timers target active:', result.returncode == 0)
    except (OSError, subprocess.SubprocessError):
        print('  user timers target active: unavailable')
    try:
        import pwd
        username = pwd.getpwuid(os.getuid()).pw_name
        result = subprocess.run(['loginctl', 'show-user', username, '-p', 'Linger', '--value'],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=8)
        linger = result.stdout.strip()
        print('  user lingering:', linger if result.returncode == 0 and linger in ('yes', 'no') else 'unavailable')
    except (ImportError, OSError, subprocess.SubprocessError, KeyError):
        print('  user lingering: unavailable')
    ffmpeg = shutil.which('ffmpeg')
    print('\nLocal CPU encoding benchmark:')
    if not ffmpeg:
        print('  FFmpeg unavailable')
    else:
        print(' ', json.dumps(benchmark(Path.home(), ffmpeg), ensure_ascii=True))
    print('This measures encoding only, not full Reel creation. No Runpod or Instagram request was made.')


if __name__ == '__main__':
    main()
