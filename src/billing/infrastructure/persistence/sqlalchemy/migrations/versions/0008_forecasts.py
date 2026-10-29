"""Predicciones del gasto (spend_forecasts) y moneda de los modelos por cliente.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

money = sa.Numeric(12, 2)


def upgrade() -> None:
    with op.batch_alter_table("ml_models") as batch:
        batch.add_column(sa.Column("currency", sa.String(3)))

    op.create_table(
        "spend_forecasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("p10", money, nullable=False),
        sa.Column("p50", money, nullable=False),
        sa.Column("p90", money, nullable=False),
        sa.Column("user_weight", sa.Float(), nullable=False),
        sa.Column("global_model_id", sa.Integer(), sa.ForeignKey("ml_models.id", ondelete="SET NULL")),
        sa.Column("user_model_id", sa.Integer(), sa.ForeignKey("ml_models.id", ondelete="SET NULL")),
        sa.Column("actual", money),
        sa.Column("predicted_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_spend_forecasts_owner_currency_period",
        "spend_forecasts",
        ["owner_id", "currency", "period"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("spend_forecasts")
    with op.batch_alter_table("ml_models") as batch:
        batch.drop_column("currency")
