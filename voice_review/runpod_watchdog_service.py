#!/usr/bin/env python3
"""One conservative Runpod watchdog pass; disabled by default."""
from contextlib import closing
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

from runpod_api_client import RunpodAPI
import runpod_lease_store as leases
import runpod_secrets
import runpod_supervisor


def private_json(path):
    path = Path(path)
    runpod_secrets._check_directory(path.parent)
    if path.is_symlink():
        raise ValueError('Unsafe watchdog configuration.')
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        item = os.fstat(stream.fileno())
        if (not stat.S_ISREG(item.st_mode) or item.st_size > 4096 or
                hasattr(os, 'getuid') and (item.st_uid != os.getuid() or item.st_mode & 0o077)):
            raise ValueError('Unsafe watchdog configuration.')
        return json.loads(stream.read(4097))


def heartbeat(state, *, result, enabled):
    state = Path(state)
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    runpod_secrets._check_directory(state)
    target = state / 'watchdog-heartbeat.json'
    if target.is_symlink():
        raise ValueError('Unsafe watchdog heartbeat.')
    data = {'time': time.time(), 'result': result, 'enabled': enabled}
    fd, temporary = tempfile.mkstemp(prefix='.watchdog-heartbeat-', dir=str(state))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(data, out)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def run_once(home, *, api_factory=RunpodAPI):
    config_dir = home / '.config/kiani-instagram-runpod'
    state = home / '.local/state/kiani-instagram-runpod'
    cfg = private_json(config_dir / 'config.json')
    parsed = runpod_supervisor.parse_config(cfg)
    if not parsed['enabled']:
        heartbeat(state, result='disabled', enabled=False)
        return 'disabled'
    key = runpod_secrets.read(config_dir / 'credentials.env')
    if not key:
        raise ValueError('Runpod credentials are unavailable.')
    # No GET or POST occurs for an idle lease; the API client is inert here.
    with closing(leases.connect(state / 'leases.sqlite3')) as con:
        result = runpod_supervisor.run_once(con, api_factory(key), state_dir=state, config=cfg)
    heartbeat(state, result=result, enabled=True)
    return result


if __name__ == '__main__':
    try:
        outcome = run_once(Path.home())
        print('Runpod watchdog:', outcome, flush=True)
        if outcome in ('manual_review', 'action_uncertain', 'status_unavailable'):
            raise SystemExit(2)
    except Exception as exc:
        # Never print raw API responses, environment variables or credentials.
        print('Runpod watchdog stopped:', type(exc).__name__, file=sys.stderr, flush=True)
        raise SystemExit(1)
