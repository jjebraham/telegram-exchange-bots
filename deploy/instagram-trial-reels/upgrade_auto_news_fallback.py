#!/usr/bin/env python3
"""Stage and install the reviewed automatic-news image fallback."""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

BASE = '15a56a5ad104332ca81af4c3f46a401a8b6afa3b'
ORIGINAL = 'a22cb107c66c366a50127aee49d13cb6bb44f7f2'
WORKER = 'deploy/instagram-trial-reels/automatic_ranked_news_images.py'
TEST = 'deploy/instagram-trial-reels/test_news_image_fallback.py'
FILES = ('instagram_ranked_news.py', 'crypto_news_trial.py', 'instagram_news_batch.py',
         'instagram_insights_data.py', 'selector_trial_runtime/economy_news_picker.py',
         'selector_trial_runtime/economy_news_translation.py',
         'selector_trial_runtime/instagram_crypto_news.py',
         'selector_trial_runtime/instagram_news_renderer.py', 'selector_trial_runtime/PINNED.md',
         'instagram_news_slide_images.py', 'instagram_reel_source_image.py',
         'instagram_reel_stock.py', 'instagram_reel_commons.py')
RUNTIME = tuple(name for name in FILES if name != 'selector_trial_runtime/PINNED.md')
REPLACED = {'selector_trial_runtime/instagram_news_renderer.py',
            'instagram_news_slide_images.py', 'instagram_reel_source_image.py',
            'instagram_reel_stock.py', 'instagram_reel_commons.py'}


def base_spec(name):
    # The previous installer assembled a release from two pinned revisions.
    if name == 'instagram_ranked_news.py':
        return BASE, WORKER
    return (BASE if name in REPLACED else ORIGINAL), name


