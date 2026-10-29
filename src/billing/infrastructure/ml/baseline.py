"""Referencia ingenua: la media de los últimos 3 meses, con un rango según su variabilidad.

Es el respaldo cuando no hay LightGBM o pocos datos, y la vara con la que se comparan los
modelos (un modelo nuevo debería superarla).
"""

import json
import math
import statistics

from billing.domain.forecasting import Z_80, MonthlySeries, Quantiles
from billing.domain.ports.forecasting import TrainedModel


def _estimate(values: list[float]) -> tuple[float, float]:
    recent = values[-3:]
    mean = sum(recent) / len(recent) if recent else 0.0
    window = values[-6:]
    sigma = statistics.pstdev(window) if len(window) >= 2 else 0.25 * mean
    return mean, sigma


def _quantiles(mean: float, sigma: float, horizon: int) -> list[Quantiles]:
    return [
        Quantiles(mean - Z_80 * sigma * math.sqrt(h), mean, mean + Z_80 * sigma * math.sqrt(h)).ordered()
        for h in range(1, horizon + 1)
    ]


class BaselineGlobalForecaster:
    algorithm = "baseline"

    def fit(self, series: list[MonthlySeries]) -> TrainedModel:
        artifact = json.dumps({"format": "billing-baseline", "version": 1}).encode()
        return TrainedModel(artifact=artifact, params={"window": 3}, n_samples=sum(len(s) for s in series))

    def predict(self, artifact: bytes, series: MonthlySeries, horizon: int) -> list[Quantiles]:
        return _quantiles(*_estimate(list(series.values)), horizon)


class BaselineSeriesForecaster:
    algorithm = "baseline"

    def fit(self, series: MonthlySeries) -> dict:
        mean, sigma = _estimate(list(series.values))
        return {"mean": mean, "sigma": sigma}

    def predict(self, params: dict, horizon: int) -> list[Quantiles]:
        return _quantiles(params["mean"], params["sigma"], horizon)
