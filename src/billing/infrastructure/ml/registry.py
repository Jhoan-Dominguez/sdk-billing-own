"""Algoritmos disponibles. El general se elige con BILLING_FORECAST_ALGORITHM; si no se
puede usar (p. ej. LightGBM sin instalar), bootstrap cae en la referencia ingenua."""

import importlib

from billing.domain.ports.forecasting import ForecastingError, GlobalForecaster, SeriesForecaster

GLOBAL: dict[str, str] = {
    "lightgbm": "billing.infrastructure.ml.lightgbm_model:LightGBMForecaster",
    "baseline": "billing.infrastructure.ml.baseline:BaselineGlobalForecaster",
}
SERIES: dict[str, str] = {
    "ets": "billing.infrastructure.ml.ets:DampedTrendForecaster",
    "baseline": "billing.infrastructure.ml.baseline:BaselineSeriesForecaster",
}


def _create(table: dict[str, str], name: str):
    try:
        module, _, cls = table[name].partition(":")
    except KeyError:
        raise ForecastingError(f"Algoritmo desconocido: {name!r}. Opciones: {', '.join(table)}") from None
    return getattr(importlib.import_module(module), cls)()


def create_global(name: str) -> GlobalForecaster:
    return _create(GLOBAL, name)


def create_series(name: str) -> SeriesForecaster:
    return _create(SERIES, name)
