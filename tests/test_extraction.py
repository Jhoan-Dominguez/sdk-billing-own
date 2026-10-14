from email.message import EmailMessage
from types import SimpleNamespace

import pytest

from app import extraction
from app.extraction import classify, extract, extract_from_text, parse_amount
from app.schemas import InvoiceData
from tests.conftest import make_pdf


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.234,56", 1234.56),
        ("1,234.56", 1234.56),
        ("1234.5", 1234.5),
        ("1 234,56", 1234.56),
        ("1.234", 1234.0),
        ("12,50", 12.5),
        ("", None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_extract_from_text_finds_main_fields():
    text = """Supermercado La Esquina
    Factura N° F001-000123
    Fecha: 05/10/2026
    Subtotal: 100,00
    IVA 12%: 12,00
    TOTAL: USD 112,00"""
    data = extract_from_text(text)
    assert data.vendor == "Supermercado La Esquina"
    assert data.invoice_number == "F001-000123"
    assert data.purchase_date == "2026-10-05"
    assert data.subtotal == 100.0
    assert data.tax == 12.0
    assert data.total == 112.0
    assert data.currency == "USD"


def test_classify_rejects_unknown_formats():
    assert classify("recibo.JPG", None) == ("imagen", "image/jpeg")
    assert classify("x.pdf", "application/octet-stream") == ("pdf", "application/pdf")
    with pytest.raises(extraction.UnsupportedFile):
        classify("hoja.xlsx", None)


def test_pdf_text_is_extracted_locally():
    pdf = make_pdf(["Ferreteria Central", "Fecha 2026-09-14", "Total 45.90"])
    result = extract(pdf, "pdf", "application/pdf", extractor="local")
    assert "Ferreteria Central" in result.text
    assert result.data.total == 45.9
    assert result.data.purchase_date == "2026-09-14"
    assert result.error is None


def test_email_with_pdf_attachment():
    msg = EmailMessage()
    msg["From"] = '"Tienda Online" <ventas@tienda.example>'
    msg["Subject"] = "Tu compra"
    msg.set_content("Gracias por tu compra.")
    msg.add_attachment(
        make_pdf(["Total 19.99"]), maintype="application", subtype="pdf", filename="factura.pdf"
    )
    result = extract(msg.as_bytes(), "email", "message/rfc822", extractor="local")
    assert result.data.vendor == "Tienda Online"
    assert result.data.total == 19.99


def test_local_extractor_flags_images():
    result = extract(b"\x89PNG...", "imagen", "image/png", extractor="local")
    assert result.error and "imágenes" in result.error


def test_claude_extractor_sends_image_and_uses_parsed_output(monkeypatch):
    calls = {}

    class FakeMessages:
        def parse(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                stop_reason="end_turn",
                parsed_output=InvoiceData(vendor="Café Sol", total=8.5, currency="EUR"),
            )

    class FakeClient:
        beta = SimpleNamespace(messages=FakeMessages())

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    result = extract(b"jpegbytes", "imagen", "image/jpeg", extractor="claude")

    assert result.data.vendor == "Café Sol"
    assert result.error is None
    content = calls["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert calls["output_format"] is InvoiceData


def test_claude_failure_falls_back_to_local(monkeypatch):
    class Boom:
        def __init__(self):
            raise RuntimeError("sin credenciales")

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", Boom)
    pdf = make_pdf(["Total 10.00"])
    result = extract(pdf, "pdf", "application/pdf", extractor="claude")
    assert "sin credenciales" in result.error
    assert result.data.total == 10.0
