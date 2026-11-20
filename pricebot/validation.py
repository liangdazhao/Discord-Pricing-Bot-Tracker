"""Input validation and user-facing errors."""
from decimal import Decimal, InvalidOperation
import ipaddress
from urllib.parse import urlsplit, urlunsplit


class UserError(ValueError):
    """A safe, actionable message that can be shown to a Discord user."""


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount > Decimal('1000000000'):
            raise ValueError
        rounded = amount.quantize(Decimal('0.01'))
        if rounded <= 0:
            raise ValueError
        return float(rounded)
    except (InvalidOperation, ValueError, TypeError):
        raise UserError('Enter a valid positive price (maximum 1 billion).') from None


def normalize_url(value):
    try:
        parts = urlsplit(value.strip())
        host = parts.hostname
        if parts.scheme not in ('http', 'https') or not host or parts.username or parts.password:
            raise ValueError
        if parts.port not in (None, 80, 443) or any(c.isspace() for c in value):
            raise ValueError
        if host == 'localhost' or host.endswith(('.local', '.localhost', '.internal')) or '.' not in host:
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError
        if len(value) > 1800:
            raise ValueError
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or '/', parts.query, ''))
    except (ValueError, AttributeError):
        raise UserError('Use a public HTTP or HTTPS product URL without credentials or a custom port.') from None


