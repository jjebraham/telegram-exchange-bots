"""Persistent single-Pod lease journal for the staged Runpod integration.

This module never controls a Pod. Unknown action outcomes retain the lease;
release requires verified provider state, not a timeout or an exception.
"""
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import stat
import time
import uuid


class LeaseError(RuntimeError):
    pass


ACTIVE = ('RESERVED', 'START_REQUESTED', 'START_CONFIRMED', 'ACTION_UNCERTAIN', 'STOP_REQUESTED')


def connect(path):
    path = Path(path)
    parent = path.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or path.is_symlink() or not parent.is_dir():
        raise LeaseError('Unsafe lease location.')
    if hasattr(os, 'getuid') and (parent.stat().st_uid != os.getuid() or parent.stat().st_mode & 0o077):
        raise LeaseError('Lease directory must be private and owned by this user.')
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (hasattr(os, 'getuid') and
                (info.st_uid != os.getuid() or info.st_mode & 0o077)):
            raise LeaseError('Lease database must be private and owned by this user.')
    finally:
        os.close(fd)
    con = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute('''CREATE TABLE IF NOT EXISTS leases (
        lease_id TEXT PRIMARY KEY, pod_id TEXT NOT NULL, state TEXT NOT NULL,
        created_at REAL NOT NULL, updated_at REAL NOT NULL, rate_usd REAL NOT NULL,
        provider_started_at TEXT)''')
    con.execute('''CREATE UNIQUE INDEX IF NOT EXISTS one_active_pod ON leases(pod_id)
        WHERE state IN ('RESERVED', 'START_REQUESTED', 'START_CONFIRMED', 'ACTION_UNCERTAIN', 'STOP_REQUESTED')''')
    return con


def reserve(con, pod_id, rate, *, now=None):
    if not isinstance(pod_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', pod_id):
        raise LeaseError('Invalid Pod identity.')
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 < rate <= 1000:
        raise LeaseError('Invalid compute rate.')
    now = time.time() if now is None else now
    lease_id = uuid.uuid4().hex
    try:
        con.execute('INSERT INTO leases VALUES(?,?,?,?,?,?,NULL)',
                    (lease_id, pod_id, 'RESERVED', now, now, rate))
    except sqlite3.IntegrityError:
        raise LeaseError('This Pod already has an unresolved lease.') from None
    return lease_id


def _change(con, lease_id, allowed, destination, *, now=None):
    if not isinstance(lease_id, str) or not re.fullmatch(r'[a-f0-9]{32}', lease_id):
        raise LeaseError('Invalid lease identity.')
    now = time.time() if now is None else now
    marks = ','.join('?' for _ in allowed)
    result = con.execute('UPDATE leases SET state=?,updated_at=? WHERE lease_id=? AND state IN (' + marks + ')',
                         (destination, now, lease_id, *allowed))
    if result.rowcount != 1:
        raise LeaseError('Lease state changed or the transition is unsafe.')


def start_requested(con, lease_id):
    _change(con, lease_id, ('RESERVED',), 'START_REQUESTED')


def start_confirmed(con, lease_id, *, pod_id, provider_status, provider_started_at):
    row = con.execute('SELECT pod_id,created_at FROM leases WHERE lease_id=?', (lease_id,)).fetchone()
    if (not row or row['pod_id'] != pod_id or provider_status != 'RUNNING' or
            not isinstance(provider_started_at, str) or
            not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)', provider_started_at)):
        raise LeaseError('Running Pod identity or provider start time was not confirmed.')
    try:
        started = datetime.fromisoformat(provider_started_at.replace('Z', '+00:00'))
        if started.tzinfo is None or started.utcoffset() != timezone.utc.utcoffset(started):
            raise ValueError()
        stamp = started.timestamp()
        if stamp < row['created_at'] - 60 or stamp > time.time() + 60:
            raise ValueError()
    except (ValueError, OverflowError, OSError):
        raise LeaseError('Provider start time is inconsistent with this lease.') from None
    result = con.execute('''UPDATE leases SET state='START_CONFIRMED',updated_at=?,provider_started_at=?
                            WHERE lease_id=? AND state='START_REQUESTED' ''',
                         (time.time(), provider_started_at, lease_id))
    if result.rowcount != 1:
        raise LeaseError('Lease state changed or the transition is unsafe.')


def action_uncertain(con, lease_id):
    _change(con, lease_id, ('START_REQUESTED', 'STOP_REQUESTED'), 'ACTION_UNCERTAIN')


def stop_requested(con, lease_id):
    _change(con, lease_id, ('START_CONFIRMED',), 'STOP_REQUESTED')


def close_confirmed(con, lease_id, *, pod_id, provider_status):
    row = con.execute('SELECT pod_id FROM leases WHERE lease_id=?', (lease_id,)).fetchone()
    if not row or row['pod_id'] != pod_id or provider_status != 'EXITED':
        raise LeaseError('Provider has not confirmed that the expected Pod is stopped.')
    # An ambiguous start/stop response cannot be made safe merely by one
    # observation: the original action might still arrive later.
    _change(con, lease_id, ('STOP_REQUESTED',), 'CLOSED')


def cancel_unused_reservation(con, lease_id):
    _change(con, lease_id, ('RESERVED',), 'CANCELLED')
