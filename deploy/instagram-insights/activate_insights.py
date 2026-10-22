#!/usr/bin/env python3
"""Activate analytics/news policies only after real access and permission checks."""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack
from datetime import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

BEGIN, END = '# BEGIN Kiani Instagram insights', '# END Kiani Instagram insights'
OLD_REVISION = '8f270cff3f40d56ea85b68e4c3b69497cf641dd3'
OLD_HASH = '9f856ef182cb265290714595c1c0153a7233caa43e05a7f68f282cb6a0165cb3'
OLD_ANALYTICS_HASH = 'c5314a04ef818856ed85144301357305cf527e206185dfd08afbeda76d5f1c37'
NEWS_BEGIN, NEWS_END = '# BEGIN Kiani hourly news v1', '# END Kiani hourly news v1'


def cron():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def release(app, source, target, names):
    for name in names:
        path, content = target / name, (source / name).read_bytes()
        if path.is_symlink() or path.exists() and path.read_bytes() != content:
            raise RuntimeError('An existing immutable release differs; no overwrite performed.')
        if not path.exists():
            app.atomic(path, content)


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


def hourly_cron(original, home):
    """Replace exactly the deployed four news jobs, preserving unrelated jobs."""
    paths = {str(home / 'publish-kiani-instagram-news.sh'): 'crypto',
             str(home / 'publish-kiani-instagram-economy.sh'): 'economy'}
    expected = {('crypto', 'first'): '0 15 * * *', ('crypto', 'second'): '30 18 * * *',
                ('economy', 'first'): '0 10 * * *', ('economy', 'second'): '0 17 * * *',
                ('economy', 'collect'): '30 * * * *'}
    upgraded = {('crypto', 'publish'): '0 7-16 * * *', ('economy', 'publish'): '30 7-16 * * *',
                ('economy', 'collect'): '15 * * * *'}
    seen, kept = {}, []
    for line in original.decode().splitlines():
        stripped = line.strip()
        if stripped in {NEWS_BEGIN, NEWS_END, '# BEGIN Kiani ranked news v2', '# END Kiani ranked news v2'}:
            continue
        if stripped.startswith('CRON_TZ=') and stripped.split('=', 1)[1].strip('"\'') not in {'UTC', 'Etc/UTC'}:
            raise RuntimeError('A non-UTC CRON_TZ requires review before hourly scheduling.')
        if not stripped or stripped.startswith('#') or not any(path in line for path in paths):
            kept.append(line)
            continue
        fields = stripped.split(None, 5)
        if len(fields) != 6:
            raise RuntimeError('Unexpected existing news cron format.')
        command = shlex.split(fields[5])
        if len(command) < 4 or command[0] not in paths:
            raise RuntimeError('Indirect or incomplete news command needs review.')
        kind = paths[command[0]]
        explicit = command[1] not in {'>>', '>'}
        action = command[1] if explicit else 'first'
        key = (kind, action)
        log = home / ('kiani-instagram-news-cron.log' if kind == 'crypto' else 'kiani-instagram-economy-cron.log')
        if command[2 if explicit else 1:] != ['>>', str(log), '2>&1'] or key in seen:
            raise RuntimeError('A news cron command changed or is duplicated; nothing replaced.')
        seen[key] = ' '.join(fields[:5])
    if seen not in (expected, upgraded):
        raise RuntimeError('Existing news schedules differ from the reviewed four-slot or hourly setup.')
    crypto, economy = home / 'publish-kiani-instagram-news.sh', home / 'publish-kiani-instagram-economy.sh'
    block = [NEWS_BEGIN,
        f'15 * * * * {economy} collect >> {home}/kiani-instagram-economy-cron.log 2>&1',
        f'0 7-16 * * * {crypto} publish >> {home}/kiani-instagram-news-cron.log 2>&1',
        f'30 7-16 * * * {economy} publish >> {home}/kiani-instagram-economy-cron.log 2>&1', NEWS_END]
    return ('\n'.join(kept).rstrip() + '\n\n' + '\n'.join(block) + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--news-batch', action='store_true')
    parser.add_argument('--news-retention', action='store_true')
    args = parser.parse_args()
    if not (args.news_batch and args.news_retention):
        parser.error('This correction requires --news-batch and --news-retention together to avoid mixing schedules and policy versions.')
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('Run as the publisher user without sudo, using the reviewed revision.')
    home, root = Path.home(), args.runtime.resolve()
    sys.path.insert(0, str(root))
    import instagram_post_insights as app
    import instagram_insights_data as data
    from instagram_news_retention import permission_proof
    for name in {*data.RUNTIME, *data.NEWS_RUNTIME}:
        if name.endswith('.py'):
            ast.parse((root / name).read_text(encoding='utf-8'), filename=name)
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=15).returncode:
        raise RuntimeError('The existing cron service is not active.')
    zone = subprocess.check_output(['timedatectl', 'show', '--property=Timezone', '--value'], text=True, timeout=15).strip()
    if zone not in {'UTC', 'Etc/UTC'} or datetime.now(ZoneInfo('Europe/Istanbul')).utcoffset().total_seconds() != 10800:
        raise RuntimeError('Server timezone differs from the reviewed UTC/Istanbul schedule.')
    graph = data.Graph()  # Configuration validation; no network request.
    launcher, config_path = home / 'collect-kiani-instagram-insights.sh', data.STATE / 'activation.json'
    config_hash = hashlib.sha256(data.private_file(data.STORY_CONFIG).read_bytes()).hexdigest()
    with ExitStack() as locks:
        locks.enter_context(app.locked(data.STATE / 'collector.lock'))
        if args.news_batch:
            for path in sorted((home / '.local/state/kiani-instagram-news-ranking/selection.lock',
                home / '.local/state/kiani-instagram-news/news.sqlite3.lock',
                home / '.local/state/kiani-instagram-news/publisher.lock',
                home / '.local/state/kiani-instagram-economy/economy.sqlite3.lock')):
                handle = locks.enter_context(path.open('a'))
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError('A news publisher is busy; retry after it finishes.') from None
        con = data.database(data.STATE / 'insights.sqlite3')
        try:
            probe = data.setting(con, 'probe')
            if (not isinstance(probe, dict) or probe.get('runtime_hash') != data.fingerprint(root) or
                probe.get('account_id') != graph.account_id or probe.get('api_version') != graph.version or
                probe.get('source_config_hash') != config_hash or not probe.get('media_ids') or
                not time.time() - 86400 <= probe.get('verified_at', 0) <= time.time()):
                raise RuntimeError('Run a successful views/reach probe from this exact revision/account/configuration first.')
            if args.news_retention:
                proof = permission_proof(con, graph)
                if not time.time() - 86400 <= proof.get('verified_at', 0) <= time.time():
                    raise RuntimeError('Run the read-only current-token permission audit first.')
                if data.setting(con, 'retention_paused'):
                    raise RuntimeError('An uncertain earlier deletion needs reconciliation; activation cannot clear it.')
                if data.setting(con, 'default_exposure') != 'organic':
                    raise RuntimeError('Record the owner\'s organic declaration in the initial probe.')
            app_root = home / 'kiani-instagram-insights-releases' / args.revision
            release(app, root, app_root, data.RUNTIME)
            python = home / 'kiani-instagram-venv/bin/python'
            wrapper = '''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export PYTHONIOENCODING=utf-8
export TZ=Asia/Tehran
umask 077
action="${1:-report}"
if [ "$#" -gt 0 ]; then shift; fi
case "$action" in
  run|probe) set -a; . "$HOME/.kiani-instagram.env"; set +a ;;
  report|keep|organic|promoted) ;;
  *) echo "Usage: run|probe|report|keep MEDIA_ID|organic MEDIA_ID|promoted MEDIA_ID" >&2; exit 2 ;;
esac
''' + 'exec ' + shlex.quote(str(python)) + ' -u ' + shlex.quote(str(app_root / 'instagram_post_insights.py')) + ' "--$action" "$@"\n'
            prior = json.loads(config_path.read_text()) if config_path.is_file() else {}
            known_install = ((prior.get('revision') == OLD_REVISION and prior.get('news_batch_enabled') is True) or
                             (prior.get('revision') == args.revision and prior.get('hourly_news_enabled') is True))
            if not known_install or prior.get('news_retention_enabled') is not True:
                raise RuntimeError('Expected the confirmed PR66 installation; review the installed configuration first.')
            old_analytics = home / 'kiani-instagram-insights-releases' / OLD_REVISION
            if data.fingerprint(old_analytics) != OLD_ANALYTICS_HASH:
                raise RuntimeError('Installed analytics source differs from the reviewed PR66 release.')
            old_wrapper = wrapper.replace(str(app_root / 'instagram_post_insights.py'), str(old_analytics / 'instagram_post_insights.py')).encode()
            if data.private_file(launcher).read_bytes() not in {old_wrapper, wrapper.encode()}:
                raise RuntimeError('Installed analytics launcher differs from the reviewed release.')
            metadata = dict(revision=args.revision, activated_at=time.time(), runtime_hash=data.fingerprint(root),
                account_id=graph.account_id, api_version=graph.version, probe=probe, policy=app.POLICY,
                news_schedule=dict(timezone='Europe/Istanbul', crypto='10:00-19:00 hourly', economy='10:30-19:30 hourly', per_slot=1, per_category_day=10),
                # The legacy worker rechecks this flag at its final publish
                # boundary. Disable its burst mode even if an old job resumes.
                news_batch_enabled=False, hourly_news_enabled=True,
                news_retention_enabled=args.news_retention or data.setting(con, 'retention_enabled', False))
            changed = {launcher: (wrapper.encode(), 0o700), config_path: (json.dumps(metadata, indent=2).encode(), 0o600)}
            if args.news_batch:
                quota = probe.get('publishing_quota', {})
                if not quota.get('total') or quota.get('duration') != 86400:
                    raise RuntimeError('Actual rolling publishing quota was not verified.')
                old_root = home / 'kiani-instagram-ranked-news-releases' / OLD_REVISION
                if hashlib.sha256((old_root / 'instagram_ranked_news.py').read_bytes()).hexdigest() != OLD_HASH:
                    raise RuntimeError('Installed news source differs from the reviewed revision; nothing replaced.')
                spec = importlib.util.spec_from_file_location('kiani_old_news_setup', root / 'deploy/instagram-news/activate_ranked_news.py')
                previous = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(previous)
                news_root = home / 'kiani-instagram-ranked-news-releases' / args.revision
                release(app, root, news_root, data.NEWS_RUNTIME)
                expected, proposed = previous.wrappers(home, old_root), hourly_wrappers(home, news_root)
                for path, content in proposed.items():
                    if data.private_file(path).read_bytes() not in {expected[path], content}:
                        raise RuntimeError('A news launcher differs from the reviewed setup; nothing replaced.')
                    changed[path] = content, path.stat().st_mode & 0o777
            before = {}
            for path in changed:
                if path.is_symlink() or path.exists() and path.stat().st_uid != os.getuid():
                    raise RuntimeError('An installation path is a symlink or has an unexpected owner.')
                before[path] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
            keys = ('retention_enabled', 'retention_enrolled_after', 'retention_policy')
            old_settings = {key: con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone() for key in keys}
            old_policy = data.setting(con, 'retention_policy')
            if not isinstance(old_policy, dict) or old_policy.get('version') not in {2, 3}:
                raise RuntimeError('Existing retention policy needs review before migration.')
            original = cron()
            command = f'7,22,37,52 * * * * {launcher} run >> {home}/kiani-instagram-insights-cron.log 2>&1'
            kept = []
            for line in hourly_cron(original, home).decode().splitlines():
                stripped = line.strip()
                if stripped in {BEGIN, END}:
                    continue
                if str(launcher) in line and not stripped.startswith('#'):
                    if stripped != command:
                        raise RuntimeError('An existing analytics cron entry differs.')
                    continue
                kept.append(line)
            replacement = ('\n'.join(kept).rstrip() + '\n\n' + BEGIN + '\n' + command + '\n' + END + '\n').encode()
            backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-insights-backup-', dir=home))
            (backup / 'crontab.txt').write_bytes(original)
            (backup / 'paths.json').write_text(json.dumps([str(p) for p in before]))
            (backup / 'settings.json').write_text(json.dumps({key: row[0] if row else None for key, row in old_settings.items()}))
            for i, old in enumerate(before.values()):
                if old:
                    (backup / str(i)).write_bytes(old[0])
            try:
                if cron() != original or hashlib.sha256(data.STORY_CONFIG.read_bytes()).hexdigest() != config_hash:
                    raise RuntimeError('Schedules or source configuration changed during preparation.')
                if any(path.exists() != bool(old) or old and path.read_bytes() != old[0] for path, old in before.items()):
                    raise RuntimeError('An installation file changed during preparation.')
                for path, (content, mode) in changed.items():
                    app.atomic(path, content, mode)
                if cron() != original:
                    raise RuntimeError('Schedules changed during installation.')
                subprocess.run(['crontab', '-'], input=replacement, timeout=15, check=True, capture_output=True)
                if cron() != replacement:
                    raise RuntimeError('Installed analytics schedule did not match.')
                if args.news_retention:
                    with con:
                        con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('retention_enabled', 'true'))
                        if data.setting(con, 'retention_enrolled_after') is None or old_policy != app.POLICY:
                            con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('retention_enrolled_after', json.dumps(time.time())))
                        con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('retention_policy', json.dumps(app.POLICY)))
            except BaseException:
                for path, old in before.items():
                    if path.exists() and path.read_bytes() == changed[path][0]:
                        if old:
                            app.atomic(path, *old)
                        else:
                            path.unlink()
                if cron() == replacement:
                    subprocess.run(['crontab', '-'], input=original, timeout=15, check=True, capture_output=True)
                with con:
                    for key, row in old_settings.items():
                        if row:
                            con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, row[0]))
                        else:
                            con.execute('DELETE FROM settings WHERE key=?', (key,))
                print('Activation incomplete. Backup:', backup, file=sys.stderr)
                raise
        finally:
            con.close()
    print('Backup:', backup)
    print('Insights: every 15 minutes; checkpoints 2, 12 (news), 24, 48 and 72 hours. Missing data stays unknown.')
    if metadata['hourly_news_enabled']:
        cap = min(10, max(0, (probe['publishing_quota']['total'] - 12) // 4))
        print(f'News: ONE per hourly slot, at most TEN per category/day; current quota planning cap {cap}/category/day.')
        print('Istanbul crypto: 10:00 through 19:00 hourly. Economy: 10:30 through 19:30 hourly.')
        print('Hourly collection moved to minute 15; existing publications count toward today\'s cap. No missed-slot catch-up.')
    if metadata['news_retention_enabled']:
        print(f'NEW crypto/economy Feed only: keep >={app.MINIMUM} Views at TWO hours; below {app.MINIMUM} may be deleted after fresh rechecks.')
        print('Two-hour assessment window: 2:00-2:30 after actual publication; two low readings at least ten minutes apart.')
        print('Rate/gold/top 50/calendars protected. Missing metrics => keep. No historical deletion or replacement posts.')
    else:
        print('News deletion disabled; current-token permission audit and policy activation still required.')
    print('Other Feed/Story schedules and original publication history preserved.')
    print('Private report:', data.STATE / 'reports/latest.html')
    print('Analytics log:', home / 'kiani-instagram-insights-cron.log')
    print('Activation complete. No Instagram post published or deleted during installation.')
    return 0


if __name__ == '__main__':
    try:
        os.umask(0o077)
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
