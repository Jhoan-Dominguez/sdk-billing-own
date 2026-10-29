"""Variables del modelo general.

Cada muestra es un mes `t` de una serie. Todo se divide por la escala del cliente (su
gasto medio en los 12 meses anteriores a `t`), así el modelo aprende patrones (estacionalidad,
inercia, rachas) que valen para cualquier moneda y nivel de gasto. Los meses que faltan al
principio de una serie quedan como NaN (LightGBM los maneja).
"""

import statistics

from billing.domain.forecasting import MonthlySeries, history_scale
from billing.domain.periods import add_months

FEATURES = ["lag_1", "lag_2", "lag_3", "lag_6", "lag_12", "mean_3", "mean_6", "std_6", "trend", "month", "history"]
MIN_HISTORY = 3  # meses previos necesarios para usar un mes como muestra
NAN = float("nan")


def scale(values: list[float], t: int) -> float:
    return history_scale(values, t)


def row(values: list[float], t: int, month: str) -> list[float]:
    """Variables para predecir el mes `t` (índice en `values`; puede ser len(values))."""
    s = scale(values, t)
    norm = [v / s for v in values[:t]] if s > 0 else [0.0] * t

    def lag(k: int) -> float:
        return norm[t - k] if t - k >= 0 else NAN

    def mean(k: int) -> float:
        window = norm[max(0, t - k) : t]
        return sum(window) / len(window) if window else NAN

    last6 = norm[max(0, t - 6) : t]
    trend = lag(1) - lag(3) if t >= 3 else NAN
    return [
        lag(1),
        lag(2),
        lag(3),
        lag(6),
        lag(12),
        mean(3),
        mean(6),
        statistics.pstdev(last6) if len(last6) >= 2 else NAN,
        trend,
        float(int(month[5:7])),
        float(t),
    ]


def training_rows(series: list[MonthlySeries]) -> tuple[list[list[float]], list[float]]:
    """(X, y) con y = gasto del mes / escala del cliente."""
    X, y = [], []
    for s in series:
        values = list(s.values)
        for t in range(MIN_HISTORY, len(values)):
            factor = scale(values, t)
            if factor <= 0:
                continue
            X.append(row(values, t, s.months[t]))
            y.append(values[t] / factor)
    return X, y


def next_month(series: MonthlySeries, step: int = 1) -> str:
    return add_months(series.months[-1], step)
