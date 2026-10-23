"""Entidades del dominio.

Son dataclasses sin dependencias de base de datos: el adaptador de persistencia las
mapea a tablas sin modificarlas (infrastructure/persistence/sqlalchemy/orm.py), así
que otro motor de datos puede guardarlas igual.

Los campos `init=False` los rellena el almacenamiento (ids, fechas por defecto) o son
relaciones que no deben fijarse al construir el objeto.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from compras.domain.catalog import FALLBACK_CATEGORY, SOURCE_MANUAL


@dataclass(eq=False, kw_only=True)
class User:
    """Usuario del proveedor de identidad visto por la app (id = claim `sub`)."""

    id: str
    username: str
    role: str
    name: str | None = None
    email: str | None = None
    # Archivo del avatar en el almacenamiento (nombre aleatorio: cambia al reemplazarlo).
    avatar_name: str | None = None
    # Preferencias: valores por defecto del formulario de compras y de los resúmenes.
    preferred_currency: str | None = None
    default_payment_method: str | None = None
    default_category: str | None = None
    created_at: datetime = field(init=False)
    last_login_at: datetime = field(init=False)

    @property
    def display_name(self) -> str:
        return self.name or self.username


@dataclass(eq=False, kw_only=True)
class PurchaseItem:
    """Línea de detalle de una compra."""

    description: str
    quantity: Decimal = Decimal(1)
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    id: int = field(init=False)


@dataclass(eq=False, kw_only=True)
class Attachment:
    """Archivo original (imagen, PDF o email).

    Mientras `purchase_id` es None es un borrador pendiente de revisión: `extracted`
    guarda lo que encontró el extractor para precargar el formulario.
    """

    owner_id: str
    original_name: str
    stored_name: str  # clave en el almacenamiento de archivos
    content_type: str
    kind: str  # imagen | pdf | email
    size: int
    sha256: str
    extracted_text: str | None = None
    extracted: dict | None = None
    extraction_error: str | None = None
    purchase_id: int | None = None
    id: int = field(init=False)
    uploaded_at: datetime = field(init=False)

    @property
    def is_draft(self) -> bool:
        return self.purchase_id is None


@dataclass(eq=False, kw_only=True)
class Purchase:
    """Una compra (factura o recibo) confirmada por el usuario."""

    owner_id: str
    source: str = SOURCE_MANUAL  # manual | imagen | pdf | email
    purchase_date: date | None = None
    vendor: str | None = None
    vendor_tax_id: str | None = None
    invoice_number: str | None = None
    category: str = FALLBACK_CATEGORY
    payment_method: str | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    notes: str | None = None
    items: list[PurchaseItem] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    id: int = field(init=False)
    created_at: datetime = field(init=False)
    owner: User = field(init=False)  # relación de solo lectura (la fija owner_id)


@dataclass(eq=False, kw_only=True)
class Category:
    """Categoría de compras: general (owner_id None, la gestiona un admin) o personal.

    Las compras guardan el nombre (texto), así que renombrar o borrar una categoría
    actualiza las compras afectadas (application/categories.py).
    """

    name: str
    owner_id: str | None = None
    id: int = field(init=False)
    created_at: datetime = field(init=False)

    @property
    def is_global(self) -> bool:
        return self.owner_id is None

    @property
    def is_protected(self) -> bool:
        return self.is_global and self.name == FALLBACK_CATEGORY
