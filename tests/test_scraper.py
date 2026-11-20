import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pricebot.models import Product
from pricebot.database import Store
from pricebot.validation import UserError
from pricebot.scraper import Scraper
from pricebot.cogs.tracker import TrackerCog


class ScraperTests(unittest.IsolatedAsyncioTestCase):
    def scraper(self, data):
        scraper = Scraper(None, 'fake', 'fake', 'test-model')
        scraper.request = AsyncMock(side_effect=[
            '<html><h1>Example product name</h1><p>Buy now for USD 19.99 today</p></html>',
            json.dumps({'candidates': [{'content': {'parts': [{'text': json.dumps(data)}]}}]})])
        return scraper

    async def test_concurrent_calls_share_cache(self):
        scraper = self.scraper({'title': 'Example', 'price': 19.99, 'currency': 'USD'})
        results = await asyncio.gather(scraper.scrape('https://example.com'), scraper.scrape('https://example.com'))
        self.assertEqual(results[0].price, 19.99)
        self.assertEqual(results[0], results[1])
        self.assertEqual(scraper.request.await_count, 2)

    async def test_unknown_price_is_not_zero(self):
        scraper = self.scraper({'title': 'Example', 'price': None, 'currency': 'USD'})
        with self.assertRaises(UserError):
            await scraper.scrape('https://example.com')
        self.assertFalse(scraper.cache)

    async def test_prompt_removes_scripts(self):
        self.assertEqual(Scraper.page_text('<script>malicious</script><p>Product</p>'), 'Product')


class AlertTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_failure_retries_and_success_suppresses_duplicates(self):
        from collections import defaultdict
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'test.db')
            row = store.add(1, 'https://example.com/', 80, Product('Example', 100, 'USD'), 5)
            user = SimpleNamespace(send=AsyncMock(side_effect=[RuntimeError('DM blocked'), None]))
            bot = SimpleNamespace(store=store, item_locks=defaultdict(asyncio.Lock),
                                  scraper=SimpleNamespace(scrape=AsyncMock(return_value=Product('Example', 70, 'USD'))),
                                  fetch_user=AsyncMock(return_value=user))
            cog = TrackerCog(bot)
            with self.assertRaises(RuntimeError):
                await cog.refresh(row['id'], 1, notify=True)
            self.assertFalse(store.get(row['id'], 1)['alerted'])
            await cog.refresh(row['id'], 1, notify=True)
            await cog.refresh(row['id'], 1, notify=True)
            self.assertEqual(user.send.await_count, 2)
            self.assertTrue(store.get(row['id'], 1)['alerted'])

class RequestTests(unittest.IsolatedAsyncioTestCase):
    def response(self, status, chunks):
        class Body:
            async def iter_chunked(self, size):
                for chunk in chunks:
                    yield chunk
        response = SimpleNamespace(status=status, content=Body())
        context = AsyncMock()
        context.__aenter__.return_value = response
        return context

    async def test_http_auth_error_does_not_retry_or_leak_body(self):
        from unittest.mock import Mock
        session = SimpleNamespace(request=Mock(return_value=self.response(401, [b'secret API key'])))
        scraper = Scraper(session, 'fake', 'fake', 'test')
        with self.assertRaises(UserError) as caught:
            await scraper.request('GET', 'https://example.com')
        self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(session.request.call_count, 1)

    async def test_transient_failure_retries(self):
        from unittest.mock import Mock, patch
        session = SimpleNamespace(request=Mock(side_effect=[self.response(503, []), self.response(200, [b'ok'])]))
        scraper = Scraper(session, 'fake', 'fake', 'test')
        with patch('pricebot.scraper.asyncio.sleep', new_callable=AsyncMock):
            self.assertEqual(await scraper.request('GET', 'https://example.com'), 'ok')
        self.assertEqual(session.request.call_count, 2)

    async def test_response_size_limit(self):
        from unittest.mock import Mock
        session = SimpleNamespace(request=Mock(return_value=self.response(200, [b'x' * 5_000_001])))
        with self.assertRaises(UserError):
            await Scraper(session, 'fake', 'fake', 'test').request('GET', 'https://example.com')


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_commands_and_clean_shutdown_without_login(self):
        import os
        from unittest.mock import patch
        from pricebot.bot import TrackerBot
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DATABASE_PATH': str(Path(folder) / 'test.db')}):
                async with TrackerBot() as bot:
                    await bot.load_extension('pricebot.cogs.search')
                    await bot.load_extension('pricebot.cogs.tracker')
                    names = {command.name for command in bot.tree.get_commands()}
                    self.assertEqual(names, {'check', 'track', 'check_now', 'list', 'price', 'target', 'untrack', 'checks_left'})
