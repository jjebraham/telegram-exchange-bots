"""Private, human-approved voice registry and idempotent selection ledger.

This module does not call Instagram, Telegram, ElevenLabs, or a scheduler.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import wave

MODEL = 'eleven_v4'
SPEED = 1.5
SAMPLE_TEXT = ('این یک نمونه آزمایشی است. بیت کوین در سال ۲۰۲۶ با رشد ۲۹٪ به ۱۲۰٬۰۰۰ دلار رسید. '
               'در تاریخ ۲۰۲۶-۱۱-۰۸، ارزش بازار اتریوم ۳٫۵ میلیارد دلار بود.')
SAMPLE_HASH = hashlib.sha256(SAMPLE_TEXT.encode('utf-8')).hexdigest()
CANDIDATES = (
    ('Sahar', 'lIfJn0EyB8lHm00xiGY8'), ('Aylin', 'zagI4JNTfBvHyoNxaZWj'),
    ('Shahram', 'rNb3hdSf0n4ROIbYC8Bl'), ('Adrian', 'BognUUMX6W1qmZKB2TOw'),
    ('Mard', None), ('Mitra', None), ('Mahdi', None), ('Arman', None),
    ('Farshad', None), ('Amitis', None), ('Aran', None), ('Connery', None),
    ('Aramofen', None),
)
CRITERIA = ('pronunciation', 'naturalness', 'presenter_tone', 'clarity')
WEIGHTS = (Decimal('.35'), Decimal('.25'), Decimal('.25'), Decimal('.15'))


class RegistryError(ValueError):
    pass


def score(values):
    if not isinstance(values, dict) or set(values) != set(CRITERIA):
        raise RegistryError('All four review criteria are required.')
    total = Decimal(0)
    for criterion, weight in zip(CRITERIA, WEIGHTS):
        raw = values[criterion]
        if isinstance(raw, bool):
            raise RegistryError('Review scores must be between 0 and 10.')
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            raise RegistryError('Review scores must be between 0 and 10.') from None
        if not value.is_finite() or not Decimal(0) <= value <= Decimal(10):
            raise RegistryError('Review scores must be between 0 and 10.')
        total += value * weight
    return float(total * 10)


def connect(path):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise RegistryError('Unsafe voice registry path.')
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if os.name == 'posix':
        os.chmod(path.parent, 0o700)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    os.close(fd)
    if os.name == 'posix':
        os.chmod(path, 0o600)
    con = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript('''
        CREATE TABLE IF NOT EXISTS voices (
            name TEXT PRIMARY KEY COLLATE NOCASE, voice_id TEXT UNIQUE,
            available INTEGER NOT NULL DEFAULT 0, verified INTEGER NOT NULL DEFAULT 0,
            id_confirmed INTEGER NOT NULL DEFAULT 0,
            approved INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 0,
            serious_error INTEGER NOT NULL DEFAULT 0, scores TEXT, score REAL,
            notes TEXT NOT NULL DEFAULT '', sample_path TEXT, sample_sha256 TEXT,
            sample_text_hash TEXT, sample_model TEXT, sample_speed REAL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS selections (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT UNIQUE NOT NULL,
            voice_id TEXT NOT NULL, voice_name TEXT NOT NULL,
            status TEXT NOT NULL, media_id TEXT UNIQUE,
            selected_at REAL NOT NULL, published_at REAL
        );
    ''')
    return con


def seed(con):
    with con:
        for name, voice_id in CANDIDATES:
            con.execute('INSERT OR IGNORE INTO voices(name,voice_id,id_confirmed,updated_at) VALUES(?,?,?,?)',
                        (name, voice_id, int(voice_id is not None), time.time()))


def list_voices(con):
    return [dict(row) for row in con.execute('SELECT * FROM voices ORDER BY name COLLATE NOCASE')]


def register(con, name, voice_id=None):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9 _-]{0,79}', name):
        raise RegistryError('Invalid voice name.')
    if voice_id is not None and not re.fullmatch(r'[A-Za-z0-9]{20}', voice_id):
        raise RegistryError('Invalid ElevenLabs voice ID.')
    try:
        con.execute('INSERT INTO voices(name,voice_id,updated_at) VALUES(?,?,?)', (name, voice_id, time.time()))
    except sqlite3.IntegrityError:
        raise RegistryError('Voice name or ID already exists.') from None


def remove(con, name):
    # The selection ledger stores a snapshot independently of the registry.
    if con.execute('DELETE FROM voices WHERE name=?', (name,)).rowcount != 1:
        raise RegistryError('Voice was not found.')


def candidate_name_matches(candidate, actual):
    """Accept a complete leading name while rejecting prefixes of other names."""
    if not isinstance(candidate, str) or not isinstance(actual, str):
        return False
    return bool(re.match(r'^' + re.escape(candidate) + r'(?=$|[\s,\-–—:|])', actual.strip(), re.IGNORECASE))


def refresh_access(con, account_voices):
    """Process a complete account inventory; new name matches require ID confirmation."""
    if not isinstance(account_voices, list):
        raise RegistryError('A complete account voice inventory is required.')
    by_id = {}
    for entry in account_voices:
        if not isinstance(entry, dict):
            raise RegistryError('Invalid account voice inventory.')
        voice_id, name = entry.get('voice_id'), entry.get('name')
        if not isinstance(voice_id, str) or not re.fullmatch(r'[A-Za-z0-9]{20}', voice_id) or not isinstance(name, str):
            raise RegistryError('Invalid account voice inventory.')
        if voice_id in by_id:
            raise RegistryError('Duplicate voice ID in account inventory.')
        by_id[voice_id] = name
    con.execute('BEGIN IMMEDIATE')
    try:
        for row in con.execute('SELECT * FROM voices').fetchall():
            if row['voice_id']:
                # The four user-supplied IDs are the identity. Provider display
                # names often add descriptions and can change independently.
                matched = row['voice_id'] in by_id
                con.execute('UPDATE voices SET available=?,verified=?,updated_at=? WHERE name=?',
                            (int(matched), int(matched and row['id_confirmed']), time.time(), row['name']))
            else:
                matches = [voice_id for voice_id, actual in by_id.items()
                           if candidate_name_matches(row['name'], actual)]
                if len(matches) == 1:
                    try:
                        con.execute('UPDATE voices SET voice_id=?,available=1,verified=0,updated_at=? WHERE name=?',
                                    (matches[0], time.time(), row['name']))
                    except sqlite3.IntegrityError:
                        con.execute('UPDATE voices SET available=0,verified=0,updated_at=? WHERE name=?',
                                    (time.time(), row['name']))
                else:
                    con.execute('UPDATE voices SET available=0,verified=0,updated_at=? WHERE name=?',
                                (time.time(), row['name']))
        con.commit()
    except BaseException:
        con.rollback()
        raise


def confirm_voice_id(con, name, voice_id):
    row = con.execute('SELECT * FROM voices WHERE name=?', (name,)).fetchone()
    if not row or not row['available'] or row['voice_id'] != voice_id:
        raise RegistryError('The ID must match an available account voice.')
    con.execute('UPDATE voices SET id_confirmed=1,verified=1,updated_at=? WHERE name=?', (time.time(), name))


def save_sample(con, name, path, *, model=MODEL, speed=SPEED, text_hash=SAMPLE_HASH):
    row = con.execute('SELECT * FROM voices WHERE name=?', (name,)).fetchone()
    path = Path(path)
    if not row or not row['available'] or not row['voice_id']:
        raise RegistryError('An available account voice is required for a sample.')
    if model != MODEL or speed != SPEED or text_hash != SAMPLE_HASH:
        raise RegistryError('Sample must use the shared test text, model and speed.')
    if path.is_symlink() or not path.is_file() or not 100 <= path.stat().st_size <= 25_000_000:
        raise RegistryError('Sample file is unavailable or unsafe.')
    try:
        with wave.open(str(path), 'rb') as audio:
            duration = audio.getnframes() / audio.getframerate()
            if (audio.getnchannels() != 1 or audio.getframerate() != 24000 or
                    audio.getsampwidth() != 2 or not .1 <= duration <= 90):
                raise RegistryError('Sample audio format or duration is invalid.')
    except (wave.Error, OSError, ZeroDivisionError):
        raise RegistryError('Sample audio could not be verified.') from None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if (digest == row['sample_sha256'] and text_hash == row['sample_text_hash'] and
            model == row['sample_model'] and speed == row['sample_speed']):
        con.execute('UPDATE voices SET sample_path=?,updated_at=? WHERE name=?',
                    (str(path.resolve()), time.time(), name))
        return
    con.execute('''UPDATE voices SET sample_path=?,sample_sha256=?,sample_text_hash=?,sample_model=?,
        sample_speed=?,approved=0,enabled=0,scores=NULL,score=NULL,updated_at=? WHERE name=?''',
        (str(path.resolve()), digest, text_hash, model, speed, time.time(), name))


def review(con, name, scores, notes, *, serious_error, approved, enabled):
    if not all(isinstance(value, bool) for value in (serious_error, approved, enabled)):
        raise RegistryError('Review decisions must be explicit booleans.')
    if not isinstance(notes, str) or len(notes) > 3000:
        raise RegistryError('Review notes are invalid.')
    value = score(scores)
    row = con.execute('SELECT * FROM voices WHERE name=?', (name,)).fetchone()
    if not row:
        raise RegistryError('Voice was not found.')
    path = Path(row['sample_path']) if row['sample_path'] else None
    if (not path or path.is_symlink() or not path.is_file() or path.stat().st_size > 25_000_000 or
            hashlib.sha256(path.read_bytes()).hexdigest() != row['sample_sha256'] or
            row['sample_model'] != MODEL or row['sample_speed'] != SPEED or row['sample_text_hash'] != SAMPLE_HASH):
        raise RegistryError('The reviewed comparison sample is missing or has changed.')
    if approved and (value < 80 or serious_error or not row['available'] or not row['verified']):
        raise RegistryError('This voice does not meet the approval requirements.')
    if enabled and not approved:
        raise RegistryError('A voice must be explicitly approved before it is enabled.')
    con.execute('''UPDATE voices SET scores=?,score=?,notes=?,serious_error=?,approved=?,enabled=?,
        updated_at=? WHERE name=?''', (json.dumps(scores, sort_keys=True), value, notes,
        int(serious_error), int(approved), int(enabled), time.time(), name))
    return value


def select(con, job_id, override=None):
    if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', job_id):
        raise RegistryError('Invalid Reel job ID.')
    con.execute('BEGIN IMMEDIATE')
    try:
        existing = con.execute('SELECT * FROM selections WHERE job_id=?', (job_id,)).fetchone()
        if existing:
            if override is not None and override != existing['voice_id']:
                raise RegistryError('The Reel already has a different reserved voice.')
            if existing['status'] == 'failed':
                raise RegistryError('This Reel voice reservation has already failed.')
            if existing['status'] == 'reserved':
                still_eligible = con.execute('''SELECT 1 FROM voices WHERE voice_id=? AND available=1
                    AND verified=1 AND approved=1 AND enabled=1 AND serious_error=0 AND score>=80
                    AND sample_model=? AND sample_speed=? AND sample_text_hash=?''',
                    (existing['voice_id'], MODEL, SPEED, SAMPLE_HASH)).fetchone()
                if not still_eligible:
                    raise RegistryError('The reserved voice is no longer approved and available.')
            con.commit()
            return dict(existing)
        eligible = con.execute('''SELECT * FROM voices WHERE available=1 AND verified=1 AND approved=1
            AND enabled=1 AND serious_error=0 AND score>=80 AND sample_model=? AND sample_speed=?
            AND sample_text_hash=? AND voice_id IS NOT NULL ORDER BY voice_id''',
            (MODEL, SPEED, SAMPLE_HASH)).fetchall()
        if override is not None:
            eligible = [row for row in eligible if row['voice_id'] == override]
        elif len(eligible) > 1:
            last_published = con.execute("SELECT voice_id FROM selections WHERE status='published' ORDER BY published_at DESC,sequence DESC LIMIT 1").fetchone()
            last_pending = con.execute("SELECT voice_id FROM selections WHERE status='reserved' ORDER BY sequence DESC LIMIT 1").fetchone()
            excluded = {row['voice_id'] for row in (last_published, last_pending) if row}
            eligible = [row for row in eligible if row['voice_id'] not in excluded]
        if not eligible:
            raise RegistryError('No approved, enabled and available voice is eligible.')
        chosen = secrets.choice(eligible)
        con.execute('INSERT INTO selections(job_id,voice_id,voice_name,status,selected_at) VALUES(?,?,?,?,?)',
                    (job_id, chosen['voice_id'], chosen['name'], 'reserved', time.time()))
        row = con.execute('SELECT * FROM selections WHERE job_id=?', (job_id,)).fetchone()
        con.commit()
        return dict(row)
    except BaseException:
        con.rollback()
        raise


def mark_failed(con, job_id):
    """Release a reservation only after the Reel is confirmed failed."""
    con.execute("UPDATE selections SET status='failed' WHERE job_id=? AND status='reserved'", (job_id,))


def mark_published(con, job_id, media_id):
    if not isinstance(media_id, str) or not re.fullmatch(r'[0-9]{5,40}', media_id):
        raise RegistryError('A confirmed Instagram media ID is required.')
    con.execute('BEGIN IMMEDIATE')
    try:
        row = con.execute('SELECT * FROM selections WHERE job_id=?', (job_id,)).fetchone()
        if not row:
            raise RegistryError('No voice reservation exists for this Reel.')
        if row['status'] == 'published' and row['media_id'] != media_id:
            raise RegistryError('The Reel already has a different confirmed media ID.')
        if row['status'] != 'published':
            con.execute("UPDATE selections SET status='published',media_id=?,published_at=? WHERE job_id=?",
                        (media_id, time.time(), job_id))
        con.commit()
    except BaseException:
        con.rollback()
        raise

