"""Entrenamiento de los modelos de predicción y generación de las predicciones.

- Modelo general: se reentrena a diario (o a demanda) con las series de todos los clientes.
  El artefacto va al FileStorage (`models/global/<versión>.json`).
- Modelo de cada cliente y moneda: se reentrena solo si sus datos cambiaron (huella de la
  serie distinta de la del entrenamiento activo). Sus parámetros van en ml_models.params.
- Predicciones: para cada serie, los próximos HORIZON meses combinando ambos modelos según
  la historia del cliente. Un mes que ya empezó no se reescribe; al cerrarse guarda el real.

Lo usan el worker (python -m billing.worker), el botón «Entrenar ahora» y `make train`.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from billing.application.forecasting.series import build_series, fingerprint
from billing.domain import forecasting as fc
from billing.domain.forecasting import MonthlySeries, Quantiles
from billing.domain.models import ForecastModel, ForecastTrainingRun, SpendForecast
from billing.domain.periods import add_months, month_key
from billing.domain.ports.forecasting import ForecastingError, GlobalForecaster, SeriesForecaster
from billing.domain.ports.repositories import UnitOfWork
from billing.domain.ports.storage import FileStorage
from billing.domain.values import CENT

log = logging.getLogger("billing.forecasting")

GLOBAL_PREFIX = "models/global/"
KEEP_GLOBAL_ARTIFACTS = 10  # versiones archivadas del modelo general que conservan su archivo


@dataclass
class TrainingReport:
    global_model: ForecastModel | None = None
    global_error: str | None = None
    user_models: int = 0
    unchanged: int = 0
    forecasts: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        if self.global_model:
            parts.append(f"modelo general {self.global_model.version}")
        if self.global_error:
            parts.append(f"modelo general sin entrenar: {self.global_error}")
        parts.append(f"{self.user_models} modelos de cliente entrenados, {self.unchanged} sin cambios")
        parts.append(f"{self.forecasts} predicciones")
        if self.errors:
            parts.append(f"{len(self.errors)} errores")
        return "; ".join(parts) + "."


def _month_date(month: str) -> date:
    return date.fromisoformat(f"{month}-01")


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(CENT)


def _active(uow: UnitOfWork, scope: str, owner_id: str | None = None, currency: str | None = None):
    candidates = uow.forecast_models.for_owner(owner_id) if owner_id else uow.forecast_models.list(scope=scope)
    return next(
        (
            m
            for m in candidates
            if m.scope == scope and m.status == fc.MODEL_ACTIVE and (m.owner_id, m.currency) == (owner_id, currency)
        ),
        None,
    )


def active_global(uow: UnitOfWork) -> ForecastModel | None:
    return _active(uow, fc.SCOPE_GLOBAL)


def _activate(uow: UnitOfWork, storage: FileStorage, model: ForecastModel) -> None:
    """Deja `model` como el único activo de su alcance (y cliente y moneda)."""
    previous = _active(uow, model.scope, model.owner_id, model.currency)
    if previous is not None:
        previous.status = fc.MODEL_ARCHIVED
    uow.forecast_models.add(model)
    if model.scope == fc.SCOPE_GLOBAL:
        archived = [m for m in uow.forecast_models.list(scope=fc.SCOPE_GLOBAL) if m.artifact_key and m is not model]
        for old in archived[KEEP_GLOBAL_ARTIFACTS:]:  # la lista va de la más reciente a la más antigua
            storage.delete(old.artifact_key)
            old.artifact_key = None


def _finish(run: ForecastTrainingRun, error: Exception | None = None) -> None:
    run.status = fc.RUN_FAILED if error else fc.RUN_SUCCEEDED
    run.error = str(error)[:2000] if error else None
    run.finished_at = datetime.now()


# --- Backtests ---------------------------------------------------------------------------


def backtest_global(forecaster: GlobalForecaster, series: list[MonthlySeries]) -> dict:
    """Origen móvil por mes de calendario. Las métricas van en la escala de cada cliente
    (gasto / su media), así se pueden mezclar monedas."""
    months = sorted({m for s in series for m in s.months})
    actual, predicted, naive = [], [], []
    for origin in months[-fc.BACKTEST_MONTHS :]:
        heads = [s.head(sum(1 for m in s.months if m < origin)) for s in series]
        train = [h for h in heads if len(h) > 0]
        try:
            trained = forecaster.fit(train)
        except ForecastingError:
            continue  # pocos datos antes de este origen
        for s, head in zip(series, heads, strict=True):
            if origin not in s.months or len(head) < 3 or (scale := fc.history_scale(head.values)) <= 0:
                continue
            q = forecaster.predict(trained.artifact, head, 1)[0]
            actual.append(s.values[len(head)] / scale)
            predicted.append(Quantiles(q.p10 / scale, q.p50 / scale, q.p90 / scale))
            naive.append(head.values[-1] / scale)
    return fc.backtest_metrics(actual, predicted, naive)


def backtest_series(forecaster: SeriesForecaster, series: MonthlySeries) -> dict:
    actual, predicted, naive = [], [], []
    for index in range(max(fc.MIN_USER_MONTHS, len(series) - fc.BACKTEST_MONTHS), len(series)):
        params = forecaster.fit(series.head(index))
        predicted.append(forecaster.predict(params, 1)[0])
        actual.append(series.values[index])
        naive.append(series.values[index - 1])
    return fc.backtest_metrics(actual, predicted, naive)


# --- Entrenamiento ---------------------------------------------------------------------


def train_global(
    uow: UnitOfWork, forecaster: GlobalForecaster, storage: FileStorage, *, now: datetime | None = None
) -> ForecastModel:
    """Entrena y activa el modelo general. Lanza ForecastingError si no se pudo (queda la ejecución fallida)."""
    now = now or datetime.now()
    series = build_series(uow.purchases.monthly_totals(owner_id=None), current_month=month_key(now))
    run = ForecastTrainingRun(
        scope=fc.SCOPE_GLOBAL,
        algorithm=forecaster.algorithm,
        data_fingerprint=fingerprint(series) if series else None,
        n_samples=sum(len(s) for s in series),
        params={"series": len(series)},
    )
    run.created_at = now  # mismo reloj que finished_at y que la decisión de reentrenar
    uow.forecast_runs.add(run)
    uow.commit()
    try:
        if not series:
            raise ForecastingError("No hay meses completos con compras.")
        metrics = backtest_global(forecaster, series)
        trained = forecaster.fit(series)
    except Exception as e:  # cualquier fallo queda en la ejecución y se informa
        _finish(run, e)
        uow.commit()
        raise ForecastingError(str(e)) from e
    version = f"{now:%Y%m%d}.{run.id}"
    key = f"{GLOBAL_PREFIX}{version}.json"
    storage.save(key, trained.artifact)
    model = ForecastModel(
        scope=fc.SCOPE_GLOBAL,
        algorithm=forecaster.algorithm,
        version=version,
        run_id=run.id,
        artifact_key=key,
        params={**trained.params, "series": len(series)},
        features=trained.features or None,
        metrics=metrics or None,
        train_from=_month_date(min(s.months[0] for s in series)),
        train_to=_month_date(max(s.months[-1] for s in series)),
        n_samples=trained.n_samples,
    )
    model.created_at = now
    _activate(uow, storage, model)
    run.n_samples = trained.n_samples
    _finish(run)
    try:
        uow.commit()
    except Exception:
        storage.delete(key)
        raise
    return model


def _needs_training(uow: UnitOfWork, forecaster: SeriesForecaster, series: MonthlySeries) -> bool:
    model = _active(uow, fc.SCOPE_USER, series.owner_id, series.currency)
    if model is None or model.algorithm != forecaster.algorithm:
        return True
    run = uow.forecast_runs.get(model.run_id) if model.run_id else None
    return run is None or run.data_fingerprint != fingerprint(series)


def train_series(
    uow: UnitOfWork,
    storage: FileStorage,
    forecaster: SeriesForecaster,
    series: MonthlySeries,
    *,
    now: datetime | None = None,
) -> ForecastModel:
    """Entrena y activa el modelo de un cliente en una moneda."""
    now = now or datetime.now()
    run = ForecastTrainingRun(
        scope=fc.SCOPE_USER,
        algorithm=forecaster.algorithm,
        owner_id=series.owner_id,
        data_fingerprint=fingerprint(series),
        n_samples=len(series),
        params={"currency": series.currency},
    )
    run.created_at = now
    uow.forecast_runs.add(run)
    uow.commit()
    try:
        metrics = backtest_series(forecaster, series)
        params = forecaster.fit(series)
    except Exception as e:  # queda en la ejecución
        _finish(run, e)
        uow.commit()
        raise ForecastingError(str(e)) from e
    model = ForecastModel(
        scope=fc.SCOPE_USER,
        algorithm=forecaster.algorithm,
        version=f"{now:%Y%m%d}.{run.id}",
        owner_id=series.owner_id,
        currency=series.currency,
        run_id=run.id,
        params=params,
        metrics=metrics or None,
        train_from=_month_date(series.months[0]),
        train_to=_month_date(series.months[-1]),
        n_samples=len(series),
    )
    model.created_at = now
    _activate(uow, storage, model)
    _finish(run)
    uow.commit()
    return model


# --- Predicciones ----------------------------------------------------------------------


def refresh_forecasts(
    uow: UnitOfWork,
    series: MonthlySeries,
    *,
    general: tuple[ForecastModel, bytes] | None,
    global_forecaster: GlobalForecaster,
    series_forecaster: SeriesForecaster,
    now: datetime | None = None,
) -> int:
    """Escribe las predicciones de la serie y el gasto real de los meses ya cerrados."""
    now = now or datetime.now()
    current = month_key(now)
    general_q = None
    if general is not None and general[0].algorithm == global_forecaster.algorithm:
        general_q = global_forecaster.predict(general[1], series, fc.HORIZON)
    user_model = _active(uow, fc.SCOPE_USER, series.owner_id, series.currency)
    user_q = None
    if user_model is not None and user_model.algorithm == series_forecaster.algorithm:
        user_q = series_forecaster.predict(user_model.params, fc.HORIZON)
    weight = fc.user_weight(len(series)) if user_q else 0.0

    written = 0
    for h in range(1, fc.HORIZON + 1):
        month = add_months(series.months[-1], h)
        q = fc.blend(general_q[h - 1] if general_q else None, user_q[h - 1] if user_q else None, weight)
        if q is None:
            continue
        period = _month_date(month)
        existing = uow.forecasts.get(series.owner_id, series.currency, period)
        if existing is not None and month <= current:
            continue  # el mes ya empezó: su predicción queda fija para medir el error real
        forecast = existing or SpendForecast(
            owner_id=series.owner_id,
            currency=series.currency,
            period=period,
            horizon=h,
            p10=Decimal(0),
            p50=Decimal(0),
            p90=Decimal(0),
            predicted_at=now,
        )
        forecast.horizon, forecast.predicted_at, forecast.user_weight = h, now, round(weight, 3)
        forecast.p10, forecast.p50, forecast.p90 = _money(q.p10), _money(q.p50), _money(q.p90)
        forecast.global_model_id = general[0].id if general_q else None
        forecast.user_model_id = user_model.id if user_q else None
        if existing is None:
            uow.forecasts.add(forecast)
        written += 1

    actuals = dict(zip(series.months, series.values, strict=True))
    for forecast in uow.forecasts.for_owner(series.owner_id):
        month = month_key(forecast.period)
        if forecast.currency == series.currency and month in actuals:
            forecast.actual = _money(actuals[month])
    return written


def train_all(
    uow_factory: Callable[[], UnitOfWork],
    *,
    global_forecaster: GlobalForecaster,
    series_forecaster: SeriesForecaster,
    storage: FileStorage,
    retrain_global: bool,
    now: datetime | None = None,
) -> TrainingReport:
    """Una pasada completa. Un fallo en una serie no detiene las demás."""
    now = now or datetime.now()
    report = TrainingReport()
    with uow_factory() as uow:
        if retrain_global or active_global(uow) is None:
            try:
                report.global_model = train_global(uow, global_forecaster, storage, now=now)
            except ForecastingError as e:
                report.global_error = str(e)
                log.warning("Modelo general sin entrenar: %s", e)

        model = active_global(uow)
        general = None
        if model is not None and model.artifact_key:
            try:
                general = (model, storage.read(model.artifact_key))
            except FileNotFoundError:
                report.errors.append(f"Falta el archivo del modelo general {model.version}.")

        for series in build_series(uow.purchases.monthly_totals(owner_id=None), current_month=month_key(now)):
            try:
                if len(series) >= fc.MIN_USER_MONTHS and _needs_training(uow, series_forecaster, series):
                    train_series(uow, storage, series_forecaster, series, now=now)
                    report.user_models += 1
                else:
                    report.unchanged += 1
                report.forecasts += refresh_forecasts(
                    uow,
                    series,
                    general=general,
                    global_forecaster=global_forecaster,
                    series_forecaster=series_forecaster,
                    now=now,
                )
                uow.commit()
            except Exception as e:  # una serie problemática no detiene el resto
                uow.rollback()
                report.errors.append(f"{series.owner_id} ({series.currency}): {e}")
                log.exception("Fallo al entrenar o predecir %s %s", series.owner_id, series.currency)
    return report


def last_global_training(uow: UnitOfWork) -> datetime | None:
    """Cuándo terminó el último entrenamiento (correcto) del modelo general."""
    model = active_global(uow)
    return model.created_at if model else None
