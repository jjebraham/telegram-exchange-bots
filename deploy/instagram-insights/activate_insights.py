#!/usr/bin/env python3
"""Activate analytics/news policies only after real access and permission checks."""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack
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

BEGIN, END = '# BEGIN Kiani Instagram insights', '# END Kiani Instagram insights'
OLD_REVISION = 'ea6d9e4646e4dfc6e60e06b9bdad960c76befa6a'
OLD_HASH = '598218d915c66f759b62f88b8310db1e83ebaf7afdc0048f61c226d1d73032c0'


def cron():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def release(app, source, target, names):
    for name in names:
        path, content = target / name, (source / name).read_bytes()
        if path.is_symlink() or path.exists() and path.read_bytes() != content:
            raise RuntimeError('An existing immutable release differs; no overwrite performed.')
        if not path.exists():
            app.atomic(path, content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--news-batch', action='store_true')
    parser.add_argument('--news-retention', action='store_true')
    args = parser.parse_args()
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
            metadata = dict(revision=args.revision, activated_at=time.time(), runtime_hash=data.fingerprint(root),
                account_id=graph.account_id, api_version=graph.version, probe=probe, policy=app.POLICY,
                news_batch_enabled=args.news_batch or prior.get('news_batch_enabled', False),
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
                expected, proposed = previous.wrappers(home, old_root), previous.wrappers(home, news_root)
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
            original = cron()
            command = f'7,22,37,52 * * * * {launcher} run >> {home}/kiani-instagram-insights-cron.log 2>&1'
            kept = []
            for line in original.decode().splitlines():
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
                        if data.setting(con, 'retention_enrolled_after') is None:
                            con.execute('INSERT INTO settings VALUES (?,?)', ('retention_enrolled_after', json.dumps(time.time())))
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
    if metadata['news_batch_enabled']:
        cap = min(10, max(0, (probe['publishing_quota']['total'] - 12) // 8))
        print(f'News: up to 10/slot; current total quota permits at most {cap}/slot, with additional dynamic Story reservations.')
        print('Istanbul slots preserved: economy 13:00/20:00; crypto 18:00/21:30.')
    if metadata['news_retention_enabled']:
        print('NEW crypto/economy Feed only: keep >=400 Views at 12h; below 400 may be deleted after fresh rechecks.')
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
