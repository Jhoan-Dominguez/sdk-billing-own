"""Esquema de la base de datos. Cambiarlo exige una migración (migrations/versions)."""

from sqlalchemy import (
    JSON,
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
    Column("uploaded_at", DateTime, nullable=False, server_default=func.now()),
)

categories = Table(
    "categories",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(50), nullable=False),
    Column("owner_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

# Un nombre por ámbito sin distinguir mayúsculas; NULLS NOT DISTINCT hace que las
# generales (owner_id NULL) también sean únicas entre sí.
Index(
    "uq_categories_owner_name",
    categories.c.owner_id,
    func.lower(categories.c.name),
    unique=True,
    postgresql_nulls_not_distinct=True,
)
