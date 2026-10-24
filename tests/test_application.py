from datetime import date
from decimal import Decimal

import pytest

from billing.application import categories as category_service
from billing.application import imports
from billing.application import purchases as purchase_service
from billing.application import users as user_service
from billing.domain.auth import CUSTOMER
from billing.domain.catalog import FALLBACK_CATEGORY, SOURCE_BANK, SOURCE_MANUAL
from billing.domain.errors import ValidationError
from billing.domain.files import KIND_PDF
from billing.infrastructure.extraction import bank_rules
from billing.infrastructure.extraction.bank import RuleBankParser
from billing.infrastructure.extraction.extractors import RegexExtractor
from tests.conftest import ADMIN_ID, ANA_ID, BETO_ID, make_email, make_pdf

VALUES = {"purchase_date": date(2026, 10, 5), "vendor": "Tienda", "currency": "usd", "category": "Supermercado"}


def new_purchase(uow, owner_id=ANA_ID, **values):
    return purchase_service.create(uow, {**VALUES, **values}, [], owner_id=owner_id)


def upload(uow, storage, owner_id=ANA_ID, raw=None, filename="factura.pdf"):
    raw = raw or make_pdf(["Ferreteria Central", "Fecha 2026-10-05", "Total 45.90"])
    return imports.store_upload(
        uow, storage, RegexExtractor(), filename, None, raw, owner_id=owner_id, bank_parser=RuleBankParser()
    )


def test_total_is_computed_from_items(uow):
    items = [
        {"description": "Pan", "quantity": 2, "unit_price": "1.25"},
        {"description": "Leche", "line_total": "3.10"},
        {"description": "", "line_total": "99"},  # sin descripción: se ignora
    ]
    p = purchase_service.create(uow, VALUES, items, owner_id=ANA_ID)
    assert p.total == Decimal("5.60")
    assert p.currency == "USD"
    assert p.source == SOURCE_MANUAL
    assert [i.description for i in p.items] == ["Pan", "Leche"]


def test_total_from_subtotal_and_tax(uow):
    p = new_purchase(uow, subtotal="100", tax="12")
    assert p.total == Decimal("112")


def test_validation_errors_are_collected(uow):
    with pytest.raises(ValidationError) as e:
        purchase_service.create(uow, {"total": "abc"}, [], owner_id=ANA_ID)
    message = str(e.value)
    assert "Fecha" in message and "Comercio" in message and "Total" in message


def test_failed_update_keeps_original(backend):
    with backend.unit_of_work() as uow:
        purchase_id = new_purchase(uow, total="10").id
    with backend.unit_of_work() as uow:
        p = purchase_service.get(uow, purchase_id, owner_id=ANA_ID)
        with pytest.raises(ValidationError):
            purchase_service.update(uow, p, {**VALUES, "vendor": ""}, [])
    with backend.unit_of_work() as uow:
        assert purchase_service.get(uow, purchase_id, owner_id=ANA_ID).vendor == "Tienda"


def test_purchases_are_scoped_to_owner(uow):
    mine = new_purchase(uow, total="10")
    new_purchase(uow, owner_id=BETO_ID, total="20")
    assert purchase_service.get(uow, mine.id, owner_id=BETO_ID) is None
    assert purchase_service.get(uow, mine.id, owner_id=None) is not None  # admin
    assert [p.owner_id for p in purchase_service.in_month(uow, "2026-10", owner_id=ANA_ID)] == [ANA_ID]
    assert len(purchase_service.in_month(uow, "2026-10", owner_id=None)) == 2
    assert purchase_service.in_month(uow, "2026-11", owner_id=None) == []


def test_import_confirm_and_delete(backend, storage):
    with backend.unit_of_work() as uow:
        att = upload(uow, storage)
        att_id, key = att.id, att.stored_name
        assert att.is_draft and att.kind == KIND_PDF
        assert storage.read(key).startswith(b"%PDF")
    with backend.unit_of_work() as uow:
        draft = imports.get_draft(uow, att_id, owner_id=ANA_ID)
        values, items = imports.draft_values(draft)
        assert values["vendor"] == "Ferreteria Central"
        assert values["purchase_date"] == date(2026, 10, 5)
        purchase = imports.confirm_draft(uow, draft, values, items)
        purchase_id = purchase.id
        assert purchase.total == Decimal("45.90")
        assert purchase.source == KIND_PDF
    with backend.unit_of_work() as uow:
        assert imports.get_draft(uow, att_id, owner_id=ANA_ID) is None  # ya no es borrador
        purchase = purchase_service.get(uow, purchase_id, owner_id=ANA_ID)
        assert [a.id for a in purchase.attachments] == [att_id]
        purchase_service.delete(uow, storage, purchase)
    with pytest.raises(FileNotFoundError):
        storage.read(key)


