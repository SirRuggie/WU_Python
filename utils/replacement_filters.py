"""Shared, unambiguous replacement weight inputs and labels."""
from decimal import Decimal, InvalidOperation
import math
import re


_WEIGHT = re.compile(r'^([0-9]+(?:\.[0-9]{1,3})?)([kK]?)$')


def parse_weight(value) -> int:
    """Accept 149/149k as 149000 and full weights as-is (maximum 500000)."""
    if isinstance(value, bool) or value is None:
        raise ValueError('Enter a positive weight up to 500k.')
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Enter a finite positive weight up to 500k.')
    text = str(value).strip()
    match = _WEIGHT.fullmatch(text)
    if not match:
        raise ValueError('Enter a weight such as 149k or 149000.')
    try:
        number = Decimal(match.group(1))
    except InvalidOperation as exc:
        raise ValueError('Enter a valid weight.') from exc
    full = number * 1000 if match.group(2) or number < 1000 else number
    if not 0 < full <= 500000 or full != full.to_integral_value():
        raise ValueError('Enter a positive weight up to 500k.')
    return int(full)


def compact_weight(value) -> str:
    """Display a known full weight as 149k or 149.5k."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return '?'
    thousands = Decimal(value) / 1000
    return f'{format(thousands.normalize(), "f")}k'
