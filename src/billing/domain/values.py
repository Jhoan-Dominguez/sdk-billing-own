"""Normalización de valores que llegan de formularios o extractores."""

import math
from decimal import Decimal, InvalidOperation

from billing.domain.errors import ValidationError

CENT = Decimal("0.01")


def is_blank(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def clean_str(value) -> str | None:
    """Texto sin espacios sobrantes; None para vacíos y NaN (celdas vacías de pandas)."""
    if is_blank(value):
        return None
    return str(value).strip() or None


def truncate(value, length: int) -> str | None:
    s = clean_str(value)
    return s[:length] if s else None


def to_decimal(value, field_name: str = "valor") -> Decimal | None:
    """Acepta None, NaN, números o textos con coma decimal; redondea a centavos."""
    if is_blank(value):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
        if not value:
            return None
    try:
        return Decimal(str(value)).quantize(CENT)
    except InvalidOperation:
        raise ValidationError(f"{field_name}: '{value}' no es un número válido") from None
