from typing import Protocol

from compras.domain.invoice import ExtractionResult


class InvoiceExtractor(Protocol):
    """Convierte un archivo (imagen, PDF o email) en datos de factura.

    Nunca debe lanzar por un fallo de extracción: lo indica en `ExtractionResult.error`
    para que la subida no se pierda.
    """

    def extract(self, raw: bytes, kind: str, content_type: str) -> ExtractionResult: ...
