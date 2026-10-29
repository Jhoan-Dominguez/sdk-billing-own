import json
import math
from datetime import date, datetime
from decimal import Decimal

import pytest

from billing.application import purchases as purchase_service
from billing.application.admin import accounts
from billing.application.forecasting import models as model_service
from billing.application.forecasting import outlook as outlook_service
from billing.application.forecasting import training
from billing.application.forecasting.series import build_series, fingerprint
from billing.domain import admin
from billing.domain import forecasting as fc
from billing.domain.errors import PermissionDenied
from billing.domain.forecasting import MonthlySeries, Quantiles
from billing.domain.periods import add_months
from billing.domain.ports.forecasting import ForecastingError
from billing.infrastructure.ml.baseline import BaselineGlobalForecaster, BaselineSeriesForecaster
from billing.infrastructure.ml.ets import DampedTrendForecaster
from tests.conftest import ADMIN_VIEWER, ANA_ID, ANA_VIEWER, BETO_ID

NOW = datetime(2026, 10, 15, 12, 0)
FIRST = "2025-07"  # 15 meses completos hasta septiembre de 2026


def seasonal(month: str, base: float) -> float:
    """Gasto con estacionalidad anual (sube en diciembre) y una tendencia suave."""
    m = int(month[5:7])
    index = (int(month[:4]) - 2025) * 12 + m
    return round(base * (1 + 0.3 * math.sin(2 * math.pi * m / 12)) + 2 * index, 2)


def add_history(uow, owner_id, base, currency="USD", months=15, first=FIRST):
    for i in range(months):
        month = add_months(first, i)
        for day, share in ((5, 0.6), (20, 0.4)):
            purchase_service.create(
                uow,
                {
                    "purchase_date": date.fromisoformat(f"{month}-{day:02d}"),
                    "vendor": "Tienda",
                    "currency": currency,
                    "total": str(round(seasonal(month, base) * share, 2)),
                },
                [],
                owner_id=owner_id,
            )


def train(backend, storage, now=NOW, retrain_global=True, global_forecaster=None):
    return training.train_all(
        backend.unit_of_work,
        global_forecaster=global_forecaster or BaselineGlobalForecaster(),
        series_forecaster=DampedTrendForecaster(),
        storage=storage,
        retrain_global=retrain_global,
        now=now,
    )


# --- Dominio ---------------------------------------------------------------------------


def test_user_weight_grows_with_history():
    assert fc.user_weight(2) == 0
    assert 0 < fc.user_weight(3) < fc.user_weight(8) < fc.user_weight(12) == fc.MAX_USER_WEIGHT
    assert fc.user_weight(40) == fc.MAX_USER_WEIGHT


def test_blend_and_ordering():
    general, user = Quantiles(80, 100, 120), Quantiles(180, 200, 220)
    assert fc.blend(general, user, 0.5) == Quantiles(130, 150, 170)
    assert fc.blend(None, user, 0.5) is user and fc.blend(general, None, 0.5) is general
    assert Quantiles(-5, 10, 3).ordered() == Quantiles(0, 3, 10)


def test_backtest_metrics():
    metrics = fc.backtest_metrics([100, 200], [Quantiles(90, 110, 130), Quantiles(150, 180, 190)], [90, 100])
    assert metrics["mae"] == 15 and metrics["mape"] == 10.0
    assert metrics["mase"] == round(15 / 55, 3) and metrics["coverage"] == 50.0
    assert fc.accuracy_pct(metrics) == 90.0
    assert fc.backtest_metrics([], [], []) == {}


def test_add_months():
    assert add_months("2026-11", 2) == "2027-01" and add_months("2026-01", -1) == "2025-12"


def test_build_series_fills_gaps_and_skips_current_month():
    rows = [
        ("u", "USD", "2026-06", Decimal("10")),
        ("u", "USD", "2026-08", Decimal("30")),
        ("u", "USD", "2026-10", Decimal("99")),  # mes en curso: incompleto
        ("u", "EUR", "2026-09", Decimal("5")),
    ]
    series = {s.currency: s for s in build_series(rows, current_month="2026-10")}
    assert series["USD"].months == ("2026-06", "2026-07", "2026-08", "2026-09")
    assert series["USD"].values == (10.0, 0.0, 30.0, 0.0)
    assert series["EUR"].values == (5.0,)
    assert fingerprint(series["USD"]) == fingerprint(build_series(rows, current_month="2026-10")[1])


