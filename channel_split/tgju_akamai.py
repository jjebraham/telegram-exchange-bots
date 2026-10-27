"""Read the fixed TGJU selector through the existing, pinned feed-only bridge."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import stat
import subprocess

HOST = '139.162.186.28'
HOST_LINE = HOST + ' ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEnTEGelzvtZGAbgDtRPDBEDpre/9+Gx+ubQC4jJHCrO'
SELECTOR = 'tgju_current'
MAX_BYTES = 2_000_000


def ssh_command(identity: Path, known_hosts: Path) -> list[str]:
    for path in (identity, known_hosts):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('TGJU relay identity/host-pin file is unsafe')
        if path == identity and info.st_mode & 0o077:
            raise ValueError('TGJU relay identity must be owner-only')
    if known_hosts.read_text(encoding='ascii').strip() != HOST_LINE:
        raise ValueError('TGJU relay host pin does not match')
    return ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known_hosts),
            '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'IdentitiesOnly=yes',
            '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes',
            '-o', 'PermitLocalCommand=no', '-o', 'ConnectionAttempts=1',
            '-o', 'ConnectTimeout=5', '-o', 'LogLevel=ERROR',
            '-i', str(identity), 'root@' + HOST, SELECTOR]


def validate_envelope(envelope: dict, *, now: datetime | None = None) -> dict:
    if (not isinstance(envelope, dict) or envelope.get('ok') is not True
            or type(envelope.get('protocol')) is not int or envelope['protocol'] != 1
            or envelope.get('selector') != SELECTOR):
        raise ValueError('TGJU relay response has an invalid identity or unsuccessful status')
    if envelope.get('http_status', 200) != 200:
        raise ValueError('TGJU relay upstream did not return HTTP 200')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('TGJU relay validation time must include a timezone')
    try:
        observed = datetime.fromisoformat(envelope['observed_at_utc'].replace('Z', '+00:00'))
        raw_headers = envelope['response_headers']
        if not isinstance(raw_headers, dict):
            raise ValueError('Invalid HTTP headers')
        headers = {str(key).lower(): value for key, value in raw_headers.items()}
        http_date = parsedate_to_datetime(headers['date'])
        raw_age = headers.get('age', '0')
        if isinstance(raw_age, bool):
            raise ValueError('Invalid cache age')
        age = Decimal(str(raw_age))
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation):
        raise ValueError('TGJU relay freshness evidence is missing or malformed') from None
    if (observed.tzinfo is None or http_date.tzinfo is None
            or not -5 <= (now - observed).total_seconds() <= 30
            or not -5 <= (now - http_date).total_seconds() <= 90
            or not age.is_finite() or not 0 <= age <= 30):
        raise ValueError('TGJU relay response is stale, future-dated, or cached too long')
    data = envelope.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('current'), dict):
        raise ValueError('TGJU relay payload has no current-price map')
    return data


def fetch_current_payload(timeout: int = 15) -> dict:
    folder = Path.home() / '.ssh'
    command = ssh_command(folder / 'kiani_akamai_rates_ed25519', folder / 'kiani_akamai_rates_known_hosts')
    try:
        result = subprocess.run(command, capture_output=True, timeout=max(1, min(float(timeout), 30)), check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('TGJU relay connection failed or timed out') from None
    if result.returncode:
        raise RuntimeError('TGJU relay request was rejected; check the fixed selector on Akamai')
    if not result.stdout or len(result.stdout) > MAX_BYTES:
        raise ValueError('TGJU relay response has an invalid size')
    try:
        envelope = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise ValueError('TGJU relay response is not valid JSON') from None
    return validate_envelope(envelope)
