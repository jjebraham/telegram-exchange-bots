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
                receipt_photo_url TEXT,
                receipt_description TEXT,
                payment_link TEXT,
                status_updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS faqs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS rate_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                toman_to_tl_factor REAL DEFAULT 0.995,
                tl_to_toman_factor REAL DEFAULT 0.94,
                buy_usdt_factor REAL DEFAULT 1.01,
                sell_usdt_factor REAL DEFAULT 0.99,
                usdt_to_lira_factor REAL DEFAULT 0.98,
                lira_to_usdt_factor REAL DEFAULT 1.02,
                foreign_payment_factor REAL DEFAULT 1.05,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            INSERT OR IGNORE INTO rate_settings
            (id, toman_to_tl_factor, tl_to_toman_factor, buy_usdt_factor, sell_usdt_factor, usdt_to_lira_factor, lira_to_usdt_factor, foreign_payment_factor)
            VALUES (1, 0.995, 0.94, 1.01, 0.99, 0.98, 1.02, 1.05)
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                details TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL,
                channel TEXT NOT NULL,
                code TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS ehraz_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT,
                national_id TEXT,
                endpoint TEXT NOT NULL,
                request_payload TEXT,
                response_payload TEXT,
                success INTEGER DEFAULT 0,
                error_message TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS sms_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT,
                provider TEXT DEFAULT 'ghasedak',
                request_payload TEXT,
                response_payload TEXT,
                success INTEGER DEFAULT 0,
                error_message TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone_number TEXT,
                action TEXT NOT NULL,
                source TEXT DEFAULT 'miniapp',
                details TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Backward-compatible migrations for existing DBs
        existing_transaction_columns = {
            row["name"] for row in c.execute("PRAGMA table_info(transactions)").fetchall()
        }
        if "receipt_photo_url" not in existing_transaction_columns:
            c.execute("ALTER TABLE transactions ADD COLUMN receipt_photo_url TEXT")
        if "receipt_description" not in existing_transaction_columns:
            c.execute("ALTER TABLE transactions ADD COLUMN receipt_description TEXT")
        if "payment_link" not in existing_transaction_columns:
            c.execute("ALTER TABLE transactions ADD COLUMN payment_link TEXT")
        if "status_updated_at" not in existing_transaction_columns:
            c.execute("ALTER TABLE transactions ADD COLUMN status_updated_at TEXT")
        conn.commit()
    logger.info("Database initialized.")
