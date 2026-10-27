#!/usr/bin/env python3
"""Configure an admin-only Telegram news intake without altering existing schedules."""
from __future__ import annotations

import argparse
import fcntl
import getpass
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

BEGIN = '# BEGIN Kiani manual Instagram news v1'
END = '# END Kiani manual Instagram news v1'
ADMIN_ID = re.compile(r'^[0-9]{5,20}$')


def atomic(path, data, mode):
    if path.is_symlink():
        raise RuntimeError('Refusing a symlink installation path.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def owner_private(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise RuntimeError('A required private configuration is missing or has unsafe permissions.')


def private_directory(path):
    if path.is_symlink():
        raise RuntimeError('A private configuration directory is a symlink.')
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if not path.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('A private configuration directory has unsafe ownership or permissions.')


def valid_runtime(runtime):
    required = (
        'instagram_manual_news_intake.py', 'instagram_ranked_news.py',
        'crypto_news_trial.py', 'instagram_news_batch.py', 'instagram_insights_data.py',
        'instagram_news_retention.py', 'selector_trial_runtime/economy_news_picker.py',
        'selector_trial_runtime/economy_news_translation.py',
        'selector_trial_runtime/instagram_crypto_news.py',
        'selector_trial_runtime/instagram_news_renderer.py',
    )
    for name in required:
        path = runtime / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('A pinned manual-news runtime file is missing.')
    return required


def check_policies(runtime, home):
    sys.path.insert(0, str(runtime))
    sys.path.insert(0, str(runtime / 'selector_trial_runtime'))
    from instagram_insights_data import Graph, STATE as INSIGHTS_STATE, read_db, setting
    from instagram_news_batch import activation as news_activation
    from instagram_news_retention import MINIMUM, AGE, permission_proof, policy_matches

    policy_db = INSIGHTS_STATE / 'insights.sqlite3'
    if not policy_db.is_file() or policy_db.is_symlink():
        raise RuntimeError('The existing Instagram news-insights policy is missing.')
    graph = Graph()
    with read_db(policy_db) as con:
        if not setting(con, 'retention_enabled', False) or setting(con, 'retention_paused') or not policy_matches(con):
            raise RuntimeError('The existing two-hour, 200-view news-retention policy is not active.')
        permission_proof(con, graph)
    news_activation()
    from economy_news_translation import load_translation_env
    load_translation_env(home / 'sub/.env')
    if not os.getenv('DEEPSEEK_API_KEY', '').strip():
        raise RuntimeError('The existing private DeepSeek configuration is unavailable.')
    return AGE, MINIMUM


def existing_config(path):
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise RuntimeError('Existing Telegram bot configuration is not a private owner-owned file.')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise RuntimeError('Existing Telegram bot configuration cannot be read.') from None
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise RuntimeError('Existing Telegram bot configuration has an unsupported schema.')
    return value


def create_config(module, path, revision):
    private_directory(path.parent)
    prior = existing_config(path)
    if prior is not None:
        token, admins = module.private_json(path)
        return token, admins, False
    print('Create a dedicated Telegram bot with BotFather, then enter its token privately.')
    print('Do not reuse the token of another bot. The token is never printed or placed in shell history.')
    token = getpass.getpass('New Telegram bot token (hidden): ').strip()
    admin_text = input('Admin Telegram numeric user ID(s), comma-separated: ').strip()
    admins = [part.strip() for part in admin_text.split(',') if part.strip()]
    if not re.fullmatch(r'[0-9]{5,15}:[A-Za-z0-9_-]{20,}', token):
        raise RuntimeError('The Telegram bot token format is invalid.')
    if not admins or len(set(admins)) != len(admins) or any(not ADMIN_ID.fullmatch(value) for value in admins):
        raise RuntimeError('Enter one or more unique numeric admin user IDs.')
    result = module.telegram(token, 'getMe', {}, timeout=20)
    if not isinstance(result, dict) or not isinstance(result.get('username'), str):
        raise RuntimeError('Telegram did not identify the supplied bot token.')
    module.no_webhook(token)
    data = dict(schema_version=1, bot_token=token, admin_ids=admins,
                bot_username=result['username'], installed_revision=revision, created_at=time.time())
    atomic(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode(), 0o600)
    return token, set(admins), True


def cron_read():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def install_cron(original, command, home):
    lines = original.decode('utf-8').splitlines()
    starts, ends = [i for i, line in enumerate(lines) if line.strip() == BEGIN], [i for i, line in enumerate(lines) if line.strip() == END]
    if starts or ends:
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            raise RuntimeError('A partial or repeated manual-news cron block needs review.')
        content = lines[starts[0] + 1:ends[0]]
        if content != [command]:
            lines = lines[:starts[0]] + lines[ends[0] + 1:]
        else:
            return original
    if not any(line.strip() == BEGIN for line in lines):
        if lines and lines[-1].strip():
            lines.append('')
        lines += [BEGIN, command, END]
    return ('\n'.join(lines).rstrip() + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        parser.error('Run as the existing publisher user without sudo.')
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('Supply the exact reviewed revision.')
    home, runtime = Path.home(), args.runtime.resolve()
    if not runtime.is_relative_to(home / '.local/state/kiani-instagram-manual-news/source'):
        raise RuntimeError('The runtime is outside the private versioned source directory.')
    valid_runtime(runtime)
    publisher = home / 'kiani-instagram-publisher'
    if publisher.is_symlink() or not publisher.is_dir():
        raise RuntimeError('The existing Instagram image publisher is unavailable.')
    for name in ('fonts/Vazirmatn-Regular.ttf', 'fonts/Vazirmatn-Bold.ttf',
                 'assets/instagram/kiani-logo.svg'):
        if not (publisher / name).is_file():
            raise RuntimeError('The existing Instagram brand assets are incomplete.')
    env_path = home / '.kiani-instagram.env'
    owner_private(env_path)
    sys.path.insert(0, str(runtime))
    sys.path.insert(0, str(runtime / 'selector_trial_runtime'))
    spec = importlib.util.spec_from_file_location('manual_news_intake', runtime / 'instagram_manual_news_intake.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.load_publish_env()
    elapsed, minimum = check_policies(runtime, home)
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=15).returncode:
        raise RuntimeError('The existing cron service is not active.')
    module_path = runtime / 'instagram_manual_news_intake.py'
    config_path = home / '.config/kiani-instagram-manual-news/config.json'
    token, admins, is_new = create_config(module, config_path, args.revision)
    bot = module.telegram(token, 'getMe', {}, timeout=20)
    module.no_webhook(token)
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=15).returncode:
        raise RuntimeError('Cron stopped during setup; nothing was scheduled.')

    state = home / '.local/state/kiani-instagram-manual-news'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state.is_symlink():
        raise RuntimeError('The private intake state directory is unsafe.')
    os.chmod(state, 0o700)
    python = home / 'kiani-instagram-venv/bin/python'
    launcher = home / 'run-kiani-instagram-manual-news.sh'
    log = home / 'kiani-instagram-manual-news.log'
    command = (f'* * * * * {shlex.quote(str(launcher))} >> {shlex.quote(str(log))} 2>&1')
    original = cron_read()
    replacement = install_cron(original, command, home)
    old_launcher = None
    if launcher.exists():
        if launcher.is_symlink() or not launcher.is_file() or launcher.stat().st_uid != os.getuid():
            raise RuntimeError('The existing manual-news launcher is unsafe.')
        old_launcher = (launcher.read_bytes(), launcher.stat().st_mode & 0o777)
    prefix = '#!/bin/bash\nset -euo pipefail\nexport PATH=/usr/local/bin:/usr/bin:/bin\nexport TZ=Europe/Istanbul\nexport PYTHONIOENCODING=utf-8\numask 077\n'
    script = prefix + 'exec ' + shlex.quote(str(python)) + ' -u ' + shlex.quote(str(module_path)) + \
        ' --once --runtime ' + shlex.quote(str(runtime)) + ' --config ' + shlex.quote(str(config_path)) + '\n'
    backup = Path(tempfile.mkdtemp(prefix='kiani-manual-news-backup-', dir=home))
    (backup / 'crontab.txt').write_bytes(original)
    if old_launcher:
        (backup / launcher.name).write_bytes(old_launcher[0])
    try:
        if cron_read() != original:
            raise RuntimeError('The crontab changed during setup; retry after review.')
        atomic(launcher, script.encode(), 0o700)
        if replacement != original:
            subprocess.run(['crontab', '-'], input=replacement, check=True, capture_output=True, timeout=15)
        if cron_read() != replacement:
            raise RuntimeError('The installed cron schedule differs from the prepared schedule.')
        config = json.loads(config_path.read_text(encoding='utf-8'))
        if config.get('installed_revision') != args.revision:
            config['installed_revision'] = args.revision
            atomic(config_path, (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode(), 0o600)
    except BaseException:
        current = launcher.read_bytes() if launcher.exists() else None
        if current == script.encode():
            if old_launcher:
                atomic(launcher, old_launcher[0], old_launcher[1])
            else:
                launcher.unlink(missing_ok=True)
        if cron_read() == replacement and replacement != original:
            subprocess.run(['crontab', '-'], input=original, check=True, capture_output=True, timeout=15)
        raise
    print('Bot:', '@' + bot['username'])
    print('Private admins:', len(admins))
    print('Manual intake: one article link per private admin message.')
    print('Categories: crypto/economy only; reviewed publisher, fresh original text, DeepSeek assessment and Persian translation.')
    print(f'Feed publication: immediate after all source, duplicate, quota and daily/hourly-limit checks.')
    print(f'News retention prerequisite confirmed: {elapsed // 3600} hours, delete only below {minimum} views after the current two-reading checks.')
    print('Feed publication is recorded in the existing news database; current delayed Story and Insights workers can discover it.')
    print('Poller: once per minute; requests are durably recorded and processed without an editor approval queue.')
    print('Launcher:', launcher)
    print('Log:', log)
    print('Backup:', backup)
    print('No Instagram post was published during installation.')
    if is_new:
        print('The bot token is stored only in the private owner-readable configuration; it was not printed.')
    return 0


if __name__ == '__main__':
    try:
        os.umask(0o077)
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}' if isinstance(exc, RuntimeError) else
              f'Activation failed ({type(exc).__name__}).', file=sys.stderr)
        raise SystemExit(1)
