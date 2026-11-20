"""Run with python bot.py after configuring .env."""
import asyncio
from collections import defaultdict
import logging
import os
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from .database import Store
from .validation import UserError
from .scraper import Scraper

BASE = Path(__file__).resolve().parent.parent
log = logging.getLogger('pricebot')


class TrackerBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=discord.Intents.default(),
                         allowed_mentions=discord.AllowedMentions.none())
        self.session = None
        self.store = Store(os.getenv('DATABASE_PATH', str(BASE / 'tracker.db')))
        self.max_items = int(os.getenv('MAX_ITEMS_PER_USER', '25'))
        self.check_hours = float(os.getenv('CHECK_INTERVAL_HOURS', '9'))
        if self.max_items < 1 or not 0.25 <= self.check_hours <= 8760:
            raise ValueError('MAX_ITEMS_PER_USER must be positive; CHECK_INTERVAL_HOURS must be between 0.25 and 8760.')
        self.item_locks = defaultdict(asyncio.Lock)
        self.tree.on_error = self.command_error

    async def setup_hook(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90))
        self.scraper = Scraper(self.session, os.environ['ZENROWS_API_KEY'],
                               os.environ['GEMINI_API_KEY'], os.getenv('GEMINI_MODEL', 'gemini-3.8-flash'))
        for extension in ('pricebot.cogs.search', 'pricebot.cogs.tracker'):
            await self.load_extension(extension)
        guild_id = os.getenv('DISCORD_GUILD_ID')
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        log.info('Registered %d commands', len(synced))

    async def on_ready(self):
        log.info('Connected as %s', self.user)

    async def close(self):
        for name in list(self.extensions):
            await self.unload_extension(name)
        if self.session:
            await self.session.close()
        await super().close()

    async def command_error(self, interaction, error):
        cause = getattr(error, 'original', error)
        if isinstance(cause, UserError):
            message = str(cause)
        elif isinstance(error, app_commands.CommandOnCooldown):
            message = f'Please wait {error.retry_after:.0f} seconds before trying again.'
        elif isinstance(error, app_commands.CheckFailure):
            message = 'You do not have permission to use this command.'
        else:
            # Avoid logging provider exception text, which may contain API credentials.
            log.error('Command %s failed (%s)', interaction.command.name if interaction.command else '?', type(cause).__name__)
            message = 'Something went wrong. Please try again or contact the bot owner.'
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def main():
    load_dotenv(BASE / '.env')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    missing = [name for name in ('DISCORD_TOKEN', 'ZENROWS_API_KEY', 'GEMINI_API_KEY') if not os.getenv(name)]
    if missing:
        raise SystemExit('Missing configuration: ' + ', '.join(missing) + '. Copy .env.example to .env and fill in your keys.')
    bot = TrackerBot()
    bot.run(os.environ['DISCORD_TOKEN'], log_handler=None)


if __name__ == '__main__':
    main()
