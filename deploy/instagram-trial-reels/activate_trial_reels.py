#!/usr/bin/env python3
"""Install private Trial/Direct Reel commands and their daily selector slots."""
from __future__ import annotations

import argparse
from datetime import datetime
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

BEGIN = '# BEGIN Kiani Instagram Trial Reels v1'
END = '# END Kiani Instagram Trial Reels v1'
MANUAL_BEGIN = '# BEGIN Kiani manual Instagram news v1'
MANUAL_END = '# END Kiani manual Instagram news v1'


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
        raise RuntimeError('A private state directory is a symlink.')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if not path.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('A private state directory has unsafe ownership or permissions.')
    os.chmod(path, 0o700)


def cron_read():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def replace_trial_cron(original, commands):
    lines = original.decode('utf-8').splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if starts or ends:
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            raise RuntimeError('The existing Trial Reel cron block is incomplete or repeated.')
        lines = lines[:starts[0]] + lines[ends[0] + 1:]
    if any(('run-kiani-instagram-trial-reels.sh' in line or
            'run-kiani-instagram-direct-reels.sh' in line or
            'run-kiani-instagram-reel-schedule.sh' in line) and not line.lstrip().startswith('#') for line in lines):
        raise RuntimeError('A Trial Reel launcher is scheduled outside its managed cron block.')
    if lines and lines[-1].strip():
        lines.append('')
    lines += [BEGIN, 'CRON_TZ=Europe/Istanbul', *commands, END]
    return ('\n'.join(lines).rstrip() + '\n').encode()


