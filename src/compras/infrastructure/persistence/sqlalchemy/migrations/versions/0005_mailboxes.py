"""Buzones IMAP de notificaciones bancarias y origen de los adjuntos importados.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mailbox_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("use_ssl", sa.Boolean(), nullable=False),
        sa.Column("folder", sa.String(255), nullable=False),
        sa.Column("sender_filter", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("uid_validity", sa.BigInteger()),
        sa.Column("last_uid", sa.BigInteger(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime()),
        sa.Column("last_error", sa.Text()),
        sa.Column("imported_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mailbox_connections_owner_id", "mailbox_connections", ["owner_id"])
    with op.batch_alter_table("attachments") as batch:
        batch.add_column(sa.Column("message_id", sa.String(255)))
        batch.add_column(sa.Column("mailbox_id", sa.Integer()))
        batch.create_foreign_key(
            "attachments_mailbox_id_fkey", "mailbox_connections", ["mailbox_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("uq_attachments_owner_message", ["owner_id", "message_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("attachments") as batch:
        batch.drop_index("uq_attachments_owner_message")
        batch.drop_constraint("attachments_mailbox_id_fkey", type_="foreignkey")
        batch.drop_column("mailbox_id")
        batch.drop_column("message_id")
    op.drop_table("mailbox_connections")
