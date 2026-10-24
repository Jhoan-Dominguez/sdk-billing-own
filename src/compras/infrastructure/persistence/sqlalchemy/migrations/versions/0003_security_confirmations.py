"""Confirmaciones de seguridad (correo + 2FA) para acciones sensibles de la cuenta.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_confirmations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("requires_otp", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("email_confirmed_at", sa.DateTime()),
        sa.Column("reauth_state_hash", sa.String(64), unique=True),
        sa.Column("otp_verified_at", sa.DateTime()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("cancelled_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_security_confirmations_user_id", "security_confirmations", ["user_id"])


def downgrade() -> None:
    op.drop_table("security_confirmations")
