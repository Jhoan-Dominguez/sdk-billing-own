"""Modelos de predicción del gasto: alcance, estados y métricas.

Hay un modelo general (aprende de las series normalizadas de todos los clientes) y uno
por cliente (owner_id). Cada entrenamiento queda en un ForecastTrainingRun; el modelo
resultante es un ForecastModel con sus métricas de backtest (origen móvil: se entrena
hasta un mes y se mide el error en el siguiente).
"""

SCOPE_GLOBAL = "global"
SCOPE_USER = "user"
SCOPE_LABELS = {SCOPE_GLOBAL: "General", SCOPE_USER: "Por cliente"}

# Solo hay un modelo `active` por alcance (y por cliente); los anteriores quedan archivados.
MODEL_ACTIVE = "active"
MODEL_ARCHIVED = "archived"
MODEL_STATUS_LABELS = {MODEL_ACTIVE: "Activo", MODEL_ARCHIVED: "Archivado"}

RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_STATUS_LABELS = {RUN_RUNNING: "En curso", RUN_SUCCEEDED: "Correcto", RUN_FAILED: "Fallido"}

# Claves de ForecastModel.metrics. `mape` y `coverage` van en porcentaje (0-100); `mae`
# en la unidad del objetivo (moneda del cliente, o proporción en el modelo general).
METRIC_MAE = "mae"
METRIC_MAPE = "mape"
METRIC_MASE = "mase"
METRIC_COVERAGE = "coverage"
METRIC_LABELS = {
    METRIC_MAPE: "Error porcentual medio (MAPE)",
    METRIC_MAE: "Error absoluto medio (MAE)",
    METRIC_MASE: "MASE (frente a la referencia ingenua)",
    METRIC_COVERAGE: "Cobertura del rango P10–P90",
}


def error_pct(metrics: dict | None) -> float | None:
    """Porcentaje de error del modelo (MAPE)."""
    value = (metrics or {}).get(METRIC_MAPE)
    return float(value) if value is not None else None


def accuracy_pct(metrics: dict | None) -> float | None:
    """Porcentaje de acierto: 100 - MAPE, acotado a [0, 100]."""
    error = error_pct(metrics)
    return None if error is None else max(0.0, min(100.0, 100.0 - error))


def beats_baseline(metrics: dict | None) -> bool | None:
    """MASE < 1: el modelo se equivoca menos que repetir el mes anterior."""
    value = (metrics or {}).get(METRIC_MASE)
    return None if value is None else float(value) < 1
