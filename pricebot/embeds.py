"""Shared Discord presentation helpers."""
from urllib.parse import quote, urlsplit

import discord


def product_embed(title, url, price, currency, target=None, item_id=None, checked_at=None):
    under = target is not None and price is not None and price > 0 and price <= target
    embed = discord.Embed(title=discord.utils.escape_markdown(title or 'Unknown product')[:256],
                          url=url, color=discord.Color.green() if under else discord.Color.blue())
    embed.add_field(name='Current price', value=f'{currency} {price:,.2f}' if price and price > 0 else 'Not available')
    if target is not None:
        embed.add_field(name='Target', value=f'{currency} {target:,.2f}')
        embed.add_field(name='Status', value='Target reached' if under else 'Waiting for target')
    embed.add_field(name='Retailer', value=urlsplit(url).hostname or 'Unknown')
    query = quote(title or 'product', safe='')
    embed.add_field(name='Compare prices', value=(
        f'[Google Shopping](https://www.google.com/search?tbm=shop&q={query}) | '
        f'[eBay](https://www.ebay.com/sch/i.html?_nkw={query})'), inline=False)
    footer = f'Item #{item_id} • ' if item_id is not None else ''
    footer += f'Checked {checked_at} UTC' if checked_at else 'Prices may change; verify at checkout.'
    embed.set_footer(text=footer)
    return embed


def row_embed(row):
    return product_embed(row['title'], row['url'], row['last_price'], row['currency'],
                         row['target_price'], row['id'], row['checked_at'])


