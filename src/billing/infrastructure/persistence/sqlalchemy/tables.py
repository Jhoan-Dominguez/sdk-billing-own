"""Esquema de la base de datos. Cambiarlo exige una migración (migrations/versions)."""

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    func,
)

metadata = MetaData()
money = Numeric(12, 2)

users = Table(
    "users",
    metadata,
    Column("id", String(64), primary_key=True),  # claim `sub` del proveedor de identidad
    Column("username", String(150), nullable=False),
    Column("name", String(200)),
    Column("email", String(254)),
    Column("role", String(20), nullable=False, index=True),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("last_login_at", DateTime, nullable=False, server_default=func.now()),
    Column("avatar_name", String(64)),
    Column("preferred_currency", String(3)),
    Column("default_payment_method", String(50)),
    Column("default_category", String(50)),
)

purchases = Table(
    "purchases",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("owner_id", String(64), ForeignKey("users.id"), nullable=False, index=True),
    Column("purchase_date", Date, nullable=False, index=True),
    Column("vendor", String(200), nullable=False),
    Column("vendor_tax_id", String(50)),
    Column("invoice_number", String(100)),
    Column("category", String(50), nullable=False, index=True),
    Column("payment_method", String(50)),
    Column("currency", String(3), nullable=False),
    Column("subtotal", money),
    Column("tax", money),
    Column("total", money, nullable=False),
    Column("notes", Text),
    Column("source", String(20), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

purchase_items = Table(
    "purchase_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("purchase_id", Integer, ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False),
    Column("description", String(300), nullable=False),
    Column("quantity", Numeric(12, 3), nullable=False),
    Column("unit_price", money),
    Column("line_total", money),
)

attachments = Table(
    "attachments",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("owner_id", String(64), ForeignKey("users.id"), nullable=False, index=True),
    Column("purchase_id", Integer, ForeignKey("purchases.id", ondelete="CASCADE"), index=True),
    Column("original_name", String(255), nullable=False),
    Column("stored_name", String(255), nullable=False, unique=True),
    Column("content_type", String(100), nullable=False),
    Column("kind", String(20), nullable=False),
    Column("size", Integer, nullable=False),
    Column("sha256", String(64), nullable=False, index=True),
    Column("extracted_text", Text),
    Column("extracted", JSON),
    Column("extraction_error", Text),
    Column("extraction_meta", JSON),
    Column("message_id", String(255)),
    Column("mailbox_id", Integer, ForeignKey("mailbox_connections.id", ondelete="SET NULL")),
    Column("uploaded_at", DateTime, nullable=False, server_default=func.now()),
)
# Un correo (Message-ID) se importa una sola vez por usuario. Los NULL (archivos
# subidos a mano) no chocan entre sí en ningún motor.
Index("uq_attachments_owner_message", attachments.c.owner_id, attachments.c.message_id, unique=True)

categories = Table(
    "categories",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(50), nullable=False),
    Column("owner_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

# Un nombre por ámbito sin distinguir mayúsculas. Las generales tienen owner_id NULL y
# en SQL los NULL no chocan en un índice único: PostgreSQL 15+ lo resuelve con
# NULLS NOT DISTINCT; en el resto de motores se indexa coalesce(owner_id, '').
Index(
    "uq_categories_owner_name",
    categories.c.owner_id,
    func.lower(categories.c.name),
    unique=True,
    postgresql_nulls_not_distinct=True,
).ddl_if(dialect="postgresql")
Index(
    "uq_categories_owner_name_portable",
    func.coalesce(categories.c.owner_id, ""),
    func.lower(categories.c.name),
    unique=True,
).ddl_if(callable_=lambda ddl, target, bind, **kw: bind is not None and bind.dialect.name != "postgresql")

# Índices que solo existen en ciertos motores (para que `alembic check` no los pida
# en los demás): nombre -> "postgresql" (solo ahí) o "!postgresql" (en todos menos ahí).
DIALECT_SPECIFIC_INDEXES = {
    "uq_categories_owner_name": "postgresql",
    "uq_categories_owner_name_portable": "!postgresql",
}


def index_applies(name: str, dialect: str) -> bool:
    rule = DIALECT_SPECIFIC_INDEXES.get(name)
    if rule is None:
        return True
    return dialect != rule[1:] if rule.startswith("!") else dialect == rule


security_confirmations = Table(
    "security_confirmations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("purpose", String(30), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("requires_otp", Boolean, nullable=False),
    Column("expires_at", DateTime, nullable=False),
    Column("email_confirmed_at", DateTime),
    Column("reauth_state_hash", String(64), unique=True),
    Column("otp_verified_at", DateTime),
    Column("started_at", DateTime),
    Column("completed_at", DateTime),
    Column("cancelled_at", DateTime),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

agent_settings = Table(
    "agent_settings",
    metadata,
    Column("agent", String(50), primary_key=True),
    Column("provider", String(30), nullable=False),
    Column("model", String(100)),
    Column("updated_by", String(64), ForeignKey("users.id", ondelete="SET NULL")),
    Column("updated_at", DateTime, nullable=False, server_default=func.now(), onupdate=func.now()),
)

mailbox_connections = Table(
    "mailbox_connections",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("owner_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("host", String(255), nullable=False),
    Column("port", Integer, nullable=False),
    Column("username", String(255), nullable=False),
    Column("password_encrypted", Text, nullable=False),
    Column("use_ssl", Boolean, nullable=False),
    Column("folder", String(255), nullable=False),
    Column("sender_filter", Text, nullable=False),
    Column("enabled", Boolean, nullable=False),
    # UIDVALIDITY y UID de IMAP son enteros de 32 bits sin signo.
    Column("uid_validity", BigInteger),
    Column("last_uid", BigInteger, nullable=False),
    Column("last_sync_at", DateTime),
    Column("last_error", Text),
    Column("imported_count", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)
