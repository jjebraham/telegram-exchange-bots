#!/usr/bin/env python3
"""Switch only the existing hourly-news runtime to the approved readable layout."""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

BASE_REVISION = '4745d848a1253b5c3ec39bf86a723b4c560ff8cd'
LAYOUT_VERSION = 'kiani-news-carousel-b-v1'
NEWS_HASHES = {
    'instagram_ranked_news.py': 'ff6bb72303f9fdf6d12327ba7f89596ca1cb20042b97fcb510495d9ffcf4f5e4',
    'crypto_news_trial.py': '692727b42f090d00334df0ee152fa553ecb6e599fc7e3071b327157670fe0deb',
    'instagram_news_batch.py': 'a140e1e6248242b36dcfc5af511599e259dbff7477f1e24026242a13d678a2c7',
    'instagram_insights_data.py': 'f315a331626ab0cb5565eaa62a836023c873e21b9b13104382d4e609b8f59219',
    'selector_trial_runtime/economy_news_picker.py': '1624ab9f37fd052b9c0c43e7ff3bc12c72197e31bdd7d6a7e8171edf36dbfe24',
    'selector_trial_runtime/economy_news_translation.py': 'a1621eb88e4a6d6c43d2bd010f91da879c5059da2410ace7b4a2a195b7c94edc',
    'selector_trial_runtime/instagram_crypto_news.py': 'e4e7de231022170cceece1e7ad0eb1d7be6eb59e423ad0b60caeb7cd9c243063',
    'selector_trial_runtime/instagram_news_renderer.py': '1d85b5d140b11d88997c1b523bf761fec306fef3641776d9d633dd33ca258e5c',
    'selector_trial_runtime/PINNED.md': '8cb6dc1d31b569beb9b22a9cee678f4a01459fbf413857b23b0d64dee613a339',
}
ANALYTICS_HASHES = {
    'instagram_insights_data.py': 'f315a331626ab0cb5565eaa62a836023c873e21b9b13104382d4e609b8f59219',
    'instagram_post_insights.py': '58cca39bf07151927de58a0fa128bf218d721f4f10f0d910e89beb61ce2a826f',
    'instagram_news_retention.py': 'b5dab891f550061f8dbce1cbe49db2c75ffe6cc6b7230080de25bc9c1c450e40',
}
ASSETS = ('assets/instagram/kiani-logo.svg', 'fonts/Vazirmatn-Regular.ttf', 'fonts/Vazirmatn-Bold.ttf')
RUNTIME = tuple(n for n in NEWS_HASHES if n != 'selector_trial_runtime/PINNED.md')
PUBLIC = Path('/var/www/peerexo.com/public/instagram-rates/ranked-news-preview')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def owned(path, private=False):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
        raise RuntimeError('Expected a publisher-owned regular file: ' + str(path))
    if private and path.stat().st_mode & 0o077:
        raise RuntimeError('Private file permissions need review: ' + str(path))
    return path.read_bytes()


def fingerprint(root, names):
    return sha(b'\0'.join(n.encode()+b'\0'+owned(root/n) for n in names))


