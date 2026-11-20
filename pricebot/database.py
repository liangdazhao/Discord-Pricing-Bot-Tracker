"""SQLite persistence and backwards-compatible schema migration."""
from contextlib import contextmanager
import sqlite3

from .validation import UserError, money


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS tracking_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, url TEXT,
                target_price REAL, html_class TEXT, last_price REAL, title TEXT)''')
            columns = {r[1] for r in db.execute('PRAGMA table_info(tracking_v2)')}
            for name, spec in [('currency', "TEXT NOT NULL DEFAULT 'USD'"),
                               ('checked_at', 'TEXT'), ('alerted', 'INTEGER NOT NULL DEFAULT 0')]:
                if name not in columns:
                    db.execute(f'ALTER TABLE tracking_v2 ADD COLUMN {name} {spec}')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def items(self, user_id=None):
        with self.connect() as db:
            if user_id is None:
                return db.execute('SELECT * FROM tracking_v2 ORDER BY id').fetchall()
            return db.execute('SELECT * FROM tracking_v2 WHERE user_id=? ORDER BY id', (user_id,)).fetchall()

    def get(self, item_id, user_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM tracking_v2 WHERE id=? AND user_id=?', (item_id, user_id)).fetchone()
        if row is None:
            raise UserError('Item not found. Use /list to see your items.')
        return row

    def add(self, user_id, url, target, product, limit):
        target = money(target)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM tracking_v2 WHERE user_id=? AND url=?', (user_id, url)).fetchone():
                raise UserError('You already track this URL. Use /target to change its target.')
            if db.execute('SELECT COUNT(*) FROM tracking_v2 WHERE user_id=?', (user_id,)).fetchone()[0] >= limit:
                raise UserError(f'You can track up to {limit} items. Remove one with /untrack first.')
            item_id = db.execute('''INSERT INTO tracking_v2
                (user_id,url,target_price,html_class,last_price,title,currency,checked_at,alerted)
                VALUES (?,?,?,'STRUCTURED',?,?,?,CURRENT_TIMESTAMP,?)''',
                (user_id,url,target,product.price,product.title,product.currency,int(product.price <= target))).lastrowid
        return self.get(item_id, user_id)

    def update(self, item_id, product):
        with self.connect() as db:
            row = db.execute('SELECT * FROM tracking_v2 WHERE id=?', (item_id,)).fetchone()
            if row is None:
                return None
            if product.currency != row['currency']:
                raise UserError('The page currency changed; remove and re-add this item to set a matching target.')
            db.execute('''UPDATE tracking_v2 SET last_price=?,title=?,checked_at=CURRENT_TIMESTAMP,
                alerted=CASE WHEN ? > target_price THEN 0 ELSE alerted END WHERE id=?''',
                (product.price,product.title,product.price,item_id))
        return self.get(item_id, row['user_id'])

    def mark_alerted(self, item_id):
        with self.connect() as db:
            db.execute('UPDATE tracking_v2 SET alerted=1 WHERE id=?', (item_id,))

    def target(self, item_id, user_id, target):
        target = money(target)
        self.get(item_id, user_id)
        with self.connect() as db:
            db.execute('UPDATE tracking_v2 SET target_price=?,alerted=0 WHERE id=? AND user_id=?', (target,item_id,user_id))
        return self.get(item_id, user_id)

    def remove(self, item_id, user_id):
        self.get(item_id, user_id)
        with self.connect() as db:
            db.execute('DELETE FROM tracking_v2 WHERE id=? AND user_id=?', (item_id,user_id))
