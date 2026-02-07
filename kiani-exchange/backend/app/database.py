import sqlite3
import logging
from .config import DATABASE_PATH

logger = logging.getLogger(__name__)


def get_db():
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
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
            accepted_terms INTEGER DEFAULT 0,
            front_id TEXT,
            back_id TEXT,
            kyc_status TEXT DEFAULT 'Pending',
            reference_code TEXT,
            kyc_notified INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            suspended INTEGER DEFAULT 0
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
        CREATE TABLE IF NOT EXISTS faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_fa TEXT NOT NULL,
            answer_fa TEXT NOT NULL,
            question_en TEXT DEFAULT '',
            answer_en TEXT DEFAULT '',
            category TEXT DEFAULT 'general',
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT NOT NULL,
            from_currency TEXT NOT NULL,
            to_currency TEXT NOT NULL,
            amount REAL NOT NULL,
            rate REAL NOT NULL,
            total REAL NOT NULL,
            fee REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            reference_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS chatbot_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            confidence REAL DEFAULT 0,
            helpful INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            target TEXT DEFAULT 'all',
            sent_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_user TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")
