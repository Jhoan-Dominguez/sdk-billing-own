"""Datos de una factura extraída de un archivo (antes de que el usuario la confirme)."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from pydantic import BaseModel, Field


class ExtractedItem(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None


class InvoiceData(BaseModel):
    """Datos de una factura tal como los devuelve un extractor.

    Todo es opcional: el resultado solo precarga el formulario de revisión y el
    usuario corrige/completa antes de guardar la compra.
    """

    vendor: str | None = Field(None, description="Nombre comercial o razón social del emisor")
    vendor_tax_id: str | None = Field(None, description="RUC/NIT/RFC/CUIT u otro identificador fiscal del emisor")
    invoice_number: str | None = None
    purchase_date: str | None = Field(None, description="Fecha de emisión en formato YYYY-MM-DD")
    currency: str | None = Field(None, description="Código ISO 4217, p. ej. USD, EUR, MXN")
    subtotal: float | None = None
    tax: float | None = Field(None, description="Total de impuestos (IVA, etc.)")
    total: float | None = None
    payment_method: str | None = None
    category: str | None = None
    items: list[ExtractedItem] = []


@dataclass
class ExtractionResult:
    """Lo que devuelve un extractor: texto legible, datos detectados y error (si lo hubo).

    `meta` describe cómo se extrajo (Attachment.extraction_meta): document_type,
    method (llm | reglas), agent, provider, model, duration_ms, tokens, warnings y,
    en notificaciones bancarias, `bank` (BankNotification como dict).
    """

    text: str = ""
    data: InvoiceData = field(default_factory=InvoiceData)
    error: str | None = None
    meta: dict = field(default_factory=dict)


# Diferencia admitida al comparar sumas (redondeos de la factura).
TOLERANCE = 0.05


def consistency_warnings(data: InvoiceData, today: date | None = None) -> list[str]:
    """Incoherencias de una extracción para avisar al usuario antes de guardar.

    No bloquean nada: el usuario revisa y corrige en el formulario.
    """
    warnings = []
    today = today or date.today()
    line_totals = [i.line_total for i in data.items if i.line_total is not None]
    lines = sum(line_totals)
    # Las líneas pueden sumar el subtotal o, si ya incluyen impuestos, el total.
    if (
        line_totals
        and data.subtotal is not None
        and abs(lines - data.subtotal) > TOLERANCE
        and (data.total is None or abs(lines - data.total) > TOLERANCE)
    ):
        warnings.append(f"La suma de las líneas ({lines:,.2f}) no coincide con el subtotal ({data.subtotal:,.2f}).")
    if (
        data.subtotal is not None
        and data.total is not None
        and abs(data.subtotal + (data.tax or 0) - data.total) > TOLERANCE
    ):
        expected = data.subtotal + (data.tax or 0)
        warnings.append(f"Subtotal + impuestos ({expected:,.2f}) no coincide con el total ({data.total:,.2f}).")
    if data.purchase_date:
        try:
            when = date.fromisoformat(data.purchase_date)
        except ValueError:
            warnings.append(f"La fecha detectada ({data.purchase_date}) no es válida.")
        else:
            if when > today + timedelta(days=1):
                warnings.append(f"La fecha detectada ({when:%d/%m/%Y}) es futura.")
            elif when < today - timedelta(days=730):
                warnings.append(f"La fecha detectada ({when:%d/%m/%Y}) tiene más de dos años.")
    if data.currency and (len(data.currency) != 3 or not data.currency.isalpha()):
        warnings.append(f"La moneda detectada ({data.currency}) no es un código ISO de 3 letras.")
    if data.total is not None and data.total < 0:
        warnings.append("El total detectado es negativo.")
    return warnings
