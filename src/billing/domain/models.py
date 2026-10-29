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

from billing.domain.catalog import DOCUMENT_INVOICE, FALLBACK_CATEGORY, SOURCE_MANUAL
from billing.domain.forecasting import MODEL_ACTIVE, RUN_RUNNING


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
    # Bloqueada por un administrador (además de deshabilitada en el proveedor de identidad):
    # la app expulsa en la siguiente interacción a quien tenga una sesión abierta.
    disabled_at: datetime | None = None
    created_at: datetime = field(init=False)
    last_login_at: datetime = field(init=False)

    @property
    def display_name(self) -> str:
        return self.name or self.username

    @property
    def is_disabled(self) -> bool:
        return self.disabled_at is not None


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
    kind: str  # image | pdf | email
    size: int
    sha256: str
    extracted_text: str | None = None
    extracted: dict | None = None
    extraction_error: str | None = None
    # Cómo se extrajo: tipo de documento, agente, proveedor y modelo, duración, avisos.
    extraction_meta: dict | None = None
    # Message-ID del correo si llegó por un buzón IMAP (evita importarlo dos veces).
    message_id: str | None = None
    mailbox_id: int | None = None
    purchase_id: int | None = None
    id: int = field(init=False)
    uploaded_at: datetime = field(init=False)

    @property
    def is_draft(self) -> bool:
        return self.purchase_id is None

    @property
    def document_type(self) -> str:
        """`invoice` o `bank_notification` (ver domain/catalog.py)."""
        return (self.extraction_meta or {}).get("document_type") or DOCUMENT_INVOICE


@dataclass(eq=False, kw_only=True)
class Purchase:
    """Una compra (factura o recibo) confirmada por el usuario."""

    owner_id: str
    source: str = SOURCE_MANUAL  # manual | image | pdf | email | bank
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


@dataclass(eq=False, kw_only=True)
class SecurityConfirmation:
    """Solicitud de una acción sensible pendiente de confirmar (domain/security.py).

    El token del enlace enviado por correo y el `state` de la reautenticación solo se
    guardan como hash SHA-256: quien lea la base no puede usarlos.
    """

    user_id: str
    purpose: str
    token_hash: str
    requires_otp: bool
    expires_at: datetime
    email_confirmed_at: datetime | None = None
    reauth_state_hash: str | None = None
    otp_verified_at: datetime | None = None
    # La acción ya se ejecutó (o se inició en el proveedor de identidad).
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    id: int = field(init=False)
    created_at: datetime = field(init=False)

    def is_active(self, now: datetime) -> bool:
        return self.completed_at is None and self.cancelled_at is None and now < self.expires_at

    @property
    def email_confirmed(self) -> bool:
        return self.email_confirmed_at is not None

    @property
    def otp_verified(self) -> bool:
        return not self.requires_otp or self.otp_verified_at is not None

    @property
    def is_ready(self) -> bool:
        """Todos los pasos exigidos están hechos: se puede ejecutar la acción."""
        return self.email_confirmed and self.otp_verified


@dataclass(eq=False, kw_only=True)
class AgentSetting:
    """Proveedor y modelo LLM elegidos por un administrador para un agente."""

    agent: str
    provider: str
    model: str | None = None
    updated_by: str | None = None
    updated_at: datetime = field(init=False)


@dataclass(eq=False, kw_only=True)
class MailboxConnection:
    """Buzón IMAP de un usuario del que se leen sus notificaciones bancarias.

    La contraseña (de aplicación) se guarda cifrada (`password_encrypted`, ver
    domain/ports/crypto.py). `last_uid` + `uid_validity` marcan hasta dónde se leyó.
    """

    owner_id: str
    host: str
    port: int
    username: str
    password_encrypted: str
    use_ssl: bool = True
    folder: str = "INBOX"
    # Remitentes aceptados, separados por coma: direcciones o dominios (@bancolombia.com.co).
    sender_filter: str = ""
    enabled: bool = True
    uid_validity: int | None = None
    last_uid: int = 0
    last_sync_at: datetime | None = None
    last_error: str | None = None
    imported_count: int = 0
    id: int = field(init=False)
    created_at: datetime = field(init=False)

    @property
    def senders(self) -> list[str]:
        return [s.strip().lower() for s in self.sender_filter.split(",") if s.strip()]


@dataclass(eq=False, kw_only=True)
class AuditEntry:
    """Acción de un administrador (domain/admin.py).

    Sin claves foráneas: la entrada debe sobrevivir al borrado de quien actuó y del
    usuario afectado, por eso guarda también sus etiquetas (nombre o correo) de ese momento.
    """

    actor_id: str | None
    actor_label: str
    action: str
    target_user_id: str | None = None
    target_label: str | None = None
    details: dict | None = None
    id: int = field(init=False)
    created_at: datetime = field(init=False)


@dataclass(eq=False, kw_only=True)
class ForecastTrainingRun:
    """Un entrenamiento de un modelo de predicción (domain/forecasting.py).

    No guarda los datos de entrenamiento (se derivan de las compras), sino su huella para
    poder reproducirlo: rango, número de muestras y hash de los datos.
    """

    scope: str  # global | user
    algorithm: str
    owner_id: str | None = None  # el cliente si scope = user
    params: dict | None = None
    data_fingerprint: str | None = None
    n_samples: int | None = None
    status: str = RUN_RUNNING
    error: str | None = None
    finished_at: datetime | None = None
    id: int = field(init=False)
    created_at: datetime = field(init=False)  # inicio


@dataclass(eq=False, kw_only=True)
class ForecastModel:
    """Un modelo de predicción entrenado y sus métricas.

    El general se guarda como archivo en el FileStorage (`artifact_key`); el de cada
    cliente son unos pocos parámetros (`params`) en la base.
    """

    scope: str
    algorithm: str
    version: str
    owner_id: str | None = None
    run_id: int | None = None
    artifact_key: str | None = None
    params: dict | None = None
    features: list | None = None  # nombres de las variables de entrada
    metrics: dict | None = None  # ver forecasting.METRIC_*
    status: str = MODEL_ACTIVE
    train_from: date | None = None
    train_to: date | None = None
    n_samples: int | None = None
    id: int = field(init=False)
    created_at: datetime = field(init=False)  # fecha de entrenamiento
