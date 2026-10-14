"""Tests de las páginas de Streamlit con AppTest (sin navegador)."""

from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.models import Purchase
from app.services import create_purchase, store_upload
from tests.conftest import make_pdf

ROOT = Path(__file__).resolve().parent.parent


def run_page(path: str) -> AppTest:
    at = AppTest.from_file(str(ROOT / path), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_entrypoint_renders(db):
    run_page("streamlit_app.py")


def test_new_purchase_form_saves(db):
    at = run_page("app_pages/nueva_compra.py")
    at.text_input[0].set_value("Panadería Luna")
    at.number_input[2].set_value(7.5)  # Total
    at.button[0].click().run()
    assert not at.exception, at.exception
    assert not at.error
    p = db.query(Purchase).one()
    assert (p.vendor, float(p.total), p.purchase_date) == ("Panadería Luna", 7.5, date.today())


def test_new_purchase_shows_validation_error(db):
    at = run_page("app_pages/nueva_compra.py")
    at.button[0].click().run()
    assert "Comercio: obligatorio" in at.error[0].value
    assert db.query(Purchase).count() == 0


def test_summary_lists_month_purchases(db):
    create_purchase(db, {"purchase_date": date.today(), "vendor": "Mercado Azul", "total": 20}, [])
    at = run_page("app_pages/resumen.py")
    table = at.dataframe[0].value
    assert list(table["Comercio"]) == ["Mercado Azul"]


def test_import_page_prefills_draft(db):
    store_upload(db, "f.pdf", "application/pdf", make_pdf(["Libreria Sur", "Total 30.00"]))
    at = run_page("app_pages/importar.py")
    assert at.text_input[0].value == "Libreria Sur"
    submit = next(b for b in at.button if b.label == "Confirmar compra")
    submit.click().run()
    assert not at.exception, at.exception
    p = db.query(Purchase).one()
    assert p.source == "pdf" and float(p.total) == 30.0


def select_first_row(monkeypatch, at: AppTest) -> None:
    """AppTest no permite seleccionar filas de st.dataframe; se inyecta el estado
    que enviaría el navegador en cada rerun."""
    import json

    from streamlit.proto.WidgetStates_pb2 import WidgetState
    from streamlit.testing.v1.element_tree import ElementTree

    widget_id = at.dataframe[0].proto.id
    original = ElementTree.get_widget_states

    def with_selection(self):
        states = original(self)
        if all(w.id != widget_id for w in states.widgets):
            ws = WidgetState(id=widget_id)
            ws.string_value = json.dumps({"selection": {"rows": [0], "columns": [], "cells": []}})
            states.widgets.append(ws)
        return states

    monkeypatch.setattr(ElementTree, "get_widget_states", with_selection)
    at.run()


def test_summary_edit_and_delete(db, monkeypatch):
    create_purchase(db, {"purchase_date": date.today(), "vendor": "Mercado Azul", "total": 20}, [])
    at = run_page("app_pages/resumen.py")
    select_first_row(monkeypatch, at)
    assert "Mercado Azul · USD 20.00" in [s.value for s in at.subheader]

    next(b for b in at.button if b.label == "Editar").click().run()
    next(t for t in at.text_input if t.label == "Comercio *").set_value("Mercado Azul Centro")
    next(b for b in at.button if b.label == "Guardar compra").click().run()
    assert not at.exception, at.exception
    db.expire_all()
    assert db.query(Purchase).one().vendor == "Mercado Azul Centro"

    next(b for b in at.button if b.label == "Sí, eliminar").click().run()
    assert not at.exception, at.exception
    assert db.query(Purchase).count() == 0
