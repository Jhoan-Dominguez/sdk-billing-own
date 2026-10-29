"""Lo que ve un cliente de sus predicciones: los próximos meses, cómo cerraría el mes en
curso y si va por encima de lo habitual. Siempre de un solo dueño (`owner_id`)."""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from billing.domain.models import Purchase, SpendForecast
from billing.domain.periods import add_months, month_bounds, month_key
from billing.domain.ports.repositories import UnitOfWork

CURVE_MONTHS = 6  # meses completos con los que se estima el ritmo de gasto dentro del mes


@dataclass(frozen=True)
class Projection:
    """Cierre estimado del mes en curso."""

    spent: float  # gastado hasta hoy
    expected: float
    low: float
    high: float
    progress: float  # fracción del gasto mensual que suele llevar a estas alturas


@dataclass
class Outlook:
    currency: str
    current: SpendForecast | None  # la predicción del mes en curso (fijada al empezar el mes)
    upcoming: list[SpendForecast] = field(default_factory=list)  # meses siguientes
    past: list[SpendForecast] = field(default_factory=list)  # meses cerrados, con el real
    projection: Projection | None = None

    @property
    def accuracy(self) -> float | None:
        """Acierto real (100 − error porcentual medio) en los meses cerrados con gasto."""
        errors = [abs(f.actual - f.p50) / f.actual * 100 for f in self.past if f.actual and f.actual > 0]
        return max(0.0, 100 - float(sum(errors) / len(errors))) if errors else None

    @property
    def above_usual(self) -> bool:
        """El gasto (o su cierre estimado) supera el rango alto previsto para el mes."""
        if self.current is None or self.projection is None:
            return False
        return self.projection.expected > float(self.current.p90)


def _progress(purchases: list[Purchase], currency: str, today: date) -> float:
    """Fracción del total mensual que se suele llevar gastada a estas alturas del mes."""
    elapsed = today.day / calendar.monthrange(today.year, today.month)[1]
    fractions = []
    current = month_key(today)
    for offset in range(1, CURVE_MONTHS + 1):
        month = add_months(current, -offset)
        rows = [p for p in purchases if p.currency == currency and month_key(p.purchase_date) == month]
        total = sum((p.total for p in rows), Decimal(0))
        if total <= 0:
            continue
        start, _ = month_bounds(month)
        cutoff = round(elapsed * calendar.monthrange(start.year, start.month)[1])
        fractions.append(float(sum((p.total for p in rows if p.purchase_date.day <= cutoff), Decimal(0)) / total))
    return sum(fractions) / len(fractions) if fractions else elapsed


def _projection(spent: float, progress: float, forecast: SpendForecast | None) -> Projection | None:
    pace = spent / progress if progress >= 0.05 else None
    if forecast is None and pace is None:
        return None
    if forecast is None:
        return Projection(spent, pace, max(spent, pace * 0.8), pace * 1.2, progress)
    # Al principio del mes pesa la predicción; a medida que avanza, el ritmo real.
    weight = min(1.0, progress) if pace is not None else 0.0
    pace = pace or 0.0

    def mix(value: Decimal) -> float:
        return max(spent, weight * pace + (1 - weight) * float(value))

    return Projection(spent, mix(forecast.p50), mix(forecast.p10), mix(forecast.p90), progress)


def outlook(uow: UnitOfWork, *, owner_id: str, today: date | None = None) -> list[Outlook]:
    today = today or date.today()
    current = month_key(today)
    forecasts = uow.forecasts.for_owner(owner_id)
    since = month_bounds(add_months(current, -CURVE_MONTHS))[0]
    purchases = uow.purchases.between(since, today + timedelta(days=1), owner_id=owner_id)
    currencies = sorted({f.currency for f in forecasts})
    result = []
    for currency in currencies:
        own = [f for f in forecasts if f.currency == currency]
        item = Outlook(
            currency=currency,
            current=next((f for f in own if month_key(f.period) == current), None),
            upcoming=[f for f in own if month_key(f.period) > current],
            past=[f for f in own if month_key(f.period) < current and f.actual is not None],
        )
        spent = float(
            sum(
                (p.total for p in purchases if p.currency == currency and month_key(p.purchase_date) == current),
                Decimal(0),
            )
        )
        item.projection = _projection(spent, _progress(purchases, currency, today), item.current)
        result.append(item)
    return result
