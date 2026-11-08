#!/usr/bin/env python3
"""Install a disabled-in-config Runpod watchdog user timer, without Pod actions."""
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import runpod_supervisor
import runpod_watchdog_service as service

SERVICE = 'kiani-runpod-watchdog.service'
TIMER = 'kiani-runpod-watchdog.timer'


class InstallError(RuntimeError):
    pass


def _unit_path(value):
    value = str(value)
    if not value.startswith('/') or not re.fullmatch(r'/[A-Za-z0-9_./-]+', value):
        raise InstallError('A watchdog path is not supported by the unit installer.')
    return value


def unit_contents(home, runtime):
    home = Path(home).resolve()
    runtime = Path(runtime).resolve()
    root = (home / '.local/state/kiani-instagram-manual-news/source').resolve()
    if runtime.parent.parent != root or runtime.name != 'voice_review' or not re.fullmatch(r'[0-9a-f]{40}', runtime.parent.name):
        raise InstallError('The staged watchdog runtime is not pinned.')
    script = runtime / 'runpod_watchdog_service.py'
    python = home / 'kiani-instagram-venv/bin/python'
    if script.is_symlink() or not script.is_file() or not python.is_file():
        raise InstallError('The watchdog runtime or Python environment is unavailable.')
    executable, script_path = _unit_path(python), _unit_path(script)
    service_text = ('[Unit]\nDescription=Kiani Runpod watchdog (config gated)\n'
                    '[Service]\nType=oneshot\nNoNewPrivileges=true\nTimeoutStartSec=60\n'
                    'ExecStart=' + executable + ' -u ' + script_path + '\n')
    timer_text = ('[Unit]\nDescription=Kiani Runpod watchdog timer\n'
                  '[Timer]\nOnBootSec=30s\nOnUnitActiveSec=30s\nAccuracySec=5s\n'
                  'Unit=' + SERVICE + '\n[Install]\nWantedBy=timers.target\n')
    return {SERVICE: service_text, TIMER: timer_text}


def _call(command, *, runner=subprocess.run, timeout=20):
    phase = next((word for word in command if word in
                  ('daemon-reload', 'start', 'enable', 'is-active')), 'operation')
    try:
        result = runner(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise InstallError('The user service manager was unavailable during ' + phase + '.') from None
    if result.returncode:
        raise InstallError('The watchdog service-manager ' + phase + ' operation failed.')


def install(home, runtime, *, runner=subprocess.run, now=time.time, sleep=time.sleep):
    home = Path(home).resolve()
    cfg = service.private_json(home / '.config/kiani-instagram-runpod/config.json')
    if runpod_supervisor.parse_config(cfg)['enabled']:
        raise InstallError('Disable Runpod automation before this watchdog test installation.')
    units = unit_contents(home, runtime)
    directory = home / '.config/systemd/user'
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir() or (hasattr(os, 'getuid') and directory.stat().st_uid != os.getuid()):
        raise InstallError('The user service directory is unsafe.')
    for name, contents in units.items():
        path = directory / name
        if path.is_symlink() or path.exists() and (not path.is_file() or path.stat().st_size > 4096 or path.read_text() != contents):
            raise InstallError('A different watchdog unit already exists; it was not changed.')
    created = []
    newly_enabled = False
    try:
        for name, contents in units.items():
            path = directory / name
            if path.exists():
                continue
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            created.append(path)
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as out:
                out.write(contents)
                out.flush()
                os.fsync(out.fileno())
        _call(['systemctl', '--user', 'daemon-reload'], runner=runner)
        started = now()
        _call(['systemctl', '--user', 'start', SERVICE], runner=runner, timeout=75)
        heartbeat = home / '.local/state/kiani-instagram-runpod/watchdog-heartbeat.json'
        result = service.private_json(heartbeat)
        if (result.get('result') != 'disabled' or result.get('enabled') is not False or
                not isinstance(result.get('time'), (int, float)) or result['time'] < started - 2):
            raise InstallError('The watchdog did not report a fresh disabled heartbeat.')
        # Do not change a previously installed matching timer on failure.
        existing = runner(['systemctl', '--user', 'is-enabled', '--quiet', TIMER],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=15).returncode == 0
        if not existing:
            # A failed enable command can still have partially enabled it.
            newly_enabled = True
            _call(['systemctl', '--user', 'enable', '--now', TIMER], runner=runner)
        else:
            _call(['systemctl', '--user', 'start', TIMER], runner=runner)
        _call(['systemctl', '--user', 'is-active', '--quiet', TIMER], runner=runner)
        return {'timer_active': True, 'automation_enabled': False, 'heartbeat': 'disabled'}
    except Exception:
        if newly_enabled:
            try:
                runner(['systemctl', '--user', 'disable', '--now', TIMER], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except (OSError, subprocess.SubprocessError):
                pass
        for path in created:
            try: path.unlink()
            except OSError: pass
        if created:
            try:
                runner(['systemctl', '--user', 'daemon-reload'], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except (OSError, subprocess.SubprocessError):
                pass
        raise


if __name__ == '__main__':
    try:
        result = install(Path.home(), Path(__file__).resolve().parent)
        print('Watchdog timer active:', result['timer_active'])
        print('Runpod automation enabled:', result['automation_enabled'])
        print('Watchdog heartbeat:', result['heartbeat'])
        print('No Pod was started or stopped, and the Instagram schedule was not changed.')
    except Exception as exc:
        print('Watchdog installation stopped:', str(exc) if isinstance(exc, InstallError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
