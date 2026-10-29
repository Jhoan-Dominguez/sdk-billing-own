"""Administración: cuentas bloqueadas, auditoría y modelos de predicción del gasto.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("disabled_at", sa.DateTime()))

    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.String(64)),
        sa.Column("actor_label", sa.String(254), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("target_user_id", sa.String(64)),
        sa.Column("target_label", sa.String(254)),
        sa.Column("details", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_admin_audit_log_action", "admin_audit_log", ["action"])
    op.create_index("ix_admin_audit_log_target_user_id", "admin_audit_log", ["target_user_id"])
    op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])

    op.create_table(
        "ml_training_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("algorithm", sa.String(50), nullable=False),
        sa.Column("params", sa.JSON()),
        sa.Column("data_fingerprint", sa.String(64)),
        sa.Column("n_samples", sa.Integer()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ml_training_runs_owner_id", "ml_training_runs", ["owner_id"])

    op.create_table(
        "ml_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("algorithm", sa.String(50), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("ml_training_runs.id", ondelete="SET NULL")),
        sa.Column("artifact_key", sa.String(255)),
        sa.Column("params", sa.JSON()),
        sa.Column("features", sa.JSON()),
        sa.Column("metrics", sa.JSON()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("train_from", sa.Date()),
        sa.Column("train_to", sa.Date()),
        sa.Column("n_samples", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ml_models_scope", "ml_models", ["scope"])
    op.create_index("ix_ml_models_owner_id", "ml_models", ["owner_id"])


def downgrade() -> None:
    op.drop_table("ml_models")
    op.drop_table("ml_training_runs")
    op.drop_table("admin_audit_log")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("disabled_at")
