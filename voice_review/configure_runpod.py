#!/usr/bin/env python3
"""Verify and save a Runpod key privately; leave automation disabled."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import warnings

from runpod_api_client import RunpodAPI, RunpodAPIError
import runpod_secrets
import runpod_supervisor


def configure(root, pod_id, key, *, api_factory=RunpodAPI):
    root = Path(root)
    if not isinstance(pod_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', pod_id):
        raise ValueError('Invalid Pod identity.')
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    runpod_secrets._check_directory(root)
    config_path = root / 'config.json'
    secret_path = root / 'credentials.env'
    if config_path.is_symlink() or (config_path.exists() and not config_path.is_file()):
        raise ValueError('Unsafe existing Runpod configuration.')
    if config_path.exists():
        info = config_path.stat()
        if info.st_size > 4096 or (hasattr(os, 'getuid') and (info.st_uid != os.getuid() or info.st_mode & 0o077)):
            raise ValueError('Existing Runpod configuration is not private.')
        existing = json.loads(config_path.read_text(encoding='utf-8'))
        normalized = runpod_supervisor.parse_config(existing)
        if normalized['pod_id'] != pod_id:
            raise ValueError('Another Pod is already configured; no changes made.')
    else:
        existing = None
    key = runpod_secrets._validate(key)
    pod = api_factory(key).status(pod_id)
    if not isinstance(pod, dict) or pod.get('id') != pod_id:
        raise ValueError('The requested Pod could not be verified.')
    runpod_secrets.write(secret_path, key)
    if existing is None:
        data = {'pod_id': pod_id, 'enabled': False, 'exclusive_during_managed_job': True,
                'max_hourly_usd': 1.0, 'max_uptime_seconds': 1800,
                'startup_timeout_seconds': 300, 'job_timeout_seconds': 900, 'idle_timeout_seconds': 120}
        runpod_supervisor.parse_config(data)
        try:
            fd = os.open(str(config_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                         getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except FileExistsError:
            raise ValueError('Runpod configuration changed concurrently; no overwrite performed.') from None
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(data, out, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.chmod(config_path, 0o600)
        enabled = False
    else:
        enabled = normalized['enabled']
    return {'status': pod.get('status') if pod.get('status') in
            ('RUNNING', 'EXITED', 'STARTING', 'PROVISIONING', 'ERROR', 'TERMINATED') else 'OTHER',
            'enabled': enabled, 'config_preserved': existing is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pod', required=True)
    args = parser.parse_args()
    root = Path.home() / '.config/kiani-instagram-runpod'
    path = root / 'credentials.env'
    key = runpod_secrets.read(path)
    if not key:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('Runpod API key (hidden): ').strip()
    if not key:
        raise ValueError('No API key supplied.')
    result = configure(root, args.pod, key)
    print('Runpod read access verified. Pod status:', result['status'])
    print('Protected key and settings available. Automation enabled:', result['enabled'])
    print('Existing settings preserved:', result['config_preserved'])
    print('No Pod was started or stopped; no Instagram request was made.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RunpodAPIError, runpod_secrets.SecretError,
            runpod_supervisor.SupervisorError, getpass.GetPassWarning, EOFError) as exc:
        print('Runpod setup stopped:', type(exc).__name__)
        raise SystemExit(1)
