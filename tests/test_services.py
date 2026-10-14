from datetime import date
from decimal import Decimal

import pytest

from app import config
from app.models import Attachment, Purchase
from app.services import (
    ValidationError,
    confirm_draft,
    create_purchase,
    delete_purchase,
    discard_draft,
    draft_values,
    find_duplicates,
    last_months,
    pending_drafts,
    purchases_in_month,
    store_upload,
    totals_by,
    update_purchase,
)
from tests.conftest import make_pdf

VALUES = {"purchase_date": date(2026, 10, 3), "vendor": "Farmacia Norte", "category": "Salud", "currency": "usd"}
ITEMS = [
    {"description": "Ibuprofeno", "quantity": 2.0, "unit_price": 3.5, "line_total": float("nan")},
    {"description": "Vendas", "quantity": None, "unit_price": "4,25", "line_total": None},
    {"description": None, "quantity": 1.0, "unit_price": None, "line_total": None},  # fila vacía del editor
]


def test_total_is_computed_from_items(db):
    p = create_purchase(db, VALUES, ITEMS)
    assert p.total == Decimal("11.25")
    assert [i.description for i in p.items] == ["Ibuprofeno", "Vendas"]
    assert p.items[1].quantity == Decimal(1)
    assert p.currency == "USD"
    assert p.source == "manual"


def test_total_from_subtotal_and_tax(db):
    p = create_purchase(db, {**VALUES, "subtotal": 100, "tax": 12}, [])
    assert p.total == Decimal("112.00")


def test_validation_errors_are_collected(db):
    with pytest.raises(ValidationError) as exc:
        create_purchase(db, {"vendor": " ", "total": "abc"}, [])
    message = str(exc.value)
    assert "Fecha" in message and "Comercio" in message and "Total" in message
    assert db.query(Purchase).count() == 0


def test_failed_update_keeps_original(db):
    p = create_purchase(db, {**VALUES, "total": 10}, [])
    with pytest.raises(ValidationError):
        update_purchase(db, p, {**VALUES, "vendor": ""}, [])
    db.expire_all()
    assert db.get(Purchase, p.id).vendor == "Farmacia Norte"


def test_import_confirm_and_delete(db):
    pdf = make_pdf(["Libreria Sur", "Fecha 2026-10-07", "Total 30.00"])
    att = store_upload(db, "factura.pdf", "application/pdf", pdf)
    assert pending_drafts(db) == [att]
    assert (config.UPLOAD_DIR / att.stored_name).read_bytes() == pdf

    values, items = draft_values(att)
    assert values["vendor"] == "Libreria Sur"
    assert values["purchase_date"] == date(2026, 10, 7)
    assert values["total"] == 30.0

    purchase = confirm_draft(db, att, {**values, "category": "Educación"}, items)
    assert purchase.source == "pdf"
    assert purchase.attachments == [att]
    assert pending_drafts(db) == []

    again = store_upload(db, "copia.pdf", None, pdf)
    assert find_duplicates(db, again) == [att]

    path = config.UPLOAD_DIR / att.stored_name
    delete_purchase(db, purchase)
    assert not path.exists()
    assert db.query(Attachment).all() == [again]  # el duplicado sigue pendiente


def test_discard_draft_removes_file(db):
    att = store_upload(db, "x.png", "image/png", b"\x89PNG")
    path = config.UPLOAD_DIR / att.stored_name
    assert att.extraction_error  # el extractor local no lee imágenes
    discard_draft(db, att)
    assert not path.exists()
    assert pending_drafts(db) == []


def test_monthly_grouping(db):
    create_purchase(db, {**VALUES, "total": 10}, [])
    create_purchase(db, {**VALUES, "total": 5, "currency": "EUR"}, [])
    create_purchase(db, {**VALUES, "purchase_date": date(2026, 9, 30), "total": 99}, [])
    october = purchases_in_month(db, "2026-10")
    assert len(october) == 2
    assert totals_by(october, lambda p: p.category) == {"Salud": {"USD": Decimal("10.00"), "EUR": Decimal("5.00")}}


def test_last_months_crosses_year():
    assert last_months(3, date(2026, 2, 15)) == ["2025-12", "2026-01", "2026-02"]
