#!/usr/bin/env python3
"""Release verified obsolete Instagram test worktrees; retain changed/in-use data."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys

# Exact, superseded manual-test revisions. No broad directory/glob deletion.
CANDIDATES = (
    ('/tmp/kiani-instagram-economy-test.fANFkG', '2107d85169853fc317e2040804c63bebcd4ddbf1'),
    ('/tmp/kiani-instagram-top50-deploy.GJcs14', 'a8f5c4af37da8cfb751dd04ad9d819cd543afebf'),
    ('/tmp/kiani-instagram-news-test.2IZO0Q', 'f3a1fd016f8e471bbfbdfc3a7ee20f415cf1e37b'),
    ('/tmp/kiani-instagram-test.NnOCQc', '821cba7ddd0a7361e98c048623ddf05fca672837'),
)
TARGET_FREE = 128 * 1024 * 1024


def git(repo, user, *args, allow_missing=False):
    # Root is needed for the process audit, but Git always runs as the repo owner.
    command = ['/usr/bin/git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
               '-c', 'core.hooksPath=/dev/null', '-C', str(repo), *args]
    env = {'PATH': '/usr/bin:/bin', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0'}
    result = subprocess.run(command, capture_output=True, timeout=60, env=env,
                            user=user.pw_uid, group=user.pw_gid,
                            extra_groups=os.getgrouplist(user.pw_name, user.pw_gid))
    if allow_missing and result.returncode == 1:
        return None
    if result.returncode:
        raise RuntimeError('Git refused the inspection/removal; files were not force-removed.')
    return result.stdout


def registered(repo, user, target, expected):
    data = git(repo, user, 'worktree', 'list', '--porcelain').decode('utf-8')
    for block in data.strip().split('\n\n'):
        fields = block.splitlines()
        if 'worktree ' + str(target) in fields:
            return 'HEAD ' + expected in fields and 'detached' in fields
    return False


def active_process(target):
    needle = str(target).encode()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            command = (proc / 'cmdline').read_bytes()
            if not command:  # kernel threads/zombies have no user application
                continue
            for name in ('cmdline', 'environ', 'maps'):
                if needle in (proc / name).read_bytes():
                    return 'Active process reference (PID ' + proc.name + ').'
            for name in ('cwd', 'exe'):
                try:
                    value = os.readlink(proc / name)
                except FileNotFoundError:
                    continue
                if value == str(target) or value.startswith(str(target) + '/'):
                    return 'Active process directory/executable (PID ' + proc.name + ').'
            for fd in (proc / 'fd').iterdir():
                try:
                    value = os.readlink(fd)
                except FileNotFoundError:
                    continue
                if value == str(target) or value.startswith(str(target) + '/'):
                    return 'Open process file (PID ' + proc.name + ').'
        except FileNotFoundError:
            continue  # the process exited during inspection
        except (PermissionError, OSError):
            if proc.exists():
                return 'Could not verify process references (PID ' + proc.name + ').'
    return ''


def config_reference(home, target):
    paths = set()
    for pattern in ('*.sh', '*.service', '.env', '.kiani*.env'):
        paths.update(home.glob(pattern))
    for root in (home / 'kiani-instagram-publisher', home / 'kiani-instagram-news-publisher',
                 home / 'kiani-instagram-economy-publisher', home / 'kiani-instagram-top50-publisher',
                 home / 'kiani-instagram-stories-publisher'):
        if root.is_dir():
            for pattern in ('*.py', '*.sh', '*.env', '*.service'):
                paths.update(root.glob(pattern))
    for root in (Path('/etc/systemd/system'), Path('/etc/cron.d'), Path('/var/spool/cron/crontabs'),
                 Path('/etc/nginx/sites-enabled')):
        if root.is_dir():
            paths.update(root.rglob('*'))
    paths.add(Path('/etc/crontab'))
    needle = str(target).encode()
    for path in paths:
        try:
            if path.is_file():
                if path.stat().st_size > 2 * 1024 * 1024:
                    return 'A configuration file is too large to audit; retained.'
                if needle in path.read_bytes():
                    return 'A launcher/service/configuration still references this checkout.'
        except OSError:
            return 'A launcher/service/configuration could not be inspected; retained.'
    return ''


def safe_to_remove(repo, user, target, expected):
    if target.is_symlink() or target.resolve() != target or target.parent != Path('/tmp'):
        return 'Unexpected/symlink target path.'
    if not target.is_dir() or target.stat().st_uid != user.pw_uid:
        return 'Target is missing or owned by another user.'
    if not registered(repo, user, target, expected):
        return 'Registered detached HEAD differs from the reviewed test revision.'
    if git(target, user, 'status', '--porcelain=v1', '-z', '--untracked-files=all'):
        return 'Tracked changes or untracked files exist; retained.'
    ignored = git(target, user, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z')
    for value in ignored.split(b'\0'):
        if not value:
            continue
        path = Path(os.fsdecode(value))
        if '__pycache__' not in path.parts or path.suffix not in {'.pyc', '.pyo'}:
            return 'Ignored data other than disposable Python bytecode exists; retained.'
    reason = config_reference(Path(user.pw_dir), target)
    return reason or active_process(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Remove eligible test worktrees using Git, without force')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        parser.error('Run with sudo for complete process-reference checks; Git removal runs as the repo owner.')
    repo = args.repo.resolve()
    if not repo.is_dir() or not (repo / '.git').is_dir() or args.repo.is_symlink():
        parser.error('Supply the existing primary repository directory.')
    user = pwd.getpwuid(repo.stat().st_uid)
    if user.pw_uid == 0 or str(user.pw_uid) != os.getenv('SUDO_UID'):
        parser.error('Run from the publisher account that owns this repository.')
    print(f'Available space before: {shutil.disk_usage(repo).free / 1024**2:.1f} MiB.')
    for raw, expected in CANDIDATES:
        target = Path(raw)
        if args.apply and shutil.disk_usage(repo).free >= TARGET_FREE:
            break
        if not target.exists():
            print('Not present:', raw)
            continue
        try:
            reason = safe_to_remove(repo, user, target, expected)
            if reason:
                print('RETAIN:', raw, '|', reason)
                continue
            if args.apply:
                # Git's own final safety checks remain enabled. No --force, rm,
                # broad pruning or recursive application-level deletion is used.
                recovery = 'refs/codex/obsolete-instagram-trials/' + target.name
                previous = git(repo, user, 'rev-parse', '--verify', '--quiet', recovery, allow_missing=True)
                if previous and previous.decode().strip() != expected:
                    raise RuntimeError('An existing recovery reference differs; retained.')
                if not previous:
                    git(repo, user, 'update-ref', recovery, expected, '0' * 40)
                git(repo, user, 'worktree', 'remove', str(target))
                print('Removed clean, inactive obsolete test:', raw)
                print('Committed source retained in Git:', recovery)
            else:
                print('Eligible clean, inactive obsolete test:', raw)
        except (RuntimeError, subprocess.TimeoutExpired, OSError):
            print('RETAIN:', raw, '| Could not complete the safety inspection/removal.')
    available = shutil.disk_usage(repo).free
    print(f'Available space after: {available / 1024**2:.1f} MiB.')
    print('Active publishers, publication databases and other worktrees were not removed.')
    if args.apply and available < TARGET_FREE:
        print('Space remains below 128 MiB. Review retained targets; preview not started.')
        return 1
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Cleanup stopped ({type(exc).__name__}); no forced removal.', file=sys.stderr)
        raise SystemExit(1)
