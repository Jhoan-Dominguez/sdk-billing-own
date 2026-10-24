"""Valores guardados en inglés: rol, origen y tipo de archivo, y metadatos de extracción.

Las etiquetas en español se resuelven al mostrarlas (domain/catalog.py, domain/bank.py).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (tabla, columna, {español: inglés})
COLUMNS = (
    ("users", "role", {"cliente": "customer"}),
    ("purchases", "source", {"banco": "bank", "imagen": "image"}),
    ("attachments", "kind", {"imagen": "image"}),
)
DOCUMENT_TYPES = {"factura": "invoice", "notificacion_bancaria": "bank_notification"}
METHODS = {"reglas": "rules"}
TRANSACTION_TYPES = {
    "compra": "purchase",
    "retiro": "withdrawal",
    "transferencia": "transfer",
    "pago": "payment",
    "otro": "other",
}
CARD_TYPES = {"credito": "credit", "debito": "debit"}


def _invert(mapping: dict[str, str]) -> dict[str, str]:
    return {v: k for k, v in mapping.items()}


def _translate_columns(reverse: bool) -> None:
    for table, column, mapping in COLUMNS:
        for old, new in (_invert(mapping) if reverse else mapping).items():
            op.execute(
                sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old").bindparams(new=new, old=old)
            )


def _translate_meta(meta: dict, reverse: bool) -> dict:
    def tr(mapping: dict[str, str], value):
        return (_invert(mapping) if reverse else mapping).get(value, value)

    meta = dict(meta)
    if "document_type" in meta:
        meta["document_type"] = tr(DOCUMENT_TYPES, meta["document_type"])
    if "method" in meta:
        meta["method"] = tr(METHODS, meta["method"])
    if isinstance(meta.get("bank"), dict):
        bank = dict(meta["bank"])
        bank["transaction_type"] = tr(TRANSACTION_TYPES, bank.get("transaction_type"))
        bank["card_type"] = tr(CARD_TYPES, bank.get("card_type"))
        meta["bank"] = bank
    return meta


def _translate_attachments(reverse: bool) -> None:
    # JSON portable (PostgreSQL y SQLite): se reescribe fila a fila desde Python.
    attachments = sa.table("attachments", sa.column("id", sa.Integer), sa.column("extraction_meta", sa.JSON))
    conn = op.get_bind()
    rows = conn.execute(sa.select(attachments.c.id, attachments.c.extraction_meta)).all()
    for row_id, meta in rows:
        if not isinstance(meta, dict):
            continue
        new_meta = _translate_meta(meta, reverse)
        if new_meta != meta:
            conn.execute(attachments.update().where(attachments.c.id == row_id).values(extraction_meta=new_meta))


def upgrade() -> None:
    _translate_columns(reverse=False)
    _translate_attachments(reverse=False)


def downgrade() -> None:
    _translate_columns(reverse=True)
    _translate_attachments(reverse=True)
