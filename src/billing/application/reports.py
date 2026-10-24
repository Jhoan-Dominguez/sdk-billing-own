"""Agregados para los resúmenes y comparativas."""

from collections import defaultdict
from decimal import Decimal

from billing.domain.models import Purchase


def totals_by(purchases: list[Purchase], key) -> dict:
    """{clave: {moneda: total}} — las monedas no se suman entre sí."""
    out: dict = defaultdict(lambda: defaultdict(Decimal))
    for p in purchases:
        out[key(p)][p.currency] += p.total
    return {k: dict(v) for k, v in out.items()}
