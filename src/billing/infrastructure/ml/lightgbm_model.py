"""Modelo general con LightGBM: tres modelos de regresión por cuantiles (P10, P50, P90)
sobre las variables normalizadas de features.py.

El artefacto es JSON con los tres modelos en el formato de texto de LightGBM (sin pickle:
cargarlo no ejecuta código). Para predecir varios meses se encadena: la predicción P50 de un
mes entra como historia del siguiente.
"""

import hashlib
import json
from functools import lru_cache

import numpy as np

from billing.domain.forecasting import MonthlySeries, Quantiles
from billing.domain.ports.forecasting import ForecastingError, TrainedModel
from billing.infrastructure.ml.features import FEATURES, next_month, row, scale, training_rows

try:
    import lightgbm as lgb
except ImportError:  # extra "ml" sin instalar
    lgb = None

QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}
MIN_SAMPLES = 12
FORMAT = "billing-lightgbm"


@lru_cache(maxsize=4)
def _boosters(digest: str, artifact: bytes) -> dict:
    data = json.loads(artifact)
    if data.get("format") != FORMAT or data.get("features") != FEATURES:
        raise ForecastingError("El modelo general guardado no es compatible con esta versión.")
    return {name: lgb.Booster(model_str=text) for name, text in data["boosters"].items()}


class LightGBMForecaster:
    algorithm = "lightgbm"

    def __init__(self, rounds: int = 300, learning_rate: float = 0.05, num_leaves: int = 15) -> None:
        if lgb is None:
            raise ForecastingError("LightGBM no está instalado (pip install '.[ml]').")
        self.rounds, self.learning_rate, self.num_leaves = rounds, learning_rate, num_leaves

    def _params(self, alpha: float, n: int) -> dict:
        return {
            "objective": "quantile",
            "alpha": alpha,
            "learning_rate": self.learning_rate,
            "num_leaves": self.num_leaves,
            "min_data_in_leaf": max(3, min(20, n // 10)),
            "feature_fraction": 0.9,
            "seed": 7,
            "deterministic": True,
            "num_threads": 2,
            "verbose": -1,
        }

    def fit(self, series: list[MonthlySeries]) -> TrainedModel:
        X, y = training_rows(series)
        if len(X) < MIN_SAMPLES:
            raise ForecastingError(f"Pocos datos para el modelo general ({len(X)} muestras; mínimo {MIN_SAMPLES}).")
        rounds = min(self.rounds, max(50, 2 * len(X)))
        features, target = np.asarray(X, dtype=float), np.asarray(y, dtype=float)
        boosters = {
            name: lgb.train(self._params(alpha, len(X)), lgb.Dataset(features, target, feature_name=FEATURES), rounds)
            for name, alpha in QUANTILES.items()
        }
        artifact = json.dumps(
            {
                "format": FORMAT,
                "version": 1,
                "features": FEATURES,
                "boosters": {name: b.model_to_string() for name, b in boosters.items()},
            }
        ).encode()
        params = {"rounds": rounds, "learning_rate": self.learning_rate, "num_leaves": self.num_leaves}
        return TrainedModel(artifact=artifact, features=list(FEATURES), params=params, n_samples=len(X))

    def predict(self, artifact: bytes, series: MonthlySeries, horizon: int) -> list[Quantiles]:
        boosters = _boosters(hashlib.sha256(artifact).hexdigest(), artifact)
        values = list(series.values)
        result = []
        for h in range(1, horizon + 1):
            t = len(values)
            factor = scale(values, t)
            if factor <= 0:  # sin gasto en el último año: se predice cero
                quantiles = Quantiles(0.0, 0.0, 0.0)
            else:
                x = np.asarray([row(values, t, next_month(series, h))], dtype=float)
                quantiles = Quantiles(*(float(boosters[n].predict(x)[0]) * factor for n in QUANTILES)).ordered()
            result.append(quantiles)
            values.append(quantiles.p50)
        return result