def require_manual_cron(original, launcher, log):
    lines = original.decode('utf-8').splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == MANUAL_BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == MANUAL_END]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise RuntimeError('The existing admin news bot cron block is missing or ambiguous.')
    content = [line for line in lines[starts[0] + 1:ends[0]] if line.strip()]
    expected = f'* * * * * {shlex.quote(str(launcher))} >> {shlex.quote(str(log))} 2>&1'
    if content != [expected]:
        raise RuntimeError('The existing admin news poller schedule differs; review it before installing Trial Reels.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        parser.error('Run as the existing publisher user without sudo.')
    home, runtime = Path.home(), args.runtime.resolve()
    source_root = home / '.local/state/kiani-instagram-manual-news/source'
    if not runtime.is_relative_to(source_root):
        raise RuntimeError('The reviewed runtime is outside the pinned private source directory.')
    if not all((runtime / name).is_file() and not (runtime / name).is_symlink() for name in (
            'instagram_trial_reels.py', 'instagram_trial_music.py', 'instagram_reel_motion.py', 'instagram_reel_media.py', 'instagram_reel_source_image.py',
            'instagram_reel_usage.py', 'report_reel_usage.py', 'instagram_reel_commons.py', 'instagram_reel_stock.py', 'instagram_reel_voice.py', 'instagram_manual_news_intake.py', 'instagram_ranked_news.py',
            'instagram_direct_reel_retention.py')):
        raise RuntimeError('A required Trial Reel runtime file is missing or unsafe.')

    publisher = home / 'kiani-instagram-publisher'
    if publisher.is_symlink() or not publisher.is_dir():
        raise RuntimeError('The existing Instagram brand assets are unavailable.')
    for name in ('fonts/Vazirmatn-Regular.ttf', 'fonts/Vazirmatn-Bold.ttf', 'assets/instagram/kiani-logo.svg'):
        asset = publisher / name
        if asset.is_symlink() or not asset.is_file():
            raise RuntimeError('The existing Kiani fonts or logo are incomplete.')
    media_parent = Path('/var/www/peerexo.com/public/instagram-rates')
    media_root = media_parent / 'trial-reels'
    if media_parent.is_symlink() or not media_parent.is_dir() or media_root.is_symlink() or media_root.exists() and not media_root.is_dir():
        raise RuntimeError('The approved public HTTPS media directory is unavailable or unsafe.')
    for name in ('ffmpeg', 'ffprobe'):
        if not shutil.which(name):
            raise RuntimeError(name + ' is required to render and verify Trial Reels.')
    try:
        from PIL import ImageFont
        import arabic_reshaper  # noqa: F401
        from bidi.algorithm import get_display  # noqa: F401
        ImageFont.truetype(str(publisher / 'fonts/Vazirmatn-Regular.ttf'), 26,
                           layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        raise RuntimeError('The installed Python environment cannot shape the existing Persian font.') from None

    bot_config = home / '.config/kiani-instagram-manual-news/config.json'
    owner_private(bot_config)
    # The manual intake loads its translation credentials via this pinned
    # runtime; make the runtime importable before calling its helpers.
    sys.path[:0] = [str(runtime), str(runtime / 'selector_trial_runtime')]
    from instagram_reel_voice import configured as voice_configured
    if not voice_configured():
        raise RuntimeError('Configure and test Persian narration before installation.')
    module_path = runtime / 'instagram_manual_news_intake.py'
    spec = importlib.util.spec_from_file_location('manual_news_intake', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token, admins = module.private_json(bot_config)
    module.no_webhook(token)
    module.load_publish_env()

    from instagram_news_batch import activation, guard
    from instagram_insights_data import Graph, read_db
    from instagram_news_retention import permission_proof
    from instagram_direct_reel_retention import enable as enable_direct_retention, _meta as direct_meta
    activation()
    reservation = guard()
    print('Existing publishing quota and scheduled Story reservations verified; remaining:',
          reservation.get('remaining'), flush=True)
    graph = Graph()
    insights_db = home / '.local/state/kiani-instagram-insights/insights.sqlite3'
    with read_db(insights_db) as audit:
        permission_proof(audit, graph)
    direct_db = home / '.local/state/kiani-instagram-trial-reels/trial_reels.sqlite3'
    if direct_db.is_symlink():
        raise RuntimeError('The direct Reel state database is a symlink.')
    if direct_db.exists():
        import sqlite3
        with sqlite3.connect(direct_db.as_uri() + '?mode=ro', uri=True) as prior:
            prior.row_factory = sqlite3.Row
            tables = {row['name'] for row in prior.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'direct_reel_retention_meta' in tables and direct_meta(prior, 'paused'):
                raise RuntimeError('Direct Reel deletion is paused for manual review; resolve that state before installation.')
    print('Direct Reel deletion permission proof verified for the current account and token.', flush=True)

    if subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=15).returncode:
        raise RuntimeError('The existing cron service is not active.')
    lock_path = home / '.local/state/kiani-instagram-trial-reels/install.lock'
    private_directory(lock_path.parent)
    if lock_path.is_symlink():
        raise RuntimeError('The private installer lock is unsafe.')
    with lock_path.open('a') as install_lock:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(install_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another Trial Reel installation is active.') from None

        python = home / 'kiani-instagram-venv/bin/python'
        manual_launcher = home / 'run-kiani-instagram-manual-news.sh'
        manual_log = home / 'kiani-instagram-manual-news.log'
        daily_launcher = home / 'run-kiani-instagram-trial-reels.sh'
        daily_log = home / 'kiani-instagram-trial-reels-cron.log'
        direct_launcher = home / 'run-kiani-instagram-direct-reels.sh'
        direct_log = home / 'kiani-instagram-direct-reels-cron.log'
        original = cron_read()
        require_manual_cron(original, manual_launcher, manual_log)
        # Debian cron uses the daemon timezone even when CRON_TZ is present.
        # Tick each minute and check Istanbul wall time in the launcher.
        tick_launcher = home / 'run-kiani-instagram-reel-schedule.sh'
        tick_log = home / 'kiani-instagram-reel-scheduler.log'
        daily_commands = [f'* * * * * {shlex.quote(str(tick_launcher))} >> {shlex.quote(str(tick_log))} 2>&1']
        replacement = replace_trial_cron(original, daily_commands)
        if subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=15).returncode:
            raise RuntimeError('Cron stopped during setup; nothing was scheduled.')

        prefix = ('#!/bin/bash\nset -euo pipefail\nexport PATH=/usr/local/bin:/usr/bin:/bin\n'
                  'export TZ=Europe/Istanbul\nexport PYTHONIOENCODING=utf-8\numask 077\n')
        manual_script = prefix + 'exec ' + shlex.quote(str(python)) + ' -u ' + shlex.quote(str(module_path)) + \
            ' --once --runtime ' + shlex.quote(str(runtime)) + ' --config ' + shlex.quote(str(bot_config)) + '\n'
        daily_script = prefix + 'exec ' + shlex.quote(str(python)) + ' -u ' + \
            shlex.quote(str(runtime / 'instagram_trial_reels.py')) + ' --daily --runtime ' + \
            shlex.quote(str(runtime)) + ' --assets ' + shlex.quote(str(publisher)) + ' "$@"\n'
        direct_script = prefix + 'exec ' + shlex.quote(str(python)) + ' -u ' + \
            shlex.quote(str(runtime / 'instagram_trial_reels.py')) + ' --direct-daily --runtime ' + \
            shlex.quote(str(runtime)) + ' --assets ' + shlex.quote(str(publisher)) + ' "$@"\n'

        # One local-time tick dispatches at most one configured slot per minute.
        tick_script = prefix + 'slot=$(date +%H:%M)\n' + \
            'case "$slot" in\n' + \
            '  11:00|13:00|15:00|17:00|20:30) exec ' + shlex.quote(str(daily_launcher)) + \
            ' --slot "$slot" >> ' + shlex.quote(str(daily_log)) + ' 2>&1 ;;\n' + \
            '  12:00|18:00) exec ' + shlex.quote(str(direct_launcher)) + \
            ' --slot "$slot" >> ' + shlex.quote(str(direct_log)) + ' 2>&1 ;;\n' + \
            'esac\n'

        paths = (manual_launcher, daily_launcher, direct_launcher, tick_launcher)
        old_files = {}
        for path in paths:
            if path.exists():
                if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
                    raise RuntimeError('An existing launcher is unsafe.')
                old_files[path] = (path.read_bytes(), path.stat().st_mode & 0o777)
            else:
                old_files[path] = None
        backup = Path(tempfile.mkdtemp(prefix='kiani-trial-reels-backup-', dir=home))
        (backup / 'crontab.txt').write_bytes(original)
        config_original = (bot_config.read_bytes(), bot_config.stat().st_mode & 0o777)
        for path, old in old_files.items():
            if old:
                (backup / path.name).write_bytes(old[0])

        try:
            if cron_read() != original:
                raise RuntimeError('The crontab changed during setup; retry after review.')
            atomic(manual_launcher, manual_script.encode(), 0o700)
            atomic(daily_launcher, daily_script.encode(), 0o700)
            atomic(direct_launcher, direct_script.encode(), 0o700)
            atomic(tick_launcher, tick_script.encode(), 0o700)
            if replacement != original:
                subprocess.run(['crontab', '-'], input=replacement, check=True,
                               capture_output=True, timeout=15)
            if cron_read() != replacement:
                raise RuntimeError('The installed cron schedule differs from the prepared schedule.')
            config = json.loads(bot_config.read_text(encoding='utf-8'))
            config['installed_revision'] = args.revision
            atomic(bot_config, (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode(), 0o600)
            enabled_after = enable_direct_retention()
        except BaseException:
            for path, old in old_files.items():
                if old:
                    atomic(path, old[0], old[1])
                elif path.exists():
                    path.unlink()
            atomic(bot_config, config_original[0], config_original[1])
            if cron_read() == replacement and replacement != original:
                subprocess.run(['crontab', '-'], input=original, check=True,
                               capture_output=True, timeout=15)
            raise

    print('Existing Telegram bot:', '@' + str(json.loads(bot_config.read_text()).get('bot_username', 'configured')))
    print('Authorized private admins:', len(admins))
    print('Admin commands: /trial <reviewed publisher URL> and /reel <reviewed publisher URL>.')
    print('Direct Reel: up to 10 admin posts/day; 200 views at two hours, with two low readings 10 minutes apart.')
    print('Automatic Trial Reel slots: 11:00, 13:00, 15:00, 17:00 and 20:30 Europe/Istanbul.')
    print('Istanbul daily limits: up to 5 admin Trial Reels plus 5 automatic; Meta quota applies.')
    print('Automatic direct Reels: 12:00 and 18:00 Europe/Istanbul; up to 2/day.')
    print('Direct Reel retention enrolled after:', datetime.fromtimestamp(enabled_after).isoformat(), flush=True)
    print('Trial graduation: SS_PERFORMANCE; Instagram decides whether to share Trial Reels with followers.')
    print('Trial Reels are excluded from ordinary Feed deletion and delayed-Story workers.')
    print('Bounded status polling runs through the existing private Telegram worker.')
    print('No Reel was created or published during installation.')
    print('Manual-news launcher:', manual_launcher)
    print('Trial Reel launcher:', daily_launcher)
    print('Direct Reel launcher:', direct_launcher)
    print('Daily log:', daily_log)
    print('Backup:', backup)
    return 0


if __name__ == '__main__':
    try:
        os.umask(0o077)
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}' if isinstance(exc, RuntimeError) else
              f'Instagram Reel activation stopped ({type(exc).__name__}).', file=sys.stderr)
        raise SystemExit(1)




