"""Modelos de predicción para el administrador: consulta y entrenamiento a demanda."""

from collections.abc import Callable
from dataclasses import dataclass

from billing.application.admin import audit
from billing.application.admin.accounts import require_manager
from billing.application.forecasting import training
from billing.domain import admin, forecasting
from billing.domain.auth import Viewer
from billing.domain.models import ForecastModel, ForecastTrainingRun
from billing.domain.ports.forecasting import GlobalForecaster, SeriesForecaster
from billing.domain.ports.repositories import UnitOfWork
from billing.domain.ports.storage import FileStorage


@dataclass(frozen=True)
class ModelsOverview:
    models: list[ForecastModel]
    runs: list[ForecastTrainingRun]
    owners: dict[str, str]  # id -> nombre de los clientes con modelo propio

    @property
    def active(self) -> list[ForecastModel]:
        return [m for m in self.models if m.status == forecasting.MODEL_ACTIVE]

    @property
    def active_global(self) -> ForecastModel | None:
        return next((m for m in self.active if m.scope == forecasting.SCOPE_GLOBAL), None)

    @property
    def mean_accuracy(self) -> float | None:
        """Acierto medio de los modelos activos que lo tienen."""
        values = [a for m in self.active if (a := forecasting.accuracy_pct(m.metrics)) is not None]
        return sum(values) / len(values) if values else None

    @property
    def last_run(self) -> ForecastTrainingRun | None:
        return self.runs[0] if self.runs else None

    def history(self, model: ForecastModel) -> list[ForecastModel]:
        """Versiones del mismo alcance (y cliente y moneda), de la más antigua a la más reciente."""
        key = (model.scope, model.owner_id, model.currency)
        same = [m for m in self.models if (m.scope, m.owner_id, m.currency) == key]
        return sorted(same, key=lambda m: m.id)

    def owner_label(self, model: ForecastModel | ForecastTrainingRun) -> str:
        if model.owner_id is None:
            return "Todos los clientes"
        return self.owners.get(model.owner_id, model.owner_id)

    def run_currency(self, run: ForecastTrainingRun) -> str | None:
        return (run.params or {}).get("currency")


def overview(uow: UnitOfWork, actor: Viewer, *, runs_limit: int = 200) -> ModelsOverview:
    require_manager(actor)
    models = uow.forecast_models.list()
    runs = uow.forecast_runs.list(limit=runs_limit)
    owners = {u.id: u.display_name for u in uow.users.list()}
    return ModelsOverview(models, runs, owners)


def train_now(
    uow_factory: Callable[[], UnitOfWork],
    actor: Viewer,
    *,
    global_forecaster: GlobalForecaster,
    series_forecaster: SeriesForecaster,
    storage: FileStorage,
) -> training.TrainingReport:
    """Entrena ya todos los modelos (incluido el general) y deja constancia en la auditoría."""
    require_manager(actor)
    report = training.train_all(
        uow_factory,
        global_forecaster=global_forecaster,
        series_forecaster=series_forecaster,
        storage=storage,
        retrain_global=True,
    )
    with uow_factory() as uow:
        audit.record(
            uow,
            actor,
            admin.TRAIN_MODELS,
            details={
                "global": report.global_model.version if report.global_model else None,
                "global_error": report.global_error,
                "user_models": report.user_models,
                "forecasts": report.forecasts,
                "errors": report.errors[:10],
            },
        )
    return report
