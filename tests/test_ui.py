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
from tests.conftest import ADMIN_ID, ADMIN_VIEWER, ANA_ID, ANA_VIEWER, BETO_ID, make_pdf

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


def test_admin_sees_everyone(app_backend):
    at = run_page("summary_table", ADMIN_VIEWER)
    assert not at.exception
    text = page_text(at)
    assert "Panadería Ana" in text and "Ferretería Beto" in text


def test_comparison_page_for_admin(app_backend):
    at = run_page("comparison", ADMIN_VIEWER)
    assert not at.exception
    assert at.title[0].value == "Comparativa de clientes"
    assert not at.error


def test_comparison_page_rejects_customer(app_backend):
    at = run_page("comparison", ANA_VIEWER)
    assert "No tienes permiso" in at.error[0].value


def test_import_page_hides_other_users_drafts(app_backend, storage):
    with app_backend.unit_of_work() as uow:
        raw = make_pdf(["Libreria Beto", "Total 9.99"])
        imports.store_upload(uow, storage, RegexExtractor(), "beto.pdf", None, raw, owner_id=BETO_ID)
        imports.store_upload(uow, storage, RegexExtractor(), "ana.pdf", None, raw, owner_id=ANA_ID)
    at = run_page("imports", ANA_VIEWER)
    assert not at.exception
    text = page_text(at) + str([s.options for s in at.selectbox])
    assert "ana.pdf" in text and "beto.pdf" not in text
    at = run_page("imports", ADMIN_VIEWER)  # tampoco el admin: los borradores son de su dueño
    assert "beto.pdf" not in page_text(at) + str([s.options for s in at.selectbox])
