#!/usr/bin/env python3
"""Install and verify the fresh Hawala source for the existing rates carousel."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

PREVIOUS = 'b78698beb59309df8797e7d3bf8b137f89dd34a4'
FILES = ('instagram_carousel.py', 'instagram_hawala_source.py')
SETTINGS = ('INSTAGRAM_HAWALA_SOURCE', 'INSTAGRAM_HAWALA_RUNTIME_ROOT')


class ActivationError(RuntimeError):
    pass


def atomic_write(path, data, mode):
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


def owned_file(path, *, optional=False):
    if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_uid != os.getuid())):
        raise ActivationError('An installation path has an unexpected type or owner')
    if not path.exists() and not optional:
        raise ActivationError('A required installation file is missing')


def live_check(module_root, runtime_root):
    """Calculate once and pass those quotes through the carousel's actual parser."""
    code = '''
import json, sys
sys.path.insert(0, sys.argv[1])
try:
    from instagram_hawala_source import fresh_snapshot
    from instagram_carousel import _parse_hawala_payload
    section = _parse_hawala_payload(fresh_snapshot(sys.argv[2]))
    print(json.dumps(section, ensure_ascii=False))
except Exception as error:
    print(json.dumps({'error_type': type(error).__name__}))
    sys.exit(1)
'''
    python = Path.home() / 'kiani-instagram-venv/bin/python'
    if not python.is_file():
        raise ActivationError('The existing Instagram interpreter is unavailable')
    environment = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    try:
        result = subprocess.run([str(python), '-B', '-c', code, str(module_root), str(runtime_root)],
                                env=environment, cwd=module_root, capture_output=True,
                                text=True, encoding='utf-8', timeout=200)
        payload = json.loads(result.stdout)
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired):
        raise ActivationError('Fresh Hawala verification could not finish; no settings changed') from None
    if result.returncode or not isinstance(payload, dict) or payload.get('kind') != 'hawala' or payload.get('calculation_mode') != 'readonly' or len(payload.get('rows', [])) != 7:
        raise ActivationError('The existing Hawala calculator could not return seven fresh quotes; no settings changed')
    return payload


