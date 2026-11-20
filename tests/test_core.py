from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pricebot.models import Product
from pricebot.database import Store
from pricebot.validation import UserError, money, normalize_url


class ValidationTests(unittest.TestCase):
    def test_reject_invalid_prices(self):
        for value in (0, -1, 'NaN', 'Infinity', None, 'free', 0.001, 1e20):
            with self.subTest(value=value), self.assertRaises(UserError):
                money(value)

    def test_money_rounding(self):
        self.assertEqual(money('19.999'), 20)

    def test_bad_urls(self):
        for value in ('file:///etc/passwd', 'http://localhost/x', 'http://127.0.0.1/',
                      'https://user:pass@example.com', 'https://example.com:8080',
                      'https://192.168.0.1/', 'https://example.com/a b'):
            with self.subTest(value=value), self.assertRaises(UserError):
                normalize_url(value)

    def test_url_normalization_preserves_query(self):
        self.assertEqual(normalize_url('https://EXAMPLE.com/product?a=1#x'), 'https://example.com/product?a=1')

    def test_invalid_extraction(self):
        for data in ({'title': 'Product', 'price': None, 'currency': 'USD'},
                     {'title': '', 'price': 1, 'currency': 'USD'},
                     {'title': 'Product', 'price': 1, 'currency': '$'}):
            with self.assertRaises(UserError):
                Product.parse(data)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'tracker.db'
        self.store = Store(self.path)
        self.product = Product('Example product', 100, 'USD')

    def tearDown(self):
        self.temp.cleanup()

    def add(self, url='https://example.com/product', user=1):
        return self.store.add(user, url, 80, self.product, 2)

    def test_ownership(self):
        row = self.add()
        for operation in (lambda: self.store.get(row['id'], 2),
                          lambda: self.store.remove(row['id'], 2),
                          lambda: self.store.target(row['id'], 2, 10)):
            with self.assertRaises(UserError):
                operation()
        self.assertEqual(len(self.store.items(1)), 1)

    def test_duplicates_and_limit(self):
        self.add()
        with self.assertRaises(UserError):
            self.add()
        self.add('https://example.com/2')
        with self.assertRaises(UserError):
            self.add('https://example.com/3')
        self.add(user=2)

    def test_ids_not_reused(self):
        row = self.add()
        self.store.remove(row['id'], 1)
        self.assertGreater(self.add()['id'], row['id'])

    def test_alert_rearms_only_above_target(self):
        row = self.add()
        low = Product('Example', 70, 'USD')
        self.assertFalse(self.store.update(row['id'], low)['alerted'])
        self.store.mark_alerted(row['id'])
        self.assertTrue(self.store.update(row['id'], low)['alerted'])
        self.assertFalse(self.store.update(row['id'], self.product)['alerted'])
        self.assertFalse(self.store.update(row['id'], low)['alerted'])

    def test_currency_mismatch_keeps_old_price(self):
        row = self.add()
        with self.assertRaises(UserError):
            self.store.update(row['id'], Product('Example', 50, 'EUR'))
        self.assertEqual(self.store.get(row['id'], 1)['last_price'], 100)

    def test_target_change_rearms(self):
        row = self.add()
        self.store.mark_alerted(row['id'])
        row = self.store.target(row['id'], 1, 120)
        self.assertFalse(row['alerted'])
        self.assertEqual(row['target_price'], 120)

    def test_legacy_migration(self):
        legacy = Path(self.temp.name) / 'legacy.db'
        with closing(sqlite3.connect(legacy)) as db:
            db.execute('CREATE TABLE tracking_v2 (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,url TEXT,target_price REAL,html_class TEXT,last_price REAL,title TEXT)')
            db.execute("INSERT INTO tracking_v2 VALUES (7,1,'https://example.com',80,'AI_PARSED',100,'Old')")
            db.commit()
        store = Store(legacy)
        row = store.get(7, 1)
        self.assertEqual(row['title'], 'Old')
        self.assertEqual(row['currency'], 'USD')
        Store(legacy)  # Repeated migrations must preserve records.
        self.assertEqual(len(store.items()), 1)
