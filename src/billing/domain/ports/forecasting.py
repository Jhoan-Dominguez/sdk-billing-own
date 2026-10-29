"""Algoritmos de predicción del gasto (infrastructure/ml)."""

from dataclasses import dataclass, field
from typing import Protocol

from billing.domain.forecasting import MonthlySeries, Quantiles


class ForecastingError(RuntimeError):
    """No se pudo entrenar o predecir (pocos datos, librería ausente, modelo dañado)."""


@dataclass
class TrainedModel:
    artifact: bytes  # el modelo serializado (sin pickle), para el FileStorage
    features: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    n_samples: int = 0


class GlobalForecaster(Protocol):
    """Modelo general: aprende de las series (normalizadas) de todos los clientes."""

    algorithm: str

    def fit(self, series: list[MonthlySeries]) -> TrainedModel: ...
    def predict(self, artifact: bytes, series: MonthlySeries, horizon: int) -> list[Quantiles]:
        """Los `horizon` meses siguientes al último de `series`."""
        ...


class SeriesForecaster(Protocol):
    """Modelo de un cliente: unos pocos parámetros que caben en la base (JSON)."""

    algorithm: str

    def fit(self, series: MonthlySeries) -> dict:
        """Parámetros del modelo, con el estado al final de la serie para poder predecir."""
        ...

    def predict(self, params: dict, horizon: int) -> list[Quantiles]: ...