def configured_environment(previous, runtime_root):
    # Only these two non-secret settings change. All credential lines stay private.
    pattern = re.compile(r'^\s*(?:export\s+)?(' + '|'.join(SETTINGS) + r')\s*=')
    lines = [line for line in previous.decode('utf-8').splitlines() if not pattern.match(line)]
    lines.extend(('INSTAGRAM_HAWALA_SOURCE=calculator',
                  'INSTAGRAM_HAWALA_RUNTIME_ROOT=' + shlex.quote(str(runtime_root))))
    return ('\n'.join(lines) + '\n').encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', help='Exact reviewed Git commit SHA')
    parser.add_argument('--check-live', action='store_true', help='Read-only fresh calculation through the installed carousel parser')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise ActivationError('Run as the existing publisher user, without sudo')
    home = Path.home().resolve()
    root, runtime_root = home / 'kiani-instagram-publisher', home / 'kiani-hawala-bot'
    if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid():
        raise ActivationError('The installed publisher directory is unavailable')
    if args.check_live:
        section = live_check(root, runtime_root)
        print(json.dumps(section, ensure_ascii=False, indent=2))
        print('Fresh Hawala section verified. Nothing published.')
        return 0
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision or ''):
        raise ActivationError('Supply the exact reviewed revision')
    repo = args.repo.expanduser().resolve()
    wanted = {name: subprocess.check_output(['git', '-C', str(repo), 'show', f'{args.revision}:{name}'], timeout=20)
              for name in FILES}
    for name, content in wanted.items():
        compile(content, name, 'exec')
        owned_file(root / name, optional=name == 'instagram_hawala_source.py')
    original = subprocess.check_output(['git', '-C', str(repo), 'show', f'{PREVIOUS}:instagram_carousel.py'], timeout=20)
    previous = {root / name: (root / name).read_bytes() if (root / name).exists() else None for name in FILES}
    if previous[root / FILES[0]] not in (original, wanted[FILES[0]]):
        raise ActivationError('Installed carousel differs from the reviewed USDT fix; nothing changed')
    if previous[root / FILES[1]] not in (None, wanted[FILES[1]]):
        raise ActivationError('An unreviewed Hawala source already exists; nothing changed')
    env_path = home / '.kiani-instagram.env'
    launcher = home / 'publish-kiani-instagram-rates.sh'
    owned_file(env_path)
    owned_file(launcher)
    previous[env_path] = env_path.read_bytes()
    launcher_bytes = launcher.read_bytes()
    cron = subprocess.check_output(['crontab', '-l'], text=True, timeout=15)
    jobs = [line.split() for line in cron.splitlines()
            if 'publish-kiani-instagram-rates.sh' in line and not line.lstrip().startswith('#')]
    if len(jobs) != 1 or jobs[0][:5] != ['30', '8', '*', '*', '*']:
        raise ActivationError('The existing daily rates job could not be confirmed')
    state_dir = home / '.local/state/kiani-instagram-rates'
    if state_dir.is_symlink() or not state_dir.is_dir() or state_dir.stat().st_uid != os.getuid():
        raise ActivationError('The existing rates state directory is unavailable')
    lock_path = state_dir / 'feed.json.lock'
    owned_file(lock_path, optional=True)
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ActivationError('The rates publisher is running; retry after it finishes') from None
        # Verify the new bridge before replacing production files or settings.
        with tempfile.TemporaryDirectory(prefix='kiani-hawala-check-', dir=home) as staging:
            staging = Path(staging)
            for name, content in wanted.items():
                (staging / name).write_bytes(content)
            section = live_check(staging, runtime_root)
        updated = {root / name: content for name, content in wanted.items()}
        updated[env_path] = configured_environment(previous[env_path], runtime_root)
        backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-hawala-backup-', dir=home))
        backup.chmod(0o700)
        for path, content in previous.items():
            if content is not None:
                saved = backup / path.name
                saved.write_bytes(content)
                saved.chmod(0o600)
        changed = []
        try:
            if launcher.read_bytes() != launcher_bytes or subprocess.check_output(['crontab', '-l'], text=True, timeout=15) != cron:
                raise ActivationError('Rates launcher or schedule changed during preparation')
            for path, content in updated.items():
                owned_file(path, optional=previous[path] is None)
                current = path.read_bytes() if path.exists() else None
                if current != previous[path]:
                    raise ActivationError('An installation file changed during preparation')
                atomic_write(path, content, 0o600 if path == env_path else 0o644)
                changed.append(path)
                if path.read_bytes() != content:
                    raise ActivationError('The installed Hawala source could not be confirmed')
            if launcher.read_bytes() != launcher_bytes or subprocess.check_output(['crontab', '-l'], text=True, timeout=15) != cron:
                raise ActivationError('Rates launcher or schedule changed during installation')
        except BaseException:
            for path in reversed(changed):
                if path.read_bytes() == updated[path]:
                    if previous[path] is None:
                        path.unlink()
                    else:
                        atomic_write(path, previous[path], 0o600 if path == env_path else 0o644)
            raise
    print(f'Backup: {backup}')
    print(f'Installed fresh Hawala source: {args.revision}')
    print(json.dumps(section, ensure_ascii=False, indent=2))
    print('Fresh Hawala section verified: seven currencies, original live adjustments and canonical TRY.')
    print('Daily rates Feed: 11:30 Istanbul. Story preview: 30 minutes after the Feed post.')
    print('Activation complete. No Instagram or Telegram message was published.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f'ERROR: Fresh Hawala activation failed ({type(error).__name__}).', file=sys.stderr)
        if isinstance(error, ActivationError):
            print(str(error), file=sys.stderr)
        raise SystemExit(1)
