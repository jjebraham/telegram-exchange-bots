#!/usr/bin/env python3
"""Activate the approved Persian/Gregorian dates in the existing rates cover."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

PREVIOUS = '4a93854cf9a4d93417f26dbad44d60cc9df39bcb'
FILES = ('instagram_carousel.py', 'instagram_calendar.py')
REQUIREMENTS = 'deploy/instagram-rates/calendar-requirements.txt'
TESTS = 'tests/test_instagram_calendar.py'


class ActivationError(RuntimeError):
    pass


def atomic_write(path, content):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def owned(path, *, directory=False, optional=False):
    if path.is_symlink():
        raise ActivationError('An installation path is a symlink')
    if path.exists():
        if (not path.is_dir() if directory else not path.is_file()) or path.stat().st_uid != os.getuid():
            raise ActivationError('An installation path has an unexpected type or owner')
    elif not optional:
        raise ActivationError('A required installation path is missing')


def verify(python, root, tests):
    code = '''
import io, json, sys, unittest
from datetime import datetime
from importlib.metadata import version
from zoneinfo import ZoneInfo
sys.path.insert(0, sys.argv[1])
from instagram_calendar import calendar_labels
assert version('jdatetime') == '5.2.0'
assert version('jalali-core') == '1.0.0'
suite = unittest.defaultTestLoader.discover(sys.argv[2], pattern='test_instagram_calendar.py')
result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
if not result.wasSuccessful() or result.testsRun != 8:
    sys.exit(1)
labels = calendar_labels(datetime.now(ZoneInfo('Europe/Istanbul')))
print(json.dumps({'tests_passed': result.testsRun, 'calendar': labels}, ensure_ascii=False))
'''
    result = subprocess.run([str(python), '-B', '-c', code, str(root), str(tests)], cwd=root,
                            env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1'),
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    if result.returncode:
        raise ActivationError('Calendar validation failed; template activation stopped')
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise ActivationError('Calendar validation did not return the expected result') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True, help='Exact reviewed commit SHA')
    args = parser.parse_args()
    if os.geteuid() == 0 or not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        raise ActivationError('Run as the existing publisher owner with the exact reviewed revision')
    home = Path.home().resolve()
    root = home / 'kiani-instagram-publisher'
    owned(root, directory=True)
    python = home / 'kiani-instagram-venv/bin/python'
    if not python.is_file():
        raise ActivationError('The existing Instagram venv is unavailable')
    repo = args.repo.expanduser().resolve()

    def git_file(name, revision=args.revision):
        return subprocess.check_output(['git', '-C', str(repo), 'show', f'{revision}:{name}'], timeout=20)

    wanted = {name: git_file(name) for name in FILES}
    test_source = git_file(TESTS)
    requirements = git_file(REQUIREMENTS)
    if requirements.decode().splitlines() != ['jdatetime==5.2.0', 'jalali-core==1.0.0']:
        raise ActivationError('Calendar dependency pins differ from the reviewed configuration')
    for name, content in (*wanted.items(), (TESTS, test_source)):
        compile(content, name, 'exec')
    previous = {}
    for name in FILES:
        path = root / name
        owned(path, optional=name == 'instagram_calendar.py')
        previous[path] = path.read_bytes() if path.exists() else None
    if previous[root / FILES[0]] not in (git_file(FILES[0], PREVIOUS), wanted[FILES[0]]):
        raise ActivationError('Installed carousel differs from the reviewed Hawala version')
    if previous[root / FILES[1]] not in (None, wanted[FILES[1]]):
        raise ActivationError('An unreviewed calendar helper already exists')
    libraries = root / 'instagram_calendar_libs'
    owned(libraries, directory=True, optional=True)
    launcher = home / 'publish-kiani-instagram-rates.sh'
    owned(launcher)
    launcher_bytes = launcher.read_bytes()
    cron = subprocess.check_output(['crontab', '-l'], text=True, timeout=15)
    jobs = [line.split() for line in cron.splitlines()
            if 'publish-kiani-instagram-rates.sh' in line and not line.lstrip().startswith('#')]
    if len(jobs) != 1 or jobs[0][:5] != ['30', '8', '*', '*', '*']:
        raise ActivationError('The existing 11:30 Istanbul rates job could not be confirmed')
    state_dir = home / '.local/state/kiani-instagram-rates'
    owned(state_dir, directory=True)
    lock_path = state_dir / 'feed.json.lock'
    owned(lock_path, optional=True)
    with lock_path.open('a') as lock, tempfile.TemporaryDirectory(prefix='kiani-calendar-check-', dir=home) as temporary:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ActivationError('The rates publisher is running; retry after it finishes') from None
        staging = Path(temporary)
        for name, content in wanted.items():
            (staging / name).write_bytes(content)
        tests = staging / 'tests'
        tests.mkdir()
        (tests / Path(TESTS).name).write_bytes(test_source)
        req = staging / 'requirements.txt'
        req.write_bytes(requirements)
        staged_libraries = staging / 'instagram_calendar_libs'
        print('Preparing pinned Persian calendar dependencies...', flush=True)
        # --isolated avoids private index configuration. Dependency output stays
        # private; these packages are installed only into a dedicated folder.
        install = subprocess.run([str(python), '-m', 'pip', '--isolated', 'install',
                                  '--index-url', 'https://pypi.org/simple', '--disable-pip-version-check',
                                  '--no-cache-dir', '--only-binary=:all:', '--no-compile',
                                  '--target', str(staged_libraries), '-r', str(req)],
                                 capture_output=True, timeout=120)
        if install.returncode:
            raise ActivationError('The pinned calendar dependencies could not be prepared; nothing changed')
        verify(python, staging, tests)
        backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-calendar-backup-', dir=home))
        backup.chmod(0o700)
        for path, content in previous.items():
            if content is not None:
                saved = backup / path.name
                saved.write_bytes(content)
                saved.chmod(0o600)
        changed, library_installed, library_saved = [], False, False
        try:
            if launcher.read_bytes() != launcher_bytes or subprocess.check_output(['crontab', '-l'], text=True, timeout=15) != cron:
                raise ActivationError('Rates launcher or schedule changed during preparation')
            owned(libraries, directory=True, optional=True)
            if libraries.exists():
                os.replace(libraries, backup / libraries.name)
                library_saved = True
            os.replace(staged_libraries, libraries)
            library_installed = True
            for path, old in previous.items():
                owned(path, optional=old is None)
                if (path.read_bytes() if path.exists() else None) != old:
                    raise ActivationError('An installation file changed during preparation')
                atomic_write(path, wanted[path.name])
                changed.append(path)
            checked = verify(python, root, tests)
            if any((root / name).read_bytes() != content for name, content in wanted.items()):
                raise ActivationError('Installed template verification failed')
            if launcher.read_bytes() != launcher_bytes or subprocess.check_output(['crontab', '-l'], text=True, timeout=15) != cron:
                raise ActivationError('Rates launcher or schedule changed during installation')
        except BaseException:
            for path in reversed(changed):
                if path.read_bytes() == wanted[path.name]:
                    if previous[path] is None:
                        path.unlink()
                    else:
                        atomic_write(path, previous[path])
            if library_installed:
                os.replace(libraries, backup / 'failed-calendar-libs')
            if library_saved:
                os.replace(backup / libraries.name, libraries)
            raise
    print(f'Backup: {backup}')
    print(f'Installed rates calendar template: {args.revision}')
    print(json.dumps(checked, ensure_ascii=False, indent=2))
    print('Daily Feed: 11:30 Istanbul. Delayed Story uses the dated Feed preview.')
    print('Activation complete. Nothing was published during installation.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f'ERROR: Calendar activation failed ({type(error).__name__}).', file=sys.stderr)
        if isinstance(error, ActivationError):
            print(str(error), file=sys.stderr)
        raise SystemExit(1)
