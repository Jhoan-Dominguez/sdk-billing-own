"""Adaptadores InvoiceExtractor que usa la app (compras/bootstrap.py elige uno)."""

from compras.domain.invoice import ExtractionResult
from compras.infrastructure.extraction.claude import read_with_claude
from compras.infrastructure.extraction.documents import parts_text, to_parts
from compras.infrastructure.extraction.regex import invoice_from_text

NO_TEXT_ERROR = (
    "El extractor local no puede leer imágenes ni PDFs escaneados. "
    "Completa los datos a mano o configura ANTHROPIC_API_KEY."
)


class RegexExtractor:
    """Sin red: texto de PDFs digitales y emails + expresiones regulares."""

    def extract(self, raw: bytes, kind: str, content_type: str) -> ExtractionResult:
        text = parts_text(to_parts(raw, kind, content_type))
        result = ExtractionResult(text=text, data=invoice_from_text(text))
        if not text:
            result.error = NO_TEXT_ERROR
        return result


class ClaudeExtractor:
    """Lee imágenes y PDFs (incluidos escaneados) con Claude.

    Si la llamada falla, el borrador no se pierde: usa las regex y deja el error.
    """

    def __init__(self, model: str, categories: list[str]) -> None:
        self.model = model
        self.categories = categories

    def extract(self, raw: bytes, kind: str, content_type: str) -> ExtractionResult:
        parts = to_parts(raw, kind, content_type)
        result = ExtractionResult(text=parts_text(parts))
        try:
            result.data = read_with_claude(parts, model=self.model, categories=self.categories)
        except Exception as exc:  # el borrador sigue siendo útil aunque falle la extracción
            result.error = f"No se pudo extraer automáticamente: {exc}"
            result.data = invoice_from_text(result.text)
        return result
