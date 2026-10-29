"""Consulta de los modelos de predicción y sus entrenamientos (vista del administrador)."""

from dataclasses import dataclass

from billing.application.admin.accounts import require_manager
from billing.domain import forecasting
from billing.domain.auth import Viewer
from billing.domain.models import ForecastModel, ForecastTrainingRun
from billing.domain.ports.repositories import UnitOfWork


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
        """Versiones del mismo alcance (y cliente), de la más antigua a la más reciente."""
        same = [m for m in self.models if m.scope == model.scope and m.owner_id == model.owner_id]
        return sorted(same, key=lambda m: m.id)

    def owner_label(self, model: ForecastModel | ForecastTrainingRun) -> str:
        if model.owner_id is None:
            return "Todos los clientes"
        return self.owners.get(model.owner_id, model.owner_id)


def overview(uow: UnitOfWork, actor: Viewer, *, runs_limit: int = 200) -> ModelsOverview:
    require_manager(actor)
    models = uow.forecast_models.list()
    runs = uow.forecast_runs.list(limit=runs_limit)
    owners = {u.id: u.display_name for u in uow.users.list()}
    return ModelsOverview(models, runs, owners)
