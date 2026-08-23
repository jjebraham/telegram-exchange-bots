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

        # KYC invariant: registration completes Level 1 only.  A user must stay
        # Pending until a Level 2 submission is explicitly approved by an admin.
        # Older registration code inserted ('Approved', 1), which made a fresh
        # account look fully verified even though no Level 2 documents had been
        # reviewed. Repair those rows and enforce the invariant at DB level so a
        # future regression in an API handler cannot silently auto-approve them.
        c.execute(
            """
            UPDATE users
               SET kyc_status = 'Pending', verification_level = 1
             WHERE COALESCE(verification_level, 1) <= 1
               AND LOWER(COALESCE(kyc_status, '')) = 'approved'
            """
        )
        c.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_users_level1_kyc_guard_insert
            AFTER INSERT ON users
            WHEN COALESCE(NEW.verification_level, 1) <= 1
             AND LOWER(COALESCE(NEW.kyc_status, '')) = 'approved'
            BEGIN
                UPDATE users
                   SET kyc_status = 'Pending', verification_level = 1
                 WHERE id = NEW.id;
            END
            """
        )
        c.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_users_level1_kyc_guard_update
            AFTER UPDATE OF kyc_status, verification_level ON users
            WHEN COALESCE(NEW.verification_level, 1) <= 1
             AND LOWER(COALESCE(NEW.kyc_status, '')) = 'approved'
            BEGIN
                UPDATE users
                   SET kyc_status = 'Pending', verification_level = 1
                 WHERE id = NEW.id;
            END
            """
        )

        conn.commit()
    logger.info("Database initialized.")