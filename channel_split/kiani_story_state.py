"""Read successful 12:10 post receipts and keep per-channel story receipts."""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import os
from pathlib import Path
import secrets
import sqlite3
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo('Europe/Istanbul')
SOURCE = 'exchangekiani'
TARGETS = ('alanchande_com', 'exchangekiani')
STORY_PERIOD = 48 * 3600
SLOT = time(12, 10)


@dataclass(frozen=True)
class SourceReceipt:
    local_date: str
    message_id: int
    sent_at: datetime


def in_daily_window(now: datetime) -> bool:
    if now.tzinfo is None:
        raise ValueError('Story worker time must be timezone-aware')
    local = now.astimezone(ISTANBUL)
    start = datetime.combine(local.date(), SLOT, ISTANBUL)
    return start <= local < start + timedelta(minutes=20)


def select_receipt(db_path: Path, now: datetime) -> SourceReceipt | None:
    """Only a confirmed same-day source in the 12:10 posting slot can qualify."""
    if not in_daily_window(now) or not db_path.is_file():
        return None
    local = now.astimezone(ISTANBUL)
    start = datetime.combine(local.date(), SLOT, ISTANBUL)
    with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        rows = db.execute('SELECT sent_at,message_id,source_chat_id FROM kiani_forward_source_messages '
                          'WHERE source_key=? AND local_date=?', ('kiani-rates', local.date().isoformat())).fetchall()
    valid = []
    for stamp, message_id, source_chat in rows:
        try:
            sent = datetime.fromisoformat(stamp)
            number = int(message_id)
        except (ValueError, TypeError):
            continue
        if sent.tzinfo is None or str(source_chat).lower() != '@' + SOURCE or number <= 0:
            continue
        sent = sent.astimezone(ISTANBUL)
        if start <= sent < start + timedelta(minutes=12) and sent <= local:
            valid.append(SourceReceipt(local.date().isoformat(), number, sent))
    return min(valid, key=lambda item: item.sent_at) if valid else None


class StoryState:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == 'posix':
            os.chmod(path.parent, 0o700)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS worker_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS daily_stories (
                local_date TEXT NOT NULL,target TEXT NOT NULL,source_id INTEGER NOT NULL,
                random_id INTEGER NOT NULL,status TEXT NOT NULL,story_id INTEGER,
                reason TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL,
                PRIMARY KEY(local_date,target))''')
        if os.name == 'posix':
            os.chmod(path, 0o600)

    def connect(self):
        return closing(sqlite3.connect(self.path, isolation_level=None))

    def ensure(self, source: SourceReceipt):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for target in TARGETS:
                db.execute('INSERT OR IGNORE INTO daily_stories '
                           '(local_date,target,source_id,random_id,status,updated_at) VALUES(?,?,?,?,?,?)',
                           (source.local_date, target, source.message_id, secrets.randbelow(2**63 - 1) + 1,
                            'ready', datetime.now(timezone.utc).isoformat()))
            rows = db.execute('SELECT source_id FROM daily_stories WHERE local_date=?', (source.local_date,)).fetchall()
            if any(row[0] != source.message_id for row in rows):
                db.execute('ROLLBACK')
                raise ValueError('The first confirmed daily story source cannot be replaced')
            db.execute('COMMIT')

    def jobs(self, local_date: str):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM daily_stories WHERE local_date=? ORDER BY target', (local_date,))]

    def defer(self, seconds: int, now: datetime):
        until = now + timedelta(seconds=max(1, seconds))
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO worker_meta(key,value) VALUES(?,?)',
                       ('not_before', until.astimezone(timezone.utc).isoformat()))

    def cooling_down(self, now: datetime) -> bool:
        with self.connect() as db:
            row = db.execute('SELECT value FROM worker_meta WHERE key=?', ('not_before',)).fetchone()
        return bool(row and now < datetime.fromisoformat(row[0]))

    def mark(self, day: str, target: str, status: str, *, story_id=None, reason=''):
        if target not in TARGETS or status not in {'ready', 'attempting', 'retry', 'sent', 'blocked', 'uncertain'}:
            raise ValueError('Unknown story state transition')
        with self.connect() as db:
            db.execute('UPDATE daily_stories SET status=?,story_id=?,reason=?,updated_at=? WHERE local_date=? AND target=?',
                       (status, story_id, reason[:160], datetime.now(timezone.utc).isoformat(), day, target))
