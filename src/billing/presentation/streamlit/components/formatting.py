"""Formato de valores para mostrar (la lógica no depende de esto)."""

from decimal import Decimal

from billing.domain.values import is_blank

MONTH_NAMES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def month_label(month: str) -> str:
    y, m = month.split("-")
    return f"{MONTH_NAMES[int(m) - 1].capitalize()} {y}"


def money(amount, currency: str = "") -> str:
    if amount is None:
        return "—"
    return f"{currency} {amount:,.2f}".strip()


def to_float(value: Decimal | float | None) -> float | None:
    """Decimal -> float para gráficos y widgets numéricos (None y NaN -> None)."""
    return None if is_blank(value) else float(value)
