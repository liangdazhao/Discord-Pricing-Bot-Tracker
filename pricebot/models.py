"""Product data model."""
from dataclasses import dataclass

from .validation import UserError, money


@dataclass(frozen=True)
class Product:
    title: str
    price: float
    currency: str

    @classmethod
    def parse(cls, data):
        title = str(data.get('title') or '').strip()
        currency = str(data.get('currency') or '').upper().strip()
        if not title or len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise UserError('Could not identify a product title and currency on this page.')
        return cls(title[:250], money(data.get('price')), currency)