def owned(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError('Unexpected file type or owner: ' + path.name)
    return path.read_bytes()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fingerprint(files):
    return digest(b'\0'.join(n.encode() + b'\0' + files[n] for n in RUNTIME))


def git_file(repo, revision, name):
    raw = subprocess.check_output(['git', '-C', str(repo), 'show', revision + ':' + name], timeout=30)
    if not raw or len(raw) > 1_000_000:
        raise RuntimeError('Pinned file is empty or too large: ' + name)
    return raw


def atomic(path, data, mode=0o600):
    if path.is_symlink():
        raise RuntimeError('Refusing symlink: ' + path.name)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0 or not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        raise RuntimeError('Run as the publisher user with an exact revision.')
    os.umask(0o077)
    home, repo = Path.home(), args.repo.resolve()
    if shutil.disk_usage(home).free < 256 * 1024 * 1024:
        raise RuntimeError('At least 256 MiB free is required.')
    meta_path = home / '.local/state/kiani-instagram-insights/activation.json'
    old_meta = owned(meta_path)
    meta = json.loads(old_meta)
    if meta.get('news_runtime_revision') != BASE or meta.get('hourly_news_enabled') is not True:
        raise RuntimeError('Automatic news revision differs; inspect before updating.')
    old_root = home / 'kiani-instagram-ranked-news-releases' / BASE
    old_hashes = meta.get('news_source_hashes')
    if not isinstance(old_hashes, dict) or set(old_hashes) != set(FILES):
        raise RuntimeError('Automatic news source list differs.')
    files = {}
    for name in FILES:
        raw = owned(old_root / name)
        revision, source_name = base_spec(name)
        pinned = git_file(repo, revision, source_name)
        if raw != pinned or digest(raw) != old_hashes[name]:
            raise RuntimeError('Installed automatic news file differs: ' + name)
        files[name] = raw
    if meta.get('news_template', {}).get('runtime_hash') != fingerprint(files):
        raise RuntimeError('Installed automatic news runtime fingerprint differs.')
    files['instagram_ranked_news.py'] = git_file(repo, args.revision, WORKER)
    test = git_file(repo, args.revision, TEST)
    compile(files['instagram_ranked_news.py'], WORKER, 'exec')
    with tempfile.TemporaryDirectory(prefix='kiani-news-fallback-') as tmp:
        folder = Path(tmp)
        (folder / 'automatic_ranked_news_images.py').write_bytes(files['instagram_ranked_news.py'])
        (folder / 'test_image_fallback.py').write_bytes(test)
        subprocess.run([str(home / 'kiani-instagram-venv/bin/python'),
                        str(folder / 'test_image_fallback.py')], check=True, timeout=60)
    print('Offline fallback preflight passed; no model or Instagram request made.')
    if not args.install:
        return
    wrappers = [home / 'publish-kiani-instagram-news.sh',
                home / 'publish-kiani-instagram-economy.sh']
    before = {p: (owned(p), stat.S_IMODE(p.stat().st_mode)) for p in wrappers}
    new_root = home / 'kiani-instagram-ranked-news-releases' / args.revision
    old_ref = str(old_root / 'instagram_ranked_news.py').encode()
    new_ref = str(new_root / 'instagram_ranked_news.py').encode()
    replacements = {}
    for index, path in enumerate(wrappers):
        raw = before[path][0]
        if raw.count(old_ref) != (1 if index == 0 else 2):
            raise RuntimeError('Automatic news launcher differs: ' + path.name)
        replacements[path] = raw.replace(old_ref, new_ref)
        subprocess.run(['bash', '-n'], input=replacements[path], check=True, timeout=15)
    cron = subprocess.check_output(['crontab', '-l'], timeout=15)
    locks = [meta_path.parent / 'collector.lock',
             home / '.local/state/kiani-instagram-news-ranking/selection.lock',
             home / '.local/state/kiani-instagram-news-ranking/crypto.collection.lock',
             home / '.local/state/kiani-instagram-news-ranking/economy.collection.lock',
             home / '.local/state/kiani-instagram-news/news.sqlite3.lock',
             home / '.local/state/kiani-instagram-news/publisher.lock',
             home / '.local/state/kiani-instagram-economy/economy.sqlite3.lock']
    with ExitStack() as stack:
        for path in sorted(locks):
            if path.is_symlink():
                raise RuntimeError('Unsafe lock file.')
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            handle = stack.enter_context(path.open('a'))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('News worker is busy; retry shortly.') from None
        if (owned(meta_path) != old_meta or
                any(owned(p) != before[p][0] for p in wrappers) or
                subprocess.check_output(['crontab', '-l'], timeout=15) != cron):
            raise RuntimeError('News configuration changed during preflight.')
        for name in FILES:
            raw = owned(old_root / name)
            if digest(raw) != old_hashes[name]:
                raise RuntimeError('Installed release changed during preflight: ' + name)
            path = new_root / name
            if path.is_symlink() or path.exists() and owned(path) != files[name]:
                raise RuntimeError('Conflicting file in new release: ' + name)
            if not path.exists():
                atomic(path, files[name])
        backup = Path(tempfile.mkdtemp(prefix='kiani-auto-news-fallback-backup-', dir=home))
        atomic(backup / 'activation.json', old_meta)
        atomic(backup / 'crontab.txt', cron)
        for path, (raw, mode) in before.items():
            atomic(backup / path.name, raw, mode)
        template = dict(meta.get('news_template') or {}, revision=args.revision,
                        previous_news_runtime_revision=BASE,
                        runtime_hash=fingerprint(files), activated_at=time.time(), backup=str(backup))
        updated = dict(meta, news_runtime_revision=args.revision,
                       news_source_hashes={name: digest(files[name]) for name in FILES},
                       news_template=template)
        proposed = (json.dumps(updated, indent=2) + '\n').encode()
        try:
            for path, raw in replacements.items():
                atomic(path, raw, before[path][1])
            atomic(meta_path, proposed)
            if subprocess.check_output(['crontab', '-l'], timeout=15) != cron:
                raise RuntimeError('Crontab changed during installation.')
        except BaseException:
            for path, (raw, mode) in before.items():
                if path.exists() and owned(path) == replacements[path]:
                    atomic(path, raw, mode)
            if meta_path.exists() and owned(meta_path) == proposed:
                atomic(meta_path, old_meta)
            print('Installation incomplete; backup:', backup, flush=True)
            raise
    print('Automatic news fallback installed:', args.revision)
    print('Up to three eligible stories are tried when images are unavailable.')
    print('Two images, existing schedules, quota, source and retention rules preserved.')
    print('Backup:', backup)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('Automatic news fallback stopped:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
        raise SystemExit(1)
