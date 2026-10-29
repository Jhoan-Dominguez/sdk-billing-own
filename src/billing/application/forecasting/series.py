"""Series mensuales de gasto a partir de las compras (los datos de entrenamiento).

No se copian a ninguna tabla: se derivan de `purchases` cada vez, así editar o borrar una
compra (o una cuenta) se refleja en el siguiente entrenamiento.
"""

import hashlib
import json
from collections import defaultdict
from decimal import Decimal

from billing.domain.forecasting import MonthlySeries
from billing.domain.periods import add_months


def build_series(rows: list[tuple[str, str, str, Decimal]], *, current_month: str) -> list[MonthlySeries]:
    """Una serie por (dueño, moneda): del primer mes con compras al último mes completo
    (anterior a `current_month`), con 0 en los meses sin compras."""
    grouped: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for owner, currency, month, total in rows:
        if month < current_month:
            grouped[(owner, currency)][month] = float(total)
    last = add_months(current_month, -1)
    result = []
    for (owner, currency), totals in sorted(grouped.items()):
        months, month = [], min(totals)
        while month <= last:
            months.append(month)
            month = add_months(month, 1)
        result.append(MonthlySeries(owner, currency, tuple(months), tuple(totals.get(m, 0.0) for m in months)))
    return result


def fingerprint(series: list[MonthlySeries] | MonthlySeries) -> str:
    """Hash de los datos: si no cambia, no hace falta reentrenar."""
    items = [series] if isinstance(series, MonthlySeries) else series
    payload = [[s.owner_id, s.currency, s.months[0], [round(v, 2) for v in s.values]] for s in items]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()
