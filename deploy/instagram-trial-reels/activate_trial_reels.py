#!/usr/bin/env python3
"""Install the private admin Trial Reel command and daily 20:30 selector."""
from __future__ import annotations

import argparse
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


def replace_trial_cron(original, command):
    lines = original.decode('utf-8').splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if starts or ends:
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            raise RuntimeError('The existing Trial Reel cron block is incomplete or repeated.')
        lines = lines[:starts[0]] + lines[ends[0] + 1:]
    if any('run-kiani-instagram-trial-reels.sh' in line and not line.lstrip().startswith('#') for line in lines):
        raise RuntimeError('A Trial Reel launcher is scheduled outside its managed cron block.')
    if lines and lines[-1].strip():
        lines.append('')
    lines += [BEGIN, 'CRON_TZ=Europe/Istanbul', command, END]
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
            'instagram_trial_reels.py', 'instagram_trial_music.py', 'instagram_reel_motion.py', 'instagram_reel_media.py',
            'instagram_reel_usage.py', 'report_reel_usage.py', 'instagram_manual_news_intake.py', 'instagram_ranked_news.py')):
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
    module_path = runtime / 'instagram_manual_news_intake.py'
    spec = importlib.util.spec_from_file_location('manual_news_intake', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token, admins = module.private_json(bot_config)
    module.no_webhook(token)
    module.load_publish_env()

    from instagram_news_batch import activation, guard
    activation()
    reservation = guard()
    print('Existing publishing quota and scheduled Story reservations verified; remaining:',
          reservation.get('remaining'), flush=True)

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
        original = cron_read()
        require_manual_cron(original, manual_launcher, manual_log)
        daily_command = f'30 20 * * * {shlex.quote(str(daily_launcher))} >> {shlex.quote(str(daily_log))} 2>&1'
        replacement = replace_trial_cron(original, daily_command)
        if subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=15).returncode:
            raise RuntimeError('Cron stopped during setup; nothing was scheduled.')

        prefix = ('#!/bin/bash\nset -euo pipefail\nexport PATH=/usr/local/bin:/usr/bin:/bin\n'
                  'export TZ=Europe/Istanbul\nexport PYTHONIOENCODING=utf-8\numask 077\n')
        manual_script = prefix + 'exec ' + shlex.quote(str(python)) + ' -u ' + shlex.quote(str(module_path)) + \
            ' --once --runtime ' + shlex.quote(str(runtime)) + ' --config ' + shlex.quote(str(bot_config)) + '\n'
        daily_script = prefix + 'exec ' + shlex.quote(str(python)) + ' -u ' + \
            shlex.quote(str(runtime / 'instagram_trial_reels.py')) + ' --daily --runtime ' + \
            shlex.quote(str(runtime)) + ' --assets ' + shlex.quote(str(publisher)) + '\n'

        paths = (manual_launcher, daily_launcher)
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
        for path, old in old_files.items():
            if old:
                (backup / path.name).write_bytes(old[0])

        try:
            if cron_read() != original:
                raise RuntimeError('The crontab changed during setup; retry after review.')
            atomic(manual_launcher, manual_script.encode(), 0o700)
            atomic(daily_launcher, daily_script.encode(), 0o700)
            if replacement != original:
                subprocess.run(['crontab', '-'], input=replacement, check=True,
                               capture_output=True, timeout=15)
            if cron_read() != replacement:
                raise RuntimeError('The installed cron schedule differs from the prepared schedule.')
            config = json.loads(bot_config.read_text(encoding='utf-8'))
            config['installed_revision'] = args.revision
            atomic(bot_config, (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode(), 0o600)
        except BaseException:
            for path, old in old_files.items():
                if old:
                    atomic(path, old[0], old[1])
                elif path.exists():
                    path.unlink()
            if cron_read() == replacement and replacement != original:
                subprocess.run(['crontab', '-'], input=original, check=True,
                               capture_output=True, timeout=15)
            raise

    print('Existing Telegram bot:', '@' + str(json.loads(bot_config.read_text()).get('bot_username', 'configured')))
    print('Authorized private admins:', len(admins))
    print('Admin command: /trial <one approved publisher article URL>; publication timestamp optional.')
    print('Daily automatic selection: highest-ranked eligible crypto/economy story at 20:30 Europe/Istanbul.')
    print('Istanbul daily limits: up to 5 admin Trial Reels plus 1 automatic; Meta quota applies.')
    print('Graduation: SS_PERFORMANCE; Instagram decides whether to share with followers.')
    print('Trial Reels are excluded from ordinary Feed deletion and delayed-Story workers.')
    print('Bounded status polling runs through the existing private Telegram worker.')
    print('No Reel was created or published during installation.')
    print('Manual-news launcher:', manual_launcher)
    print('Trial Reel launcher:', daily_launcher)
    print('Daily log:', daily_log)
    print('Backup:', backup)
    return 0


if __name__ == '__main__':
    try:
        os.umask(0o077)
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}' if isinstance(exc, RuntimeError) else
              f'Trial Reel activation stopped ({type(exc).__name__}).', file=sys.stderr)
        raise SystemExit(1)


