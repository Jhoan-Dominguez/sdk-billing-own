from email.message import EmailMessage

import pytest

from billing.application.agents.base import Agent
from billing.application.agents.registry import AGENTS, BANK_NOTIFICATION, INVOICE
from billing.domain.catalog import DOCUMENT_BANK_NOTIFICATION, DOCUMENT_INVOICE
from billing.domain.files import KIND_EMAIL, KIND_IMAGE, KIND_PDF
from billing.domain.ports.llm import LLMError
from billing.infrastructure.extraction import bank_rules
from billing.infrastructure.extraction.bank import LLMBankParser, RuleBankParser
from billing.infrastructure.extraction.extractors import LLMInvoiceExtractor, RegexExtractor
from billing.infrastructure.extraction.regex import invoice_from_text, parse_amount
from billing.infrastructure.llm.fake import FakeLLMClient
from tests.conftest import make_email, make_pdf

CATEGORIES = ["Supermercado", "Otros"]


class FailingLLM(FakeLLMClient):
    def generate(self, **kwargs):
        raise LLMError("sin conexión")


def agent(name: str, llm) -> Agent:
    return Agent(AGENTS[name], llm)


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


def test_invoice_from_text_finds_main_fields():
    text = """Supermercado La Esquina
    Factura N° F001-000123
    Fecha: 05/10/2026
    Subtotal: 100,00
    IVA 12%: 12,00
    TOTAL: USD 112,00"""
    data = invoice_from_text(text)
    assert data.vendor == "Supermercado La Esquina"
    assert data.invoice_number == "F001-000123"
    assert data.purchase_date == "2026-10-05"
    assert (data.subtotal, data.tax, data.total) == (100.0, 12.0, 112.0)
    assert data.currency == "USD"


def test_pdf_text_is_extracted_locally():
    pdf = make_pdf(["Ferreteria Central", "Fecha 2026-09-14", "Total 45.90"])
    result = RegexExtractor().extract(pdf, KIND_PDF, "application/pdf", categories=CATEGORIES)
    assert "Ferreteria Central" in result.text
    assert result.data.total == 45.9
    assert result.data.purchase_date == "2026-09-14"
    assert result.error is None
    assert result.meta["document_type"] == DOCUMENT_INVOICE
    assert result.meta["method"] == "rules"


def test_email_with_pdf_attachment():
    msg = EmailMessage()
    msg["From"] = '"Tienda Online" <ventas@tienda.example>'
    msg["Subject"] = "Tu compra"
    msg.set_content("Gracias por tu compra.")
    msg.add_attachment(make_pdf(["Total 19.99"]), maintype="application", subtype="pdf", filename="factura.pdf")
    result = RegexExtractor().extract(msg.as_bytes(), KIND_EMAIL, "message/rfc822", categories=CATEGORIES)
    assert result.data.vendor == "Tienda Online"
    assert result.data.total == 19.99


def test_regex_extractor_flags_images():
    result = RegexExtractor().extract(b"\x89PNG...", KIND_IMAGE, "image/png", categories=CATEGORIES)
    assert result.error and "imágenes" in result.error


def test_llm_extractor_uses_agent_output():
    llm = FakeLLMClient(responses={"InvoiceData": {"vendor": "Café Central", "total": 8.5, "currency": "EUR"}})
    pdf = make_pdf(["Ticket"])
    result = LLMInvoiceExtractor(lambda: agent(INVOICE, llm)).extract(
        pdf, KIND_PDF, "application/pdf", categories=CATEGORIES
    )
    assert (result.data.vendor, result.data.total, result.data.currency) == ("Café Central", 8.5, "EUR")
    assert result.meta["method"] == "llm" and result.meta["provider"] == "fake"
    assert "Supermercado, Otros" in llm.calls[0]["system"]  # el prompt recibe las categorías


def test_llm_failure_falls_back_to_rules():
    pdf = make_pdf(["Total 45.90"])
    result = LLMInvoiceExtractor(lambda: agent(INVOICE, FailingLLM())).extract(
        pdf, KIND_PDF, "application/pdf", categories=CATEGORIES
    )
    assert result.data.total == 45.9
    assert result.meta["method"] == "rules"
    assert "sin conexión" in result.error


def test_without_agent_uses_rules():
    pdf = make_pdf(["Total 10.00"])
    result = LLMInvoiceExtractor(lambda: None).extract(pdf, KIND_PDF, "application/pdf", categories=CATEGORIES)
    assert result.meta["method"] == "rules" and result.data.total == 10.0


@pytest.mark.parametrize(
    "template, pattern",
    [(t, p) for t in bank_rules.TEMPLATES for p in t.patterns],
    ids=lambda v: getattr(v, "bank", None) or getattr(v, "transaction_type", ""),
)
def test_every_bank_pattern_matches_its_example(template, pattern):
    notification = bank_rules.match(pattern.example, f"alertas@{template.senders[0]}")
    assert notification is not None
    assert notification.bank == template.bank
    assert notification.transaction_type == pattern.transaction_type
    assert notification.transaction_type in bank_rules.BankNotification.model_fields["transaction_type"].description


def test_rule_parser_builds_bank_draft():
    example = bank_rules.TEMPLATES[0].patterns[0].example
    result = RuleBankParser().parse(make_email(example))
    assert result.meta["document_type"] == DOCUMENT_BANK_NOTIFICATION
    assert result.meta["method"] == "rules"
    assert result.meta["bank"]["transaction_type"] == "purchase"
    assert result.meta["bank"]["card_type"] in ("credit", "debit")
    assert result.data.total and result.data.vendor


def test_bank_parser_uses_agent_only_for_bank_senders():
    llm = FakeLLMClient(
        responses={
            "BankNotification": {
                "is_transaction": True,
                "bank": "Nequi",
                "transaction_type": "transfer",
                "amount": 20000,
                "merchant": "Juan",
            }
        }
    )
    parser = LLMBankParser(lambda: agent(BANK_NOTIFICATION, llm), require_bank_sender=True)
    # Correo de una tienda subido a mano: no se gasta una llamada al agente.
    assert parser.parse(make_email("Gracias por tu compra", sender="ventas@tienda.example")) is None
    assert llm.calls == []
    result = parser.parse(make_email("Enviaste $20.000 a Juan", sender="alertas@bancolombia.com.co"))
    assert result.meta["method"] == "llm"
    assert result.meta["bank"]["transaction_type"] == "transfer"
    assert result.data.payment_method == "Transferencia"


def test_bank_parser_ignores_non_transactions():
    parser = LLMBankParser(lambda: agent(BANK_NOTIFICATION, FakeLLMClient()))
    assert parser.parse(make_email("Nuevas promociones para ti")) is None
