"""Modelo de cada cliente: suavizado exponencial con tendencia amortiguada (ETS A,Ad,N).

Con 24 meses o más se le suma una estacionalidad multiplicativa por mes del año (encogida
hacia 1 para no sobreajustar). Los parámetros se eligen por rejilla minimizando el error a un
paso; el resultado son unos pocos números que se guardan como JSON en ml_models.params.
"""

import math

from billing.domain.forecasting import Z_80, MonthlySeries, Quantiles
from billing.domain.periods import add_months

ALPHAS = (0.1, 0.2, 0.3, 0.5, 0.7)
BETAS = (0.0, 0.05, 0.1, 0.2)
PHIS = (0.8, 0.9, 0.98)
SEASONAL_MONTHS = 24
SEASONAL_SHRINK = 0.5


def _smooth(y: list[float], alpha: float, beta: float, phi: float) -> tuple[float, float, float]:
    """(suma de errores², nivel final, tendencia final)."""
    level = y[0]
    k = min(3, len(y) - 1)
    trend = (y[k] - y[0]) / k if k else 0.0
    sse = 0.0
    for value in y[1:]:
        forecast = level + phi * trend
        sse += (value - forecast) ** 2
        new_level = alpha * value + (1 - alpha) * forecast
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    return sse, level, trend


def _seasonal(series: MonthlySeries) -> dict[str, float] | None:
    mean = sum(series.values) / len(series.values)
    if len(series) < SEASONAL_MONTHS or mean <= 0:
        return None
    by_month: dict[str, list[float]] = {}
    for month, value in zip(series.months, series.values, strict=True):
        by_month.setdefault(month[5:7], []).append(value)
    return {m: 1 + SEASONAL_SHRINK * ((sum(vs) / len(vs)) / mean - 1) for m, vs in by_month.items() if sum(vs) > 0}


class DampedTrendForecaster:
    algorithm = "ets"

    def fit(self, series: MonthlySeries) -> dict:
        seasonal = _seasonal(series)
        y = [v / (seasonal or {}).get(m[5:7], 1.0) for m, v in zip(series.months, series.values, strict=True)]
        best = None
        for alpha in ALPHAS:
            for beta in BETAS:
                for phi in PHIS:
                    sse, level, trend = _smooth(y, alpha, beta, phi)
                    if best is None or sse < best[0]:
                        best = (sse, alpha, beta, phi, level, trend)
        sse, alpha, beta, phi, level, trend = best
        mean = sum(y) / len(y)
        sigma = math.sqrt(sse / (len(y) - 1)) if len(y) > 1 and sse > 0 else 0.25 * mean
        return {
            "alpha": alpha,
            "beta": beta,
            "phi": phi,
            "level": level,
            "trend": trend,
            "sigma": sigma,
            "seasonal": seasonal,
            "last_month": series.months[-1],
        }

    def predict(self, params: dict, horizon: int) -> list[Quantiles]:
        result = []
        damp = 0.0
        for h in range(1, horizon + 1):
            damp += params["phi"] ** h
            factor = (params.get("seasonal") or {}).get(add_months(params["last_month"], h)[5:7], 1.0)
            center = (params["level"] + damp * params["trend"]) * factor
            spread = Z_80 * params["sigma"] * math.sqrt(h) * factor
            result.append(Quantiles(center - spread, center, center + spread).ordered())
        return result
