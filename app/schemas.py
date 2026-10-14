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