# --- Algoritmos --------------------------------------------------------------------------


def make_series(owner="u", base=500.0, months=24, first="2024-10") -> MonthlySeries:
    keys = tuple(add_months(first, i) for i in range(months))
    return MonthlySeries(owner, "USD", keys, tuple(seasonal(m, base) for m in keys))


def test_ets_learns_level_and_is_json_serializable():
    series = make_series()
    model = DampedTrendForecaster()
    params = model.fit(series)
    json.dumps(params)
    assert params["seasonal"] is not None  # 24 meses: con estacionalidad
    forecast = model.predict(params, 3)
    assert all(q.p10 <= q.p50 <= q.p90 for q in forecast)
    assert abs(forecast[0].p50 - seasonal(add_months(series.months[-1], 1), 500)) < 150
    short = model.fit(series.head(4))
    assert short["seasonal"] is None and model.predict(short, 1)[0].p50 > 0


def test_baselines():
    series = make_series(months=6)
    params = BaselineSeriesForecaster().fit(series)
    assert BaselineSeriesForecaster().predict(params, 2)[0].p50 == pytest.approx(sum(series.values[-3:]) / 3)
    general = BaselineGlobalForecaster()
    trained = general.fit([series])
    assert general.predict(trained.artifact, series, 1)[0].p50 == pytest.approx(sum(series.values[-3:]) / 3)


def test_lightgbm_global_model():
    pytest.importorskip("lightgbm")
    from billing.infrastructure.ml.lightgbm_model import LightGBMForecaster

    series = [make_series(owner=f"u{i}", base=100 * (i + 1)) for i in range(5)]
    model = LightGBMForecaster(rounds=60)
    trained = model.fit(series)
    artifact = json.loads(trained.artifact)  # JSON, sin pickle
    assert set(artifact["boosters"]) == {"p10", "p50", "p90"} and trained.n_samples > 50
    forecast = model.predict(trained.artifact, series[2], fc.HORIZON)
    assert len(forecast) == fc.HORIZON and all(q.p10 <= q.p50 <= q.p90 for q in forecast)
    assert 100 < forecast[0].p50 < 700  # en la escala del cliente (base 300)
    with pytest.raises(ForecastingError, match="Pocos datos"):
        model.fit([make_series(months=4)])


# --- Entrenamiento ---------------------------------------------------------------------


def test_train_all_trains_models_and_forecasts(backend, storage):
    with backend.unit_of_work() as uow:
        add_history(uow, ANA_ID, 500)
        add_history(uow, BETO_ID, 80, currency="EUR", months=2, first="2026-08")
    report = train(backend, storage)
    assert report.global_model is not None and not report.errors
    assert report.user_models == 1  # Beto solo tiene 2 meses: sin modelo propio

    with backend.unit_of_work() as uow:
        user_models = [m for m in uow.forecast_models.list() if m.scope == fc.SCOPE_USER]
        assert [(m.owner_id, m.currency) for m in user_models] == [(ANA_ID, "USD")]
        assert user_models[0].metrics["evaluations"] == fc.BACKTEST_MONTHS
        assert storage.read(report.global_model.artifact_key)
        ana = uow.forecasts.for_owner(ANA_ID)
        assert [f"{f.period:%Y-%m}" for f in ana] == ["2026-10", "2026-11", "2026-12", "2027-01"]
        assert all(f.user_weight == fc.MAX_USER_WEIGHT and f.user_model_id for f in ana)
        beto = uow.forecasts.for_owner(BETO_ID)
        assert beto and all(f.user_model_id is None and f.global_model_id for f in beto)


