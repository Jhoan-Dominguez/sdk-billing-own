"""Configuración de agentes LLM y metadatos de extracción de los adjuntos.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_settings",
        sa.Column("agent", sa.String(50), primary_key=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(100)),
        sa.Column("updated_by", sa.String(64), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    # batch_alter_table: en SQLite recrea la tabla; en PostgreSQL es un ALTER normal.
    with op.batch_alter_table("attachments") as batch:
        batch.add_column(sa.Column("extraction_meta", sa.JSON()))


def downgrade() -> None:
    with op.batch_alter_table("attachments") as batch:
        batch.drop_column("extraction_meta")
    op.drop_table("agent_settings")
