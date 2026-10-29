"""Modelos de predicción del gasto: alcance, estados y métricas.

Hay un modelo general (aprende de las series normalizadas de todos los clientes) y uno
por cliente (owner_id). Cada entrenamiento queda en un ForecastTrainingRun; el modelo
resultante es un ForecastModel con sus métricas de backtest (origen móvil: se entrena
hasta un mes y se mide el error en el siguiente).
"""

from dataclasses import dataclass

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


# --- Series, cuantiles y combinación ---------------------------------------------------

# Meses que se predicen desde el último mes completo (el primero es el mes en curso).
HORIZON = 4
# Con menos meses de historia el cliente no tiene modelo propio: solo el general.
MIN_USER_MONTHS = 3
# Con esta historia el modelo del cliente alcanza su peso máximo en la combinación.
FULL_USER_MONTHS = 12
MAX_USER_WEIGHT = 0.8
# Meses del backtest (origen móvil): se entrena hasta cada uno y se mide el siguiente.
BACKTEST_MONTHS = 6
Z_80 = 1.2816  # cuantil 0,9 de la normal: P10–P90 es un intervalo del 80 %


@dataclass(frozen=True)
class MonthlySeries:
    """Gasto mensual de un cliente en una moneda: meses consecutivos y completos."""

    owner_id: str
    currency: str
    months: tuple[str, ...]  # "AAAA-MM", consecutivos
    values: tuple[float, ...]  # total gastado cada mes (0 si no hubo compras)

    def __len__(self) -> int:
        return len(self.values)

    def head(self, n: int) -> "MonthlySeries":
        """Los primeros `n` meses (para entrenar hasta un origen del backtest)."""
        return MonthlySeries(self.owner_id, self.currency, self.months[:n], self.values[:n])


@dataclass(frozen=True)
class Quantiles:
    p10: float
    p50: float
    p90: float

    def ordered(self) -> "Quantiles":
        """Sin cuantiles cruzados ni gasto negativo."""
        p10, p50, p90 = sorted(max(0.0, v) for v in (self.p10, self.p50, self.p90))
        return Quantiles(p10, p50, p90)


def history_scale(values: list[float] | tuple[float, ...], t: int | None = None) -> float:
    """Gasto medio en los 12 meses anteriores a `t` (por defecto, al final): la escala del cliente."""
    t = len(values) if t is None else t
    window = values[max(0, t - 12) : t]
    return sum(window) / len(window) if window else 0.0


def user_weight(months: int) -> float:
    """Peso del modelo del cliente frente al general según su historia."""
    if months < MIN_USER_MONTHS:
        return 0.0
    progress = (months - MIN_USER_MONTHS + 1) / (FULL_USER_MONTHS - MIN_USER_MONTHS + 1)
    return MAX_USER_WEIGHT * min(1.0, progress)


def blend(general: Quantiles | None, user: Quantiles | None, weight: float) -> Quantiles | None:
    if general is None:
        return user
    if user is None or weight <= 0:
        return general
    mix = [
        weight * u + (1 - weight) * g
        for u, g in zip((user.p10, user.p50, user.p90), (general.p10, general.p50, general.p90), strict=True)
    ]
    return Quantiles(*mix).ordered()


def backtest_metrics(actuals: list[float], predictions: list[Quantiles], naive: list[float]) -> dict:
    """Métricas de un backtest: `naive` es la predicción ingenua (el mes anterior)."""
    if not actuals:
        return {}
    errors = [abs(a - p.p50) for a, p in zip(actuals, predictions, strict=True)]
    naive_errors = [abs(a - n) for a, n in zip(actuals, naive, strict=True)]
    pct = [abs(a - p.p50) / a * 100 for a, p in zip(actuals, predictions, strict=True) if a > 0]
    inside = [p.p10 <= a <= p.p90 for a, p in zip(actuals, predictions, strict=True)]
    mae = sum(errors) / len(errors)
    naive_mae = sum(naive_errors) / len(naive_errors)
    return {
        METRIC_MAE: round(mae, 4),
        METRIC_MAPE: round(sum(pct) / len(pct), 2) if pct else None,
        METRIC_MASE: round(mae / naive_mae, 3) if naive_mae > 0 else None,
        METRIC_COVERAGE: round(100 * sum(inside) / len(inside), 1),
        "evaluations": len(actuals),
    }
