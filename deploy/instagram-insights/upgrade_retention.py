#!/usr/bin/env python3
"""Upgrade the confirmed hourly news installation from 100 to 200 views only."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo
from datetime import datetime

OLD_REVISION = 'f59415f9ddb7a94541a1d36ecd456f9b63a57dda'
OLD_FINGERPRINT = '8b86b7323bd3b0d9b99c44abc1ec5556385d8cd344d1814de6017e90b51622de'


def wrapper(home, release):
    return ('''#!/bin/bash
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
''' + 'exec ' + shlex.quote(str(home / 'kiani-instagram-venv/bin/python')) + ' -u ' +
        shlex.quote(str(release / 'instagram_post_insights.py')) + ' "--$action" "$@"\n').encode()


def cron():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Run as the existing publisher user without sudo, with the reviewed revision.')
    os.umask(0o077)
    home, root = Path.home(), args.runtime.resolve()
    sys.path.insert(0, str(root))
    import instagram_insights_data as data
    import instagram_post_insights as app
    from instagram_news_retention import permission_proof, policy_matches
    old_policy = dict(app.POLICY, version=3, keep_at_or_above_views=100)
    if app.POLICY.get('version') != 4 or app.MINIMUM != 200:
        raise RuntimeError('Expected the reviewed two-hour/200-view policy version 4.')
    for name in data.RUNTIME:
        ast.parse((root / name).read_text(encoding='utf-8'), filename=name)
    graph = data.Graph()  # Local configuration validation only; no API request.
    state = data.STATE
    launcher, metadata_path = home / 'collect-kiani-instagram-insights.sh', state / 'activation.json'
    release_root = home / 'kiani-instagram-insights-releases' / args.revision
    legacy_root = home / 'kiani-instagram-insights-releases' / OLD_REVISION
    runtime_hash = data.fingerprint(root)
    for name in data.RUNTIME:
        data.private_file(legacy_root / name)
    if data.fingerprint(legacy_root) != OLD_FINGERPRINT:
        raise RuntimeError('Installed hourly analytics differs from the confirmed PR67 release.')
    with app.locked(state / 'collector.lock'):
        con = data.database(state / 'insights.sqlite3')
        try:
            original_metadata = data.private_file(metadata_path).read_bytes()
            prior = json.loads(original_metadata)
            original_launcher = data.private_file(launcher).read_bytes()
            original_policy = data.setting(con, 'retention_policy')
            same = prior.get('revision') == args.revision
            expected_revision = args.revision if same else OLD_REVISION
            expected_policy = app.POLICY if same else old_policy
            expected_root = release_root if same else legacy_root
            if (prior.get('revision') != expected_revision
                    or prior.get('hourly_news_enabled') is not True
                    or prior.get('news_retention_enabled') is not True
                    or prior.get('account_id') != graph.account_id
                    or prior.get('api_version') != graph.version
                    or prior.get('policy') != expected_policy
                    or original_policy != expected_policy
                    or original_launcher != wrapper(home, expected_root)
                    or prior.get('runtime_hash') != (runtime_hash if same else OLD_FINGERPRINT)):
                raise RuntimeError('Installed hourly launcher, policy or account differs; nothing changed.')
            if not data.setting(con, 'retention_enabled', False) or data.setting(con, 'retention_paused'):
                raise RuntimeError('Retention must already be active and not paused; an unresolved deletion cannot be cleared here.')
            permission_proof(con, graph)
            if data.setting(con, 'default_exposure') != 'organic':
                raise RuntimeError('The existing organic declaration is required.')
            cutoff = data.setting(con, 'retention_enrolled_after')
            if type(cutoff) not in {int, float} or not math.isfinite(cutoff) or not 0 < cutoff <= time.time():
                raise RuntimeError('Original news enrollment time is missing or invalid.')
            original_cron = cron()
            expected_job = f'7,22,37,52 * * * * {launcher} run >> {home}/kiani-instagram-insights-cron.log 2>&1'
            jobs = [line.strip() for line in original_cron.decode().splitlines()
                    if line.strip() and not line.lstrip().startswith('#') and str(launcher) in line]
            if jobs != [expected_job]:
                raise RuntimeError('Expected the existing every-15-minute analytics schedule.')
            protected_paths = (data.STORY_CONFIG, home / 'publish-kiani-instagram-news.sh',
                               home / 'publish-kiani-instagram-economy.sh')
            protected = {path: data.private_file(path).read_bytes() for path in protected_paths}
            probe = data.setting(con, 'probe')
            if (not isinstance(probe, dict) or probe.get('runtime_hash') != runtime_hash
                    or probe.get('account_id') != graph.account_id or probe.get('api_version') != graph.version
                    or probe.get('source_config_hash') != hashlib.sha256(protected[data.STORY_CONFIG]).hexdigest()
                    or not probe.get('media_ids')
                    or not time.time() - 86400 <= probe.get('verified_at', 0) <= time.time()):
                raise RuntimeError('Run a successful read-only insights probe from this exact revision first.')
            for name in data.RUNTIME:
                path, content = release_root / name, (root / name).read_bytes()
                if path.is_symlink() or path.exists() and path.read_bytes() != content:
                    raise RuntimeError('An immutable analytics release differs; nothing overwritten.')
                if not path.exists():
                    app.atomic(path, content)
            if data.fingerprint(release_root) != runtime_hash:
                raise RuntimeError('Installed new runtime fingerprint differs.')
            if same:
                print('The 200-view/two-hour news policy is already active; original enrollment and decisions preserved.')
                return 0
            replacement = wrapper(home, release_root)
            subprocess.run(['bash', '-n'], input=replacement, check=True, timeout=15)
            keys = ('retention_policy', 'retention_policy_changed_at')
            saved_settings = {key: con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone() for key in keys}
            changed_at = time.time()
            metadata = dict(prior, revision=args.revision, activated_at=changed_at,
                runtime_hash=runtime_hash, probe=probe, policy=app.POLICY,
                previous_insights_revision=prior['revision'],
                news_runtime_revision=prior.get('news_runtime_revision', prior['revision']),
                retention_policy_changed_at=changed_at)
            encoded_metadata = json.dumps(metadata, indent=2).encode()
            backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-retention-200-backup-', dir=home))
            app.atomic(backup / 'launcher.sh', original_launcher)
            app.atomic(backup / 'activation.json', original_metadata)
            app.atomic(backup / 'crontab.txt', original_cron)
            app.atomic(backup / 'settings.json', json.dumps({key: row[0] if row else None for key, row in saved_settings.items()}).encode())
            if (cron() != original_cron or launcher.read_bytes() != original_launcher
                    or metadata_path.read_bytes() != original_metadata
                    or any(path.read_bytes() != content for path, content in protected.items())
                    or data.setting(con, 'retention_policy') != old_policy
                    or data.setting(con, 'retention_enrolled_after') != cutoff
                    or data.setting(con, 'retention_paused')):
                raise RuntimeError('Installed configuration changed during preparation; nothing switched.')
            try:
                # The collector lock prevents any DELETE while runtime and policy
                # are switched. News launchers/crontab/publication history stay put.
                app.atomic(launcher, replacement, 0o700)
                app.atomic(metadata_path, encoded_metadata)
                with con:
                    con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('retention_policy', json.dumps(app.POLICY)))
                    con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('retention_policy_changed_at', json.dumps(changed_at)))
                if (not policy_matches(con) or data.setting(con, 'retention_enrolled_after') != cutoff
                        or cron() != original_cron
                        or any(path.read_bytes() != content for path, content in protected.items())):
                    raise RuntimeError('Policy or preserved schedule/configuration verification failed.')
            except BaseException:
                if launcher.read_bytes() == replacement:
                    app.atomic(launcher, original_launcher, 0o700)
                if metadata_path.read_bytes() == encoded_metadata:
                    app.atomic(metadata_path, original_metadata)
                with con:
                    for key, row in saved_settings.items():
                        if row:
                            con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, row[0]))
                        else:
                            con.execute('DELETE FROM settings WHERE key=?', (key,))
                print('Upgrade incomplete; rollback backup:', backup, file=sys.stderr)
                raise
        finally:
            con.close()
    print('Backup:', backup)
    print('Installed analytics revision:', args.revision)
    print('News rule: keep >=200 Views at TWO hours; below 200 requires two low readings at least ten minutes apart.')
    print('Assessment window: age 2:00 to before 2:30; final owner/Feed/Views verification required.')
    print('Pending and future assessments use 200. Completed decisions and the original enrollment cutoff are preserved.')
    print('Original enrollment:', datetime.fromtimestamp(cutoff, ZoneInfo('Europe/Istanbul')).isoformat())
    print('Rates, gold, top 50, calendars and Stories protected. Missing metrics => keep. No replacements.')
    print('Hourly news, all Feed/Story schedules, credentials and publication history preserved.')
    print('Activation complete. No Instagram post published or deleted during installation.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
