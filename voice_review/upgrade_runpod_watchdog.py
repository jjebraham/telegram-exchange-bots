#!/usr/bin/env python3
"""Upgrade the installed disabled Runpod watchdog timer with backup/rollback."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import install_runpod_watchdog as installer
import runpod_secrets
import runpod_supervisor
import runpod_watchdog_service as service
from runpod_worker_lock import pod_lock


def _write_replace(path, contents):
    if path.is_symlink() or not path.is_file():
        raise installer.InstallError('The watchdog unit changed unexpectedly.')
    fd, temporary = tempfile.mkstemp(prefix='.kiani-watchdog-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as out:
            out.write(contents)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, 0o600)
        if path.is_symlink():
            raise installer.InstallError('The watchdog unit changed unexpectedly.')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def upgrade(home, runtime, old_revision, *, runner=subprocess.run, now=time.time):
    home = Path(home).resolve()
    if not re.fullmatch(r'[0-9a-f]{40}', str(old_revision)):
        raise installer.InstallError('The previous watchdog revision is invalid.')
    old_runtime = home / '.local/state/kiani-instagram-manual-news/source' / old_revision / 'voice_review'
    old_units = installer.unit_contents(home, old_runtime)
    new_units = installer.unit_contents(home, runtime)
    config_path = home / '.config/kiani-instagram-runpod/config.json'
    cfg = runpod_supervisor.parse_config(service.private_json(config_path))
    if cfg['enabled']:
        raise installer.InstallError('Runpod automation must be disabled before upgrading the watchdog.')
    state = home / '.local/state/kiani-instagram-runpod'
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    runpod_secrets._check_directory(state)
    directory = home / '.config/systemd/user'
    service_path, timer_path = directory / installer.SERVICE, directory / installer.TIMER
    if directory.is_symlink() or not directory.is_dir():
        raise installer.InstallError('The watchdog unit directory is unsafe.')
    for path in (service_path, timer_path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise installer.InstallError('An installed watchdog unit is unavailable or unsafe.')
    with pod_lock(state, cfg['pod_id']) as held:
        if not held:
            raise installer.InstallError('A managed Pod job is active; the watchdog was not changed.')
        original_service, original_timer = service_path.read_text(), timer_path.read_text()
        if original_timer != old_units[installer.TIMER] or original_timer != new_units[installer.TIMER]:
            raise installer.InstallError('The installed watchdog timer differs; no changes made.')
        if original_service == new_units[installer.SERVICE]:
            installer._call(['systemctl', '--user', 'is-active', '--quiet', installer.TIMER], runner=runner)
            return {'already_current': True, 'backup': None}
        if original_service != old_units[installer.SERVICE]:
            raise installer.InstallError('The installed watchdog service differs; no changes made.')
        installer._call(['systemctl', '--user', 'is-enabled', '--quiet', installer.TIMER], runner=runner)
        installer._call(['systemctl', '--user', 'is-active', '--quiet', installer.TIMER], runner=runner)
        backups = state / 'watchdog-backups'
        backups.mkdir(mode=0o700, exist_ok=True)
        runpod_secrets._check_directory(backups)
        backup = Path(tempfile.mkdtemp(prefix='upgrade-', dir=str(backups)))
        for name, value in ((installer.SERVICE, original_service), (installer.TIMER, original_timer)):
            destination = backup / name
            with destination.open('x', encoding='utf-8') as out: out.write(value)
            os.chmod(destination, 0o600)
        timer_stopped = False
        replaced = False
        try:
            timer_stopped = True
            installer._call(['systemctl', '--user', 'stop', installer.TIMER], runner=runner)
            installer._call(['systemctl', '--user', 'stop', installer.SERVICE], runner=runner)
            if service_path.read_text() != original_service or runpod_supervisor.parse_config(service.private_json(config_path))['enabled']:
                raise installer.InstallError('Watchdog configuration changed during upgrade.')
            _write_replace(service_path, new_units[installer.SERVICE])
            replaced = True
            installer._call(['systemctl', '--user', 'daemon-reload'], runner=runner)
            started = now()
            installer._call(['systemctl', '--user', 'start', installer.SERVICE], runner=runner, timeout=75)
            beat = service.private_json(state / 'watchdog-heartbeat.json')
            if beat.get('result') != 'disabled' or beat.get('enabled') is not False or beat.get('time', 0) < started - 2:
                raise installer.InstallError('The updated watchdog did not report a fresh disabled heartbeat.')
            installer._call(['systemctl', '--user', 'start', installer.TIMER], runner=runner)
            installer._call(['systemctl', '--user', 'is-active', '--quiet', installer.TIMER], runner=runner)
            return {'already_current': False, 'backup': str(backup)}
        except Exception:
            try:
                safe_to_restart = (not replaced and not service_path.is_symlink() and
                                   service_path.read_text() == original_service)
            except OSError:
                safe_to_restart = False
            if replaced:
                try:
                    if not service_path.is_symlink() and service_path.read_text() == new_units[installer.SERVICE]:
                        _write_replace(service_path, original_service)
                        safe_to_restart = True
                    runner(['systemctl', '--user', 'daemon-reload'], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                except (OSError, subprocess.SubprocessError, installer.InstallError):
                    pass
            if timer_stopped and safe_to_restart:
                try:
                    runner(['systemctl', '--user', 'start', installer.TIMER], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                except (OSError, subprocess.SubprocessError):
                    pass
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-revision', required=True)
    args = parser.parse_args()
    result = upgrade(Path.home(), Path(__file__).resolve().parent, args.old_revision)
    print('Watchdog upgraded; timer active; Runpod automation remains disabled.')
    print('Already current:', result['already_current'])
    if result['backup']: print('Backup:', result['backup'])
    print('No Pod was started or stopped; the Instagram schedule was not changed.')


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print('Watchdog upgrade stopped:', str(exc) if isinstance(exc, installer.InstallError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
