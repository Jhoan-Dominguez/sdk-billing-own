from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import billing
from billing import bootstrap
from billing.application import imports
from billing.application import purchases as purchase_service
from billing.domain.auth import ADMIN, CUSTOMER
from billing.domain.models import User
from billing.infrastructure.extraction.extractors import RegexExtractor
from billing.infrastructure.persistence.memory.backend import MemoryBackend
from tests.conftest import ADMIN_ID, ADMIN_VIEWER, ANA_ID, ANA_VIEWER, BETO_ID, BETO_VIEWER, make_pdf

PAGES_DIR = Path(billing.__file__).parent / "presentation" / "streamlit" / "pages"

MONTH = date.today().replace(day=5)


@pytest.fixture
def app_backend(monkeypatch, storage):
    """La app (bootstrap) usa un backend en memoria con compras de Ana y Beto."""
    backend = MemoryBackend()
    backend.init_schema()
    with backend.unit_of_work() as uow:
        uow.users.add(User(id=ADMIN_ID, username="admin", name="Admin", role=ADMIN))
        uow.users.add(User(id=ANA_ID, username="ana", name="Ana", role=CUSTOMER))
        uow.users.add(User(id=BETO_ID, username="beto", name="Beto", role=CUSTOMER))
        uow.commit()
        for owner, vendor, total in ((ANA_ID, "Panadería Ana", "12.50"), (BETO_ID, "Ferretería Beto", "80")):
            values = {"purchase_date": MONTH, "vendor": vendor, "total": total, "currency": "USD"}
            purchase_service.create(uow, values, [], owner_id=owner)
    monkeypatch.setattr(bootstrap, "persistence", lambda: backend)
    monkeypatch.setattr(bootstrap, "file_storage", lambda: storage)
    return backend


def run_page(name: str, viewer=None) -> AppTest:
    at = AppTest.from_file(str(PAGES_DIR / f"{name}.py"), default_timeout=30)
    if viewer is not None:
        at.session_state["viewer"] = viewer
    return at.run()


def page_text(at: AppTest) -> str:
    texts = [e.value for e in (*at.markdown, *at.caption, *at.info, *at.error, *at.title)]
    texts += [df.value.to_csv() for df in at.dataframe]
    return "\n".join(str(t) for t in texts)


def test_page_without_viewer_shows_nothing(app_backend):
    at = run_page("summary_table")
    assert not at.exception
    assert "Sesión no válida" in at.error[0].value
    assert "Panadería" not in page_text(at)


def test_customer_only_sees_own_purchases(app_backend):
    at = run_page("summary_table", ANA_VIEWER)
    assert not at.exception
    text = page_text(at)
    assert "Panadería Ana" in text
    assert "Ferretería Beto" not in text


ADMIN_PAGES = ("users", "ml_models", "system", "audit", "data_model")


@pytest.fixture
def admin_app(app_backend, monkeypatch, directory):
    """Páginas de administración sin Keycloak ni servicios reales."""
    from billing.presentation.streamlit.components import admin as admin_component

    monkeypatch.setattr(bootstrap, "user_directory", lambda: directory)
    monkeypatch.setattr(bootstrap, "service_checks", lambda: {"Base de datos": lambda: "memory"})
    admin_component.identity_statuses.clear()
    return app_backend


@pytest.mark.parametrize("page", ADMIN_PAGES)
def test_admin_pages_reject_customers(admin_app, page):
    at = run_page(page, ANA_VIEWER)
    assert not at.exception
    assert "No tienes permiso" in at.error[0].value


@pytest.mark.parametrize("page", ADMIN_PAGES)
def test_admin_pages_render_without_purchase_content(admin_app, page):
    at = run_page(page, ADMIN_VIEWER)
    assert not at.exception, at.exception
    text = page_text(at)
    assert "Panadería Ana" not in text and "Ferretería Beto" not in text
    assert "12.50" not in text and "80.00" not in text


def test_users_page_lists_accounts_with_usage(admin_app):
    at = run_page("users", ADMIN_VIEWER)
    table = at.dataframe[0].value
    assert {"Ana", "Beto", "Admin"} <= set(table["Nombre"])
    assert table.set_index("Nombre").loc["Ana", "Compras"] == 1
    assert "Total" not in table.columns


def test_ml_models_page_shows_metrics(admin_app):
    from billing.domain import forecasting
    from billing.domain.models import ForecastModel

    with admin_app.unit_of_work() as uow:
        uow.forecast_models.add(
            ForecastModel(
                scope=forecasting.SCOPE_GLOBAL,
                algorithm="lightgbm",
                version="2026.10.1",
                metrics={"mape": 12.5, "mae": 0.08, "mase": 0.7, "coverage": 81},
            )
        )
        uow.commit()
    at = run_page("ml_models", ADMIN_VIEWER)
    assert not at.exception
    table = at.dataframe[0].value
    assert table.loc[0, "Versión"] == "2026.10.1"
    assert table.loc[0, "Acierto"] == pytest.approx(87.5)
    assert any(m.value == "87.5 %" for m in at.metric)


def test_data_model_page_without_schema(admin_app):
    at = run_page("data_model", ADMIN_VIEWER)
    assert "no tiene esquema" in at.info[0].value


def test_import_page_hides_other_users_drafts(app_backend, storage):
    with app_backend.unit_of_work() as uow:
        raw = make_pdf(["Libreria Beto", "Total 9.99"])
        imports.store_upload(uow, storage, RegexExtractor(), "beto.pdf", None, raw, owner_id=BETO_ID)
        imports.store_upload(uow, storage, RegexExtractor(), "ana.pdf", None, raw, owner_id=ANA_ID)
    at = run_page("imports", ANA_VIEWER)
    assert not at.exception
    text = page_text(at) + str([s.options for s in at.selectbox])
    assert "ana.pdf" in text and "beto.pdf" not in text
    at = run_page("imports", BETO_VIEWER)
    text = page_text(at) + str([s.options for s in at.selectbox])
    assert "beto.pdf" in text and "ana.pdf" not in text