def test_discard_draft_removes_file(uow, storage):
    att = upload(uow, storage)
    key = att.stored_name
    imports.discard_draft(uow, storage, att)
    assert imports.drafts(uow, owner_id=ANA_ID) == []
    with pytest.raises(FileNotFoundError):
        storage.read(key)


def test_bank_email_becomes_bank_purchase(uow, storage):
    example = bank_rules.TEMPLATES[0].patterns[0].example
    att = upload(uow, storage, raw=make_email(example), filename="alerta.eml")
    assert att.document_type == "bank_notification"
    values, items = imports.draft_values(att)
    purchase = imports.confirm_draft(uow, att, values, items)
    assert purchase.source == SOURCE_BANK


def test_drafts_and_duplicates_are_scoped_to_owner(uow, storage):
    pdf = make_pdf(["Total 10.00"])
    first = upload(uow, storage, raw=pdf)
    second = upload(uow, storage, raw=pdf)
    other = upload(uow, storage, owner_id=BETO_ID, raw=pdf)
    assert {a.id for a in imports.drafts(uow, owner_id=ANA_ID)} == {first.id, second.id}
    assert len(imports.drafts(uow, owner_id=None)) == 3
    assert [a.id for a in imports.find_duplicates(uow, first)] == [second.id]  # sin el de Beto
    assert imports.get_draft(uow, other.id, owner_id=ANA_ID) is None


def test_similar_purchases(uow, storage):
    new_purchase(uow, total="45.90", purchase_date=date(2026, 10, 6))
    new_purchase(uow, owner_id=BETO_ID, total="45.90")
    att = upload(uow, storage)
    assert [p.owner_id for p in imports.similar_purchases(uow, att)] == [ANA_ID]


def test_category_rename_and_delete_move_purchases(uow):
    category = category_service.create(uow, "Mascotas", owner_id=ANA_ID)
    new_purchase(uow, total="10", category="Mascotas")
    assert category_service.rename(uow, category, "Animales") == 1
    assert purchase_service.in_month(uow, "2026-10", owner_id=ANA_ID)[0].category == "Animales"
    assert category_service.delete(uow, category) == 1
    assert purchase_service.in_month(uow, "2026-10", owner_id=ANA_ID)[0].category == FALLBACK_CATEGORY
    assert "Animales" not in category_service.names(uow, owner_id=ANA_ID)


def test_category_names_are_unique_per_scope(uow):
    category_service.create(uow, "Mascotas", owner_id=ANA_ID)
    with pytest.raises(ValidationError):
        category_service.create(uow, "mascotas", owner_id=ANA_ID)
    category_service.create(uow, "Mascotas", owner_id=BETO_ID)  # otro usuario: permitido
    fallback = next(c for c in category_service.visible_to(uow, owner_id=None) if c.name == FALLBACK_CATEGORY)
    with pytest.raises(ValidationError):
        category_service.delete(uow, fallback)


def test_sync_user_creates_and_updates(uow):
    claims = {"sub": "sub-new", "preferred_username": "nuevo", "name": "Nuevo", "email": "n@billing.example.com"}
    user = user_service.sync_from_claims(uow, claims, CUSTOMER)
    assert (user.username, user.role) == ("nuevo", CUSTOMER)
    user_service.sync_from_claims(uow, {**claims, "name": "Renombrado"}, CUSTOMER)
    assert user_service.get(uow, "sub-new").name == "Renombrado"
    assert {u.id for u in user_service.list_users(uow, role=CUSTOMER)} == {ANA_ID, BETO_ID, "sub-new"}
    assert ADMIN_ID not in {u.id for u in user_service.list_users(uow, role=CUSTOMER)}