def test_retraining_only_when_data_changes_and_months_freeze(backend, storage):
    with backend.unit_of_work() as uow:
        add_history(uow, ANA_ID, 500)
    train(backend, storage)
    with backend.unit_of_work() as uow:
        october = uow.forecasts.get(ANA_ID, "USD", date(2026, 10, 1))
        frozen = october.p50

    assert train(backend, storage, retrain_global=False).unchanged == 1

    with backend.unit_of_work() as uow:  # una compra nueva en un mes cerrado: hay que reentrenar
        purchase_service.create(
            uow,
            {"purchase_date": date(2026, 9, 9), "vendor": "X", "currency": "USD", "total": "900"},
            [],
            owner_id=ANA_ID,
        )
    assert train(backend, storage, retrain_global=False).user_models == 1
    with backend.unit_of_work() as uow:
        assert uow.forecasts.get(ANA_ID, "USD", date(2026, 10, 1)).p50 == frozen  # octubre ya empezó
        assert len([m for m in uow.forecast_models.list(scope=fc.SCOPE_USER)]) == 2
        assert len([m for m in uow.forecast_models.list(scope=fc.SCOPE_USER, status=fc.MODEL_ACTIVE)]) == 1

    # Un mes después, octubre está cerrado: guarda el gasto real.
    with backend.unit_of_work() as uow:
        purchase_service.create(
            uow,
            {"purchase_date": date(2026, 10, 3), "vendor": "X", "currency": "USD", "total": "640"},
            [],
            owner_id=ANA_ID,
        )
    train(backend, storage, now=datetime(2026, 11, 10), retrain_global=False)
    with backend.unit_of_work() as uow:
        october = uow.forecasts.get(ANA_ID, "USD", date(2026, 10, 1))
        assert october.p50 == frozen and october.actual == Decimal("640.00")


def test_failed_global_training_is_recorded(backend, storage):
    class Broken(BaselineGlobalForecaster):
        algorithm = "broken"

        def fit(self, series):
            raise ForecastingError("sin datos")

    with backend.unit_of_work() as uow:
        add_history(uow, ANA_ID, 500)
    report = train(backend, storage, global_forecaster=Broken())
    assert report.global_error and report.user_models == 1  # el resto sigue
    with backend.unit_of_work() as uow:
        runs = uow.forecast_runs.list()
        assert any(r.status == fc.RUN_FAILED and r.error for r in runs)
        assert all(f.global_model_id is None for f in uow.forecasts.for_owner(ANA_ID))


def test_train_now_requires_admin_and_is_audited(backend, storage):
    with backend.unit_of_work() as uow:
        add_history(uow, ANA_ID, 500)
    kwargs = {
        "global_forecaster": BaselineGlobalForecaster(),
        "series_forecaster": DampedTrendForecaster(),
        "storage": storage,
    }
    with pytest.raises(PermissionDenied):
        model_service.train_now(backend.unit_of_work, ANA_VIEWER, **kwargs)
    report = model_service.train_now(backend.unit_of_work, ADMIN_VIEWER, **kwargs)
    assert report.global_model
    with backend.unit_of_work() as uow:
        entry = uow.audit_log.list()[0]
        assert entry.action == admin.TRAIN_MODELS and entry.details["user_models"] == 1


def test_deleting_user_removes_forecasts(backend, storage, directory):
    with backend.unit_of_work() as uow:
        add_history(uow, ANA_ID, 500)
    train(backend, storage)
    with backend.unit_of_work() as uow:
        accounts.delete(uow, storage, directory, ADMIN_VIEWER, uow.users.get(ANA_ID))
    with backend.unit_of_work() as uow:
        assert uow.forecasts.for_owner(ANA_ID) == []
        assert [m.scope for m in uow.forecast_models.list()] == [fc.SCOPE_GLOBAL]


# --- Vista del cliente -------------------------------------------------------------


def test_outlook_projects_current_month(backend, storage):
    with backend.unit_of_work() as uow:
        add_history(uow, ANA_ID, 500)
        purchase_service.create(  # a mitad de octubre ya gastó mucho más de lo habitual
            uow,
            {"purchase_date": date(2026, 10, 4), "vendor": "X", "currency": "USD", "total": "2000"},
            [],
            owner_id=ANA_ID,
        )
    train(backend, storage)
    with backend.unit_of_work() as uow:
        (item,) = outlook_service.outlook(uow, owner_id=ANA_ID, today=NOW.date())
        assert item.currency == "USD" and item.current and len(item.upcoming) == fc.HORIZON - 1
        assert item.projection.spent == 2000 and item.projection.expected >= 2000
        assert item.above_usual
        assert outlook_service.outlook(uow, owner_id=BETO_ID, today=NOW.date()) == []
