"""BankNotificationParser: reglas por banco primero y, si no reconocen el correo, el
agente LLM `bank_notification`."""

from collections.abc import Callable

from billing.application.agents.base import Agent
from billing.domain.bank import BankNotification
from billing.domain.catalog import DOCUMENT_BANK_NOTIFICATION
from billing.domain.files import KIND_EMAIL
from billing.domain.invoice import ExtractionResult, consistency_warnings
from billing.domain.llm import TextBlock
from billing.domain.ports.llm import LLMError
from billing.infrastructure.extraction import bank_rules
from billing.infrastructure.extraction.documents import email_sender, parts_text, to_parts


def _result(text: str, notification: BankNotification, meta: dict) -> ExtractionResult:
    data = notification.to_invoice()
    return ExtractionResult(
        text=text,
        data=data,
        meta={
            "document_type": DOCUMENT_BANK_NOTIFICATION,
            "bank": notification.model_dump(),
            "warnings": consistency_warnings(data),
            **meta,
        },
    )


class RuleBankParser:
    """Solo plantillas de reglas (bank_rules.py): sin red ni coste."""

    def parse(self, raw_email: bytes) -> ExtractionResult | None:
        text = parts_text(to_parts(raw_email, KIND_EMAIL, "message/rfc822"))
        notification = bank_rules.match(text, email_sender(raw_email))
        if notification is None:
            return None
        return _result(text, notification, {"method": "reglas"})


class LLMBankParser:
    """Reglas primero; si no reconocen el correo, el agente `bank_notification`.

    `require_bank_sender`: con True (correos subidos a mano) el agente solo se usa si
    el remitente es un banco conocido o el texto menciona uno, para no gastar una
    llamada en cada factura por correo. Los buzones IMAP ya filtran por remitente.
    """

    def __init__(self, agent: Callable[[], Agent | None], *, require_bank_sender: bool = False) -> None:
        self._agent = agent
        self._rules = RuleBankParser()
        self.require_bank_sender = require_bank_sender

    def parse(self, raw_email: bytes) -> ExtractionResult | None:
        if result := self._rules.parse(raw_email):
            return result
        text = parts_text(to_parts(raw_email, KIND_EMAIL, "message/rfc822"))
        sender = email_sender(raw_email)
        if self.require_bank_sender and not (
            bank_rules.is_bank_sender(sender) or bank_rules.templates_for(sender, text)
        ):
            return None
        agent = self._agent()
        if agent is None or not text:
            return None
        try:
            llm_result = agent.run([TextBlock(text)])
        except LLMError as exc:
            # Remitente de banco pero ilegible: queda como borrador para completarlo a mano.
            result = ExtractionResult(text=text, error=f"No se pudo leer la notificación: {exc}")
            result.meta = {"document_type": DOCUMENT_BANK_NOTIFICATION, "method": "reglas", "warnings": []}
            return result
        notification = llm_result.output
        if not notification.is_transaction:
            return None
        meta = {"method": "llm", "agent": agent.name, **llm_result.meta()}
        return _result(text, notification, meta)
