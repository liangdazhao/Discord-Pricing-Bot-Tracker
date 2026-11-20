import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..validation import UserError, money, normalize_url
from ..embeds import row_embed

log = logging.getLogger('pricebot.tracker')


class TrackerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.price_check_loop.change_interval(hours=self.bot.check_hours)
        self.price_check_loop.start()

    async def cog_unload(self):
        task = self.price_check_loop.get_task()
        self.price_check_loop.cancel()
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def refresh(self, item_id, user_id, notify=False):
        async with self.bot.item_locks[item_id]:
            row = self.bot.store.get(item_id, user_id)
            product = await self.bot.scraper.scrape(row['url'])
            updated = self.bot.store.update(item_id, product)
            if updated is None:
                raise UserError('This item was removed during the price check.')
            if product.price <= updated['target_price'] and not updated['alerted']:
                if notify:
                    user = await self.bot.fetch_user(user_id)
                    await user.send('🔔 Your target price has been reached!', embed=row_embed(updated))
                    self.bot.store.mark_alerted(item_id)
                # Manual checks leave the alert pending for the scheduled DM.
            return updated

    @tasks.loop(hours=9)
    async def price_check_loop(self):
        try:
            rows = self.bot.store.items()
            for row in rows:
                try:
                    await self.refresh(row['id'], row['user_id'], notify=True)
                except Exception as error:
                    log.warning('Check failed for item %s (%s)', row['id'], type(error).__name__)
                await asyncio.sleep(3)
        except Exception as error:
            log.error('Scheduled pass failed (%s); will retry next interval', type(error).__name__)

    @price_check_loop.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name='track', description='Track a product; target uses the product’s currency')
    @app_commands.checks.cooldown(1, 30, key=lambda i: i.user.id)
    async def track(self, interaction: discord.Interaction, url: str, target_price: float):
        url, target = normalize_url(url), money(target_price)
        rows = self.bot.store.items(interaction.user.id)
        if any(row['url'] == url for row in rows):
            raise UserError('You already track this URL. Use /target to change its target.')
        if len(rows) >= self.bot.max_items:
            raise UserError(f'Your limit is {self.bot.max_items} items. Remove one with /untrack first.')
        await interaction.response.defer(ephemeral=True)
        product = await self.bot.scraper.scrape(url)
        row = self.bot.store.add(interaction.user.id, url, target, product, self.bot.max_items)
        await interaction.followup.send('✅ Tracking added. Target uses the currency shown below.', embed=row_embed(row), ephemeral=True)

    @app_commands.command(name='check_now', description='Refresh a tracked price (results may be cached for 60 seconds)')
    @app_commands.checks.cooldown(1, 30, key=lambda i: i.user.id)
    async def check_now(self, interaction: discord.Interaction, item_id: int):
        self.bot.store.get(item_id, interaction.user.id)
        await interaction.response.defer(ephemeral=True)
        row = await self.refresh(item_id, interaction.user.id)
        await interaction.followup.send(embed=row_embed(row), ephemeral=True)

    @app_commands.command(name='list', description='List your tracked products, ten per page')
    async def list_tracked(self, interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1):
        rows = self.bot.store.items(interaction.user.id)
        pages = max(1, (len(rows) + 9) // 10)
        if page > pages:
            raise UserError(f'Choose a page between 1 and {pages}.')
        embed = discord.Embed(title=f'Your tracked products • page {page}/{pages}', color=discord.Color.blue())
        for row in rows[(page - 1) * 10:page * 10]:
            embed.add_field(name=f"#{row['id']} — {discord.utils.escape_markdown(row['title'] or 'Unknown')[:120]}",
                            value=f"Target: {row['currency']} {row['target_price']:,.2f}", inline=False)
        if not rows:
            embed.description = 'No tracked products yet. Add one with /track.'
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='price', description='Show the last saved price without making a paid request')
    async def price(self, interaction: discord.Interaction, item_id: int):
        await interaction.response.send_message(embed=row_embed(self.bot.store.get(item_id, interaction.user.id)), ephemeral=True)

    @app_commands.command(name='target', description='Change a tracked product’s target price')
    async def target(self, interaction: discord.Interaction, item_id: int, target_price: float):
        money(target_price)
        self.bot.store.get(item_id, interaction.user.id)
        await interaction.response.defer(ephemeral=True)
        async with self.bot.item_locks[item_id]:
            row = self.bot.store.target(item_id, interaction.user.id, target_price)
        await interaction.followup.send('Target updated.', embed=row_embed(row), ephemeral=True)

    @app_commands.command(name='untrack', description='Stop tracking one of your products')
    async def untrack(self, interaction: discord.Interaction, item_id: int):
        self.bot.store.get(item_id, interaction.user.id)
        await interaction.response.defer(ephemeral=True)
        async with self.bot.item_locks[item_id]:
            self.bot.store.remove(item_id, interaction.user.id)
        await interaction.followup.send(f'Removed item #{item_id}.', ephemeral=True)

    @app_commands.command(name='checks_left', description='Bot owner: inspect ZenRows account credit information')
    @app_commands.checks.cooldown(1, 60, key=lambda i: i.user.id)
    async def checks_left(self, interaction: discord.Interaction):
        if not await self.bot.is_owner(interaction.user):
            raise UserError('Only the bot owner can view account usage.')
        await interaction.response.defer(ephemeral=True)
        import json
        text = await self.bot.scraper.request('GET', 'https://api.zenrows.com/v1/subscriptions/self/details',
                                               headers={'X-API-Key': self.bot.scraper.zenrows_key})
        data = json.loads(text)
        caps = data.get('api_key', {}).get('caps', [])
        remaining = caps[0].get('remaining_credits') if caps else None
        message = f'ZenRows cap credits remaining: {remaining}' if remaining is not None else 'No credit cap reported. Check your ZenRows dashboard for account usage.'
        await interaction.followup.send(message, ephemeral=True)


async def setup(bot):
    await bot.add_cog(TrackerCog(bot))
