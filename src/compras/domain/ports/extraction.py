from typing import Protocol

from compras.domain.invoice import ExtractionResult


class InvoiceExtractor(Protocol):
    """Convierte un archivo (imagen, PDF o email) en datos de factura.

    Nunca debe lanzar por un fallo de extracción: lo indica en `ExtractionResult.error`
    para que la subida no se pierda. `categories` son las que puede usar el dueño.
    """

    def extract(self, raw: bytes, kind: str, content_type: str, *, categories: list[str]) -> ExtractionResult: ...


class BankNotificationParser(Protocol):
    """Lee un correo (.eml) de un banco.

    Devuelve un ExtractionResult con `meta["document_type"] = "notificacion_bancaria"`
    y `meta["bank"]` (BankNotification) si el correo es una notificación de un
    movimiento, o None si no lo es. Como InvoiceExtractor, no lanza por fallos.
    """

    def parse(self, raw_email: bytes) -> ExtractionResult | None: ...
