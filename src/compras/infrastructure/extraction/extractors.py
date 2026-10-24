"""Adaptadores InvoiceExtractor que usa la app (compras/bootstrap.py elige uno)."""

from collections.abc import Callable

from compras.application.agents.base import Agent
from compras.domain.catalog import DOCUMENT_INVOICE, PAYMENT_METHODS
from compras.domain.invoice import ExtractionResult, consistency_warnings
from compras.domain.ports.llm import LLMError
from compras.infrastructure.extraction.documents import parts_text, to_blocks, to_parts
from compras.infrastructure.extraction.regex import invoice_from_text

NO_TEXT_ERROR = (
    "El extractor local no puede leer imágenes ni PDFs escaneados. "
    "Completa los datos a mano o configura un agente LLM (Configuración → Agentes IA)."
)


class RegexExtractor:
    """Sin red: texto de PDFs digitales y emails + expresiones regulares."""

    def extract(self, raw: bytes, kind: str, content_type: str, *, categories: list[str]) -> ExtractionResult:
        text = parts_text(to_parts(raw, kind, content_type))
        result = ExtractionResult(text=text, data=invoice_from_text(text))
        result.meta = {"document_type": DOCUMENT_INVOICE, "method": "reglas"}
        if not text:
            result.error = NO_TEXT_ERROR
        result.meta["warnings"] = consistency_warnings(result.data)
        return result


class LLMInvoiceExtractor:
    """Lee imágenes, PDFs (incluidos escaneados) y correos con el agente `invoice`.

    `agent` se pide en cada extracción para respetar el proveedor/modelo que haya
    elegido el administrador en ese momento; si devuelve None se usan las regex.
    Si el LLM falla, el borrador no se pierde: se usan las regex y se deja el error.
    """

    def __init__(self, agent: Callable[[], Agent | None]) -> None:
        self._agent = agent
        self._fallback = RegexExtractor()

    def extract(self, raw: bytes, kind: str, content_type: str, *, categories: list[str]) -> ExtractionResult:
        agent = self._agent()
        if agent is None:
            return self._fallback.extract(raw, kind, content_type, categories=categories)
        parts = to_parts(raw, kind, content_type)
        result = ExtractionResult(text=parts_text(parts))
        blocks, notes = to_blocks(parts, agent.llm.capabilities)
        meta = {
            "document_type": DOCUMENT_INVOICE,
            "method": "llm",
            "agent": agent.name,
            "provider": agent.llm.provider,
            "model": agent.llm.model,
        }
        try:
            if not blocks:
                raise LLMError(" ".join(notes) or "el archivo no tiene contenido legible")
            llm_result = agent.run(blocks, categories=", ".join(categories), payment_methods=", ".join(PAYMENT_METHODS))
        except LLMError as exc:
            result.error = f"No se pudo extraer automáticamente: {exc}"
            result.data = invoice_from_text(result.text)
            meta["method"] = "reglas"
        else:
            result.data = llm_result.output
            meta.update(llm_result.meta())
            if errors := llm_result.extra.get("fallback_errors"):
                meta["fallback_errors"] = errors
        meta["warnings"] = [*notes, *consistency_warnings(result.data)]
        result.meta = meta
        return result
