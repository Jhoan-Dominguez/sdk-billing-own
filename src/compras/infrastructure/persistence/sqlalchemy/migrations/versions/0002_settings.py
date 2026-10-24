"""Configuración de usuario: avatar, preferencias y categorías editables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Las categorías que antes eran fijas pasan a ser las generales (copia fija: una migración
# no debe cambiar si luego cambia el código).
DEFAULT_CATEGORIES = [
    "Supermercado",
    "Restaurantes",
    "Servicios",
    "Transporte",
    "Salud",
    "Hogar",
    "Tecnología",
    "Educación",
    "Entretenimiento",
    "Otros",
]


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_name", sa.String(64)))
    op.add_column("users", sa.Column("preferred_currency", sa.String(3)))
    op.add_column("users", sa.Column("default_payment_method", sa.String(50)))
    op.add_column("users", sa.Column("default_category", sa.String(50)))

    categories = op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_categories_owner_id", "categories", ["owner_id"])
    # Ver tables.py: NULLS NOT DISTINCT en PostgreSQL, coalesce(owner_id, '') en otros motores.
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "uq_categories_owner_name",
            "categories",
            ["owner_id", sa.text("lower(name)")],
            unique=True,
            postgresql_nulls_not_distinct=True,
        )
    else:
        op.create_index(
            "uq_categories_owner_name_portable",
            "categories",
            [sa.text("coalesce(owner_id, '')"), sa.text("lower(name)")],
            unique=True,
        )
    op.bulk_insert(categories, [{"name": name} for name in DEFAULT_CATEGORIES])


def downgrade() -> None:
    op.drop_table("categories")
    op.drop_column("users", "default_category")
    op.drop_column("users", "default_payment_method")
    op.drop_column("users", "preferred_currency")
    op.drop_column("users", "avatar_name")
