from datetime import date

import pytest

from billing.domain import auth
from billing.domain.bank import PURCHASE, TRANSFER, WITHDRAWAL, BankNotification, transaction_label
from billing.domain.errors import UnsupportedFile
from billing.domain.files import KIND_IMAGE, KIND_PDF, classify
from billing.domain.invoice import InvoiceData, consistency_warnings
from billing.domain.periods import last_months, month_bounds
from tests.conftest import ADMIN_VIEWER, ANA_ID, ANA_VIEWER, BETO_ID


@pytest.mark.parametrize(
    "claims, expected",
    [
        ({"roles": ["admin", "customer"]}, auth.ADMIN),
        ({"roles": ["customer"]}, auth.CUSTOMER),
        ({"roles": "customer"}, auth.CUSTOMER),
        ({"roles": ["offline_access"]}, None),
        ({}, None),
    ],
)
def test_primary_role(claims, expected):
    assert auth.primary_role(claims) == expected


def test_every_role_has_pages_and_unknown_role_has_none():
    for role in auth.ROLES:
        assert auth.can_view(role, "settings")
    # El administrador no ve compras: solo comparte Configuración con los clientes.
    for page in ("summary", "summary_table", "imports"):
        assert auth.can_view(auth.CUSTOMER, page) and not auth.can_view(auth.ADMIN, page)
    for page in ("users", "ml_models", "system", "audit", "data_model"):
        assert auth.can_view(auth.ADMIN, page) and not auth.can_view(auth.CUSTOMER, page)
    assert not auth.can_view(None, "summary")
    assert not auth.can_view("other", "summary")


def test_viewer_scoping():
    assert ANA_VIEWER.can_modify(ANA_ID)
    assert not ADMIN_VIEWER.can_modify(ANA_ID)  # administrar cuentas no da acceso a sus compras
    assert ADMIN_VIEWER.manages_users and not ANA_VIEWER.manages_users
    assert ANA_VIEWER.tracks_purchases and not ADMIN_VIEWER.tracks_purchases
    assert ANA_VIEWER.can_delete_own_account and not ADMIN_VIEWER.can_delete_own_account
    assert ADMIN_VIEWER.can_manage_category(None) and not ANA_VIEWER.can_manage_category(None)
    assert ANA_VIEWER.can_manage_category(ANA_ID) and not ANA_VIEWER.can_manage_category(BETO_ID)


def test_viewer_requires_sub_and_role():
    assert auth.viewer_from_claims({"roles": ["customer"]}) is None
    assert auth.viewer_from_claims({"sub": "x", "roles": []}) is None
    viewer = auth.viewer_from_claims({"sub": "x", "roles": ["customer"], "email": "x@billing.example.com"})
    assert viewer == auth.Viewer(user_id="x", role=auth.CUSTOMER, name="x@billing.example.com")


def test_classify_rejects_unknown_formats():
    assert classify("recibo.JPG", None) == (KIND_IMAGE, "image/jpeg")
    assert classify("x.pdf", "application/octet-stream") == (KIND_PDF, "application/pdf")
    with pytest.raises(UnsupportedFile):
        classify("hoja.xlsx", None)


def test_months():
    assert last_months(3, today=date(2026, 2, 10)) == ["2025-12", "2026-01", "2026-02"]
    assert month_bounds("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))


def test_bank_notification_to_invoice():
    n = BankNotification(
        is_transaction=True,
        bank="Bancolombia",
        transaction_type=PURCHASE,
        amount=45900,
        currency="cop",
        merchant="EXITO",
        occurred_on="2026-10-05",
        card_type="credit",
        card_last4="4321",
    )
    assert n.is_expense
    invoice = n.to_invoice()
    assert (invoice.vendor, invoice.total, invoice.currency) == ("EXITO", 45900, "COP")
    assert invoice.payment_method == "Tarjeta de crédito"
    assert n.summary() == "Bancolombia · compra · *4321"
    assert BankNotification(is_transaction=True, transaction_type=TRANSFER).to_invoice().payment_method == (
        "Transferencia"
    )
    assert BankNotification(is_transaction=True, transaction_type=WITHDRAWAL).to_invoice().payment_method == "Efectivo"
    assert not BankNotification(is_transaction=True, transaction_type="other").is_expense
    assert transaction_label(None) == "movimiento"


def test_consistency_warnings():
    today = date(2026, 10, 24)
    ok = InvoiceData(subtotal=100, tax=12, total=112, purchase_date="2026-10-05", currency="USD")
    assert consistency_warnings(ok, today) == []
    bad = InvoiceData(subtotal=100, tax=12, total=150, purchase_date="2027-01-01", currency="US$")
    assert len(consistency_warnings(bad, today)) == 3
