import discord
from discord import app_commands
from discord.ext import commands
from ..validation import normalize_url
from ..embeds import product_embed


class Search(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='check', description='Check a product price without saving it')
    @app_commands.checks.cooldown(1, 30, key=lambda i: i.user.id)
    async def check_price(self, interaction: discord.Interaction, url: str):
        url = normalize_url(url)
        await interaction.response.defer(ephemeral=True)
        product = await self.bot.scraper.scrape(url)
        await interaction.followup.send(embed=product_embed(product.title, url, product.price, product.currency), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Search(bot))
