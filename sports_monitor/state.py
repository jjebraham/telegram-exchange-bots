"""SQLite observations and an outbox that quarantines ambiguous deliveries."""
import json
import sqlite3
import time
from .model import Product, qualifies, change_reason


class State:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY, product_key TEXT NOT NULL, observed_at INTEGER NOT NULL,
            sale INTEGER NOT NULL, payload TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS observations_key_time ON observations(product_key, observed_at);
          CREATE TABLE IF NOT EXISTS posts (
            destination TEXT NOT NULL, product_key TEXT NOT NULL, posted_at INTEGER NOT NULL,
            payload TEXT NOT NULL, message_id INTEGER NOT NULL,
            PRIMARY KEY(destination, product_key));
          CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY, destination TEXT NOT NULL, created_at INTEGER NOT NULL,
            text TEXT NOT NULL, products TEXT NOT NULL, status TEXT NOT NULL,
            message_id INTEGER);
          CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY, started_at INTEGER NOT NULL, finished_at INTEGER, report TEXT);
        ''')

    def history(self, product, now):
        row = self.db.execute('SELECT MIN(sale), COUNT(DISTINCT observed_at) FROM observations WHERE product_key=? AND observed_at>=? AND observed_at<?',
                              (product.key, now - 30 * 86400, now)).fetchone()
        return row[0], row[1]

    def previous(self, key):
        row = self.db.execute('SELECT payload FROM observations WHERE product_key=? ORDER BY id DESC LIMIT 1', (key,)).fetchone()
        return Product.loads(row[0]) if row else None

    def reason(self, product, destination, now):
        if not qualifies(product, *self.history(product, now)):
            return None
        pending = self.db.execute("SELECT products FROM outbox WHERE destination=? AND status IN ('sending','unknown')", (destination,)).fetchall()
        if any(product.key == Product.loads(p).key for row in pending for p in json.loads(row[0])):
            return None
        row = self.db.execute('SELECT payload, posted_at FROM posts WHERE destination=? AND product_key=?', (destination, product.key)).fetchone()
        posted = Product.loads(row[0]) if row else None
        previous = self.previous(product.key)
        restock_seen = False
        if row:
            observations = self.db.execute('SELECT payload FROM observations WHERE product_key=? AND observed_at>?', (product.key, row[1])).fetchall()
            restock_seen = any(not Product.loads(o[0]).sizes for o in observations)
        return change_reason(product, posted, previous, elapsed=now - row[1] if row else 0, restock_seen=restock_seen)

    def observe(self, product):
        with self.db:
            self.db.execute('INSERT INTO observations(product_key,observed_at,sale,payload) VALUES(?,?,?,?)',
                            (product.key, product.observed_at, product.sale, product.dumps()))

    def reserve(self, destination, text, products):
        with self.db:
            cursor = self.db.execute("INSERT INTO outbox(destination,created_at,text,products,status) VALUES(?,?,?,?,'sending')",
                                     (destination, int(time.time()), text, json.dumps([p.dumps() for p in products])))
            return cursor.lastrowid

    def delivered(self, batch, message_id, now):
        with self.db:
            row = self.db.execute('SELECT * FROM outbox WHERE id=?', (batch,)).fetchone()
            for payload in json.loads(row['products']):
                p = Product.loads(payload)
                self.db.execute('INSERT OR REPLACE INTO posts VALUES(?,?,?,?,?)', (row['destination'], p.key, now, payload, message_id))
            self.db.execute("UPDATE outbox SET status='sent', message_id=? WHERE id=?", (message_id, batch))

    def failed(self, batch, ambiguous):
        with self.db:
            self.db.execute('UPDATE outbox SET status=? WHERE id=?', ('unknown' if ambiguous else 'failed', batch))

    def resolve(self, batch, message_id=None):
        row = self.db.execute("SELECT id FROM outbox WHERE id=? AND status IN ('sending','unknown')", (batch,)).fetchone()
        if not row:
            raise ValueError('Batch is not awaiting reconciliation')
        if message_id is not None:
            self.delivered(batch, message_id, int(time.time()))
        else:
            self.failed(batch, False)

    def known_urls(self, store):
        rows = self.db.execute('SELECT payload FROM observations WHERE id IN (SELECT MAX(id) FROM observations GROUP BY product_key)').fetchall()
        return [p.url for row in rows if (p := Product.loads(row[0])).store == store]

    def close(self):
        self.db.close()