def atomic(path, raw, mode=0o600):
    if path.is_symlink():
        raise RuntimeError('Refusing a symlink installation target.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cron():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def hourly_wrappers(home, runtime):
    python = shlex.quote(str(home / 'kiani-instagram-venv/bin/python'))
    script = shlex.quote(str(runtime / 'instagram_ranked_news.py'))
    header = '''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export TZ=Europe/Istanbul
export PYTHONIOENCODING=utf-8
umask 077
action="${1:-publish}"
case "$action" in
'''
    outputs = {}
    for kind, filename in (('crypto', 'publish-kiani-instagram-news.sh'), ('economy', 'publish-kiani-instagram-economy.sh')):
        text = header
        if kind == 'economy':
            text += f'  collect) exec {python} -u {script} --kind economy --collect-only ;;\n'
        text += '''  publish) slot="hour-$(date +%H)" ;;
  *) echo "Usage: publish''' + ('|collect' if kind == 'economy' else '') + '''" >&2; exit 2 ;;
esac
set -a
. "$HOME/.kiani-instagram.env"
set +a
'''
        text += f'exec {python} -u {script} --kind {kind} --slot "$slot" --publish\n'
        outputs[home / filename] = text.encode()
    return outputs


def preview_proof(home, source, assets, kind):
    from PIL import Image
    expected = fingerprint(source, RUNTIME)
    assets_hash = fingerprint(assets, ASSETS)
    runs = home / '.local/state/kiani-instagram-news-ranking/runs'
    reports = sorted(runs.glob(kind+'-*/ranking.json'), key=lambda p:p.stat().st_mtime, reverse=True)[:80]
    for report in reports:
        audit = json.loads(owned(report, private=True))
        selected = audit.get('selected_at', 0)
        if (audit.get('status') != 'previewed' or audit.get('kind') != kind or
                audit.get('runtime_fingerprint') != expected or
                not time.time()-86400 <= selected <= time.time()+5 or
                len(audit.get('chosen_ids', [])) != 1 or audit.get('media_ids')):
            continue
        urls = audit.get('preview_urls') or []
        if not 2 <= len(urls) <= 10:
            continue
        files = []
        for url in urls:
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or parsed.netloc != 'peerexo.com' or parsed.query or parsed.fragment or
                    parsed.path != '/instagram-rates/ranked-news-preview/'+kind+'/'+Path(parsed.path).name):
                raise RuntimeError('Unexpected preview media URL.')
            path = PUBLIC / kind / Path(parsed.path).name
            owned(path)
            with Image.open(path) as image:
                if image.format != 'JPEG' or image.size != (1080, 1350):
                    raise RuntimeError('Preview image dimensions/format differ.')
                image.verify()
            files.append(path)
        first = files[0].name
        if not first.endswith('-01.jpg'):
            raise RuntimeError('The first news slide is not the cover.')
        manifest = json.loads(owned(files[0].parent/(first[:-7]+'.json')))
        body = manifest.get('body_pages', [])
        summary = manifest.get('summary_normalized', '')
        if (manifest.get('layout_version') != LAYOUT_VERSION or manifest.get('body_font_px') != 64 or
                manifest.get('text_complete') is not True or manifest.get('assets_fingerprint') != assets_hash or
                manifest.get('slides') != [p.name for p in files] or len(body) != len(files)-1 or
                len(manifest.get('stories', [])) != 1 or not summary or
                sha(summary.encode()) != manifest.get('summary_sha256')):
            raise RuntimeError('Preview layout, source-text or asset proof differs.')
        if re.sub(r'\s+', ' ', manifest['stories'][0]['summary_fa']).strip() != summary:
            raise RuntimeError('Preview summary differs from the verified translation.')
        if ''.join(p.get('separator_before', '')+p['text'] for p in body) != summary:
            raise RuntimeError('The preview did not preserve the complete summary.')
        if any(not 1 <= len(p.get('lines', [])) <= 7 for p in body):
            raise RuntimeError('A large-type page exceeds its line limit.')
        return dict(report=str(report), slides=len(files), hero=manifest.get('hero_available'), runtime_hash=expected)
    raise RuntimeError('A successful new-runtime '+kind+' preview within 24 hours is required; run the preview first.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Use the pinned revision as the existing publisher user, without sudo.')
    os.umask(0o077)
    home, source = Path.home(), args.runtime.resolve()
    assets = home / 'kiani-instagram-publisher'
    for name in NEWS_HASHES:
        if name.endswith('.py'):
            ast.parse(owned(source/name).decode('utf-8'), filename=name, feature_version=(3,11))
        if name not in {'selector_trial_runtime/instagram_news_renderer.py', 'selector_trial_runtime/PINNED.md'}:
            if sha(owned(source/name)) != NEWS_HASHES[name]:
                raise RuntimeError('This style upgrade may not change selection, quota or publishing logic: '+name)
    proofs = {kind:preview_proof(home, source, assets, kind) for kind in ('crypto', 'economy')}
    initial_cron = cron()
    expected_jobs = {
        f'15 * * * * {home}/publish-kiani-instagram-economy.sh collect >> {home}/kiani-instagram-economy-cron.log 2>&1',
        f'0 7-16 * * * {home}/publish-kiani-instagram-news.sh publish >> {home}/kiani-instagram-news-cron.log 2>&1',
        f'30 7-16 * * * {home}/publish-kiani-instagram-economy.sh publish >> {home}/kiani-instagram-economy-cron.log 2>&1',
    }
    jobs = [line.strip() for line in initial_cron.decode().splitlines()
            if not line.lstrip().startswith('#') and any(n in line for n in
                ('publish-kiani-instagram-news.sh', 'publish-kiani-instagram-economy.sh'))]
    if len(jobs) != 3 or set(jobs) != expected_jobs:
        raise RuntimeError('The confirmed hourly-news schedules differ; nothing replaced.')
    for line in initial_cron.decode().splitlines():
        if line.strip().startswith('CRON_TZ=') and line.split('=',1)[1].strip().strip('\"\'') not in {'UTC','Etc/UTC','GMT','Etc/GMT',''}:
            raise RuntimeError('A non-UTC crontab timezone needs review.')
    zone = subprocess.check_output(['timedatectl','show','--property=Timezone','--value'], text=True, timeout=15).strip()
    if zone not in {'UTC','Etc/UTC','GMT','Etc/GMT'} or subprocess.run(['systemctl','is-active','--quiet','cron'], timeout=15).returncode:
        raise RuntimeError('The existing active UTC cron service is required.')
    meta_path = home / '.local/state/kiani-instagram-insights/activation.json'
    old_meta = owned(meta_path, private=True)
    meta = json.loads(old_meta)
    if meta.get('revision') != BASE_REVISION:
        raise RuntimeError('The installed analytics revision differs from the confirmed weekly-market deployment.')
    if (meta.get('hourly_news_enabled') is not True or meta.get('news_schedule', {}).get('per_slot') != 1 or
            meta.get('news_schedule', {}).get('per_category_day') != 10 or
            meta.get('news_schedule', {}).get('timezone') != 'Europe/Istanbul' or
            meta.get('policy', {}).get('assessment_hours') != 2 or
            meta.get('policy', {}).get('keep_at_or_above_views') != 200):
        raise RuntimeError('The confirmed hourly or retention policy differs; nothing replaced.')
    analytics = home / 'kiani-instagram-insights-releases' / BASE_REVISION
    analytics_before = {analytics/n:owned(analytics/n) for n in ANALYTICS_HASHES}
    if any(sha(raw) != ANALYTICS_HASHES[p.name] for p,raw in analytics_before.items()) or fingerprint(analytics, ANALYTICS_HASHES) != meta.get('runtime_hash'):
        raise RuntimeError('The existing analytics/retention runtime differs; nothing replaced.')
    old_revision = meta.get('news_runtime_revision')
    if old_revision not in {BASE_REVISION, args.revision}:
        raise RuntimeError('An unreviewed hourly-news version is installed.')
    old_root = home / 'kiani-instagram-ranked-news-releases' / old_revision
    new_root = home / 'kiani-instagram-ranked-news-releases' / args.revision
    news_before = {old_root/n:owned(old_root/n) for n in NEWS_HASHES}
    for name, expected in NEWS_HASHES.items():
        raw = news_before[old_root/name]
        if old_revision == BASE_REVISION and sha(raw) != expected or old_revision == args.revision and raw != owned(source/name):
            raise RuntimeError('An installed hourly-news source differs: '+name)
    old_wrappers = hourly_wrappers(home, old_root)
    replacements = hourly_wrappers(home, new_root)
    before = {p:(owned(p),p.stat().st_mode&0o777) for p in old_wrappers}
    if any(before[p][0] != expected for p,expected in old_wrappers.items()):
        raise RuntimeError('An hourly-news launcher differs from its reviewed layout.')
    for raw in replacements.values():
        subprocess.run(['bash','-n'], input=raw, check=True, timeout=15)
    config_path = home / '.local/state/kiani-instagram-stories/config.json'
    original_config = owned(config_path, private=True)
    config = json.loads(original_config)
    if (config.get('sources', {}).get('crypto') != str(home/'.local/state/kiani-instagram-news/news.sqlite3') or
            config.get('sources', {}).get('economy') != str(home/'.local/state/kiani-instagram-economy/economy.sqlite3')):
        raise RuntimeError('The existing news Story registrations differ.')
    for name in NEWS_HASHES:
        target, raw = new_root/name, owned(source/name)
        if target.is_symlink() or target.exists() and owned(target) != raw:
            raise RuntimeError('An existing immutable news release differs: '+name)
        if not target.exists():
            atomic(target, raw)
    with ExitStack() as stack:
        paths = [meta_path.parent/'collector.lock',
                 home/'.local/state/kiani-instagram-news-ranking/selection.lock',
                 home/'.local/state/kiani-instagram-news-ranking/crypto.collection.lock',
                 home/'.local/state/kiani-instagram-news-ranking/economy.collection.lock',
                 home/'.local/state/kiani-instagram-news/news.sqlite3.lock',
                 home/'.local/state/kiani-instagram-news/publisher.lock',
                 home/'.local/state/kiani-instagram-economy/economy.sqlite3.lock']
        for path in sorted(paths):
            if path.is_symlink():
                raise RuntimeError('Refusing a symlink worker lock.')
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            handle = stack.enter_context(path.open('a'))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('A news or insights worker is active; retry activation when it finishes.') from None
        if (cron() != initial_cron or owned(meta_path) != old_meta or owned(config_path) != original_config or
                any(owned(p) != raw for p,raw in news_before.items()) or
                any(owned(p) != raw for p,raw in analytics_before.items()) or
                any(owned(p) != prior[0] for p,prior in before.items())):
            raise RuntimeError('Installed files changed during preparation; nothing replaced.')
        assets_hash = fingerprint(assets, ASSETS)
        proofs = {kind:preview_proof(home, source, assets, kind) for kind in ('crypto','economy')}
        backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-news-carousel-backup-', dir=home))
        atomic(backup/'activation.json', old_meta)
        atomic(backup/'crontab.txt', initial_cron)
        for path,(raw,mode) in before.items():
            atomic(backup/path.name, raw, mode)
        new_meta = dict(meta, news_runtime_revision=args.revision,
                        news_source_hashes={name:sha(owned(source/name)) for name in NEWS_HASHES},
                        news_template=dict(revision=args.revision, layout_version=LAYOUT_VERSION,
                            body_font_px=64, activated_at=time.time(), backup=str(backup),
                            previous_news_runtime_revision=old_revision,
                            runtime_hash=fingerprint(source,RUNTIME), previews=proofs))
        proposed_meta = json.dumps(new_meta, indent=2).encode()
        try:
            for path, raw in replacements.items():
                atomic(path, raw, before[path][1])
            atomic(meta_path, proposed_meta)
            if (cron() != initial_cron or owned(config_path) != original_config or
                    fingerprint(assets, ASSETS) != assets_hash or
                    any(owned(p) != raw for p,raw in analytics_before.items())):
                raise RuntimeError('A preserved schedule, asset or worker changed during activation.')
        except BaseException:
            for path,raw in replacements.items():
                if owned(path) == raw:
                    atomic(path, *before[path])
            if owned(meta_path) == proposed_meta:
                atomic(meta_path, old_meta)
            print('Activation incomplete. Backup:', backup, file=sys.stderr)
            raise
    print('Backup:', backup)
    print('Installed readable-news revision:', args.revision)
    print('Crypto and economy: photo/headline cover, swipe-left prompt, then complete 64px text pages.')
    print('Slide count adapts to summary length, maximum ten; no shrinking or truncation.')
    print('Istanbul slots: crypto 10:00-19:00 hourly; economy 10:30-19:30 hourly; one Feed/slot, ten/category/day.')
    print('Story: one cover preview, 30 minutes after successful Feed publication.')
    print('News retention preserved: below 200 Views at two hours, with original checks/enrollment/decisions.')
    print('Analytics, source ranking, quota reservations, databases, other publishers and schedules preserved.')
    print('Activation complete. No immediate Instagram post or deletion was performed.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('News carousel activation stopped:', str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
