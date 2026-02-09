import sqlite3
import logging
from contextlib import contextmanager

DB_PATH = "users.db"

logger = logging.getLogger(__name__)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                phone_number TEXT UNIQUE,
                national_id TEXT,
                dob TEXT,
                bank_card_number TEXT,
                accepted_terms INTEGER,
                front_id TEXT,
                back_id TEXT,
                kyc_status TEXT DEFAULT 'Pending',
                reference_code TEXT,
                kyc_notified INT DEFAULT 0,
                password_hash TEXT,
                verification_level INTEGER DEFAULT 1
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS bank_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_number TEXT,
                UNIQUE(user_id, card_number),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_name TEXT,
                user_phone TEXT,
                verification_level INTEGER,
                exchange_pair TEXT,
                exchange_type TEXT,
                send_amount REAL,
                receive_amount REAL,
                reference_number TEXT UNIQUE,
                status TEXT DEFAULT 'Pending',
                timestamp TEXT,
                expires_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.commit()
    logger.info("Database initialized.")
