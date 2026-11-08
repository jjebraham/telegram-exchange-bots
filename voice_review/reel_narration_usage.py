"""Durable character accounting; submitted text is not an ElevenLabs invoice."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time


def schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS narration_requests(
        cache_key TEXT PRIMARY KEY, voice_id TEXT NOT NULL, model TEXT NOT NULL,
        characters INTEGER NOT NULL, requested_at REAL NOT NULL, status TEXT NOT NULL,
        response_audio BLOB, response_alignment TEXT)''')


def reserve(con, cache_key, voice_id, model, characters, *, now=None):
    """Caller holds BEGIN IMMEDIATE. Unconfirmed requests cannot be retried."""
    now = time.time() if now is None else now
    old = con.execute('SELECT * FROM narration_requests WHERE cache_key=?', (cache_key,)).fetchone()
    if old:
        if old[5] == 'received':
            return old[6], json.loads(old[7])
        raise ValueError('A previous narration request needs review before another billable request.')
    raw = os.environ.get('REEL_ELEVENLABS_MONTHLY_CHAR_LIMIT', '')
    if raw:
        if not raw.isdigit() or not 1 <= int(raw) <= 100_000_000:
            raise ValueError('The monthly narration character limit is invalid.')
        dt = datetime.fromtimestamp(now, timezone.utc)
        start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        used = con.execute('SELECT COALESCE(SUM(characters),0) FROM narration_requests WHERE requested_at>=?', (start,)).fetchone()[0]
        if used + characters > int(raw):
            raise ValueError('The local monthly narration character limit would be exceeded.')
    con.execute('INSERT INTO narration_requests VALUES(?,?,?,?,?,?,NULL,NULL)',
                (cache_key, voice_id, model, characters, now, 'requested'))
    return None


def report(path, *, now=None):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Unsafe narration accounting path.')
    if not path.exists():
        return {'submitted_characters': 0, 'requests': 0, 'unconfirmed_requests': 0, 'history_available': False}
    dt = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        found = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='narration_requests'").fetchone()
        if not found:
            return {'submitted_characters': 0, 'requests': 0, 'unconfirmed_requests': 0, 'history_available': False}
        rows = con.execute('SELECT characters,status FROM narration_requests WHERE requested_at>=?', (start,)).fetchall()
        return {'month_utc': dt.strftime('%Y-%m'), 'submitted_characters': sum(r[0] for r in rows),
                'requests': len(rows), 'unconfirmed_requests': sum(r[1] in ('requested', 'uncertain') for r in rows),
                'history_available': True, 'billing_note': 'Characters submitted since accounting was installed; not actual credits or final charges.'}
    finally:
        con.close()
