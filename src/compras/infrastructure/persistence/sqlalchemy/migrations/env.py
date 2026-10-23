"""Entorno de Alembic. La metadata es el esquema de tables.py.

database.migrate() pasa su propia conexión; desde la CLI (`alembic upgrade head`)
se conecta con COMPRAS_DATABASE_URL / POSTGRES_* (compras.settings).
"""

from alembic import context

from compras import settings
from compras.infrastructure.persistence.sqlalchemy.database import make_engine
from compras.infrastructure.persistence.sqlalchemy.tables import metadata


def run(connection) -> None:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


if (connection := context.config.attributes.get("connection")) is not None:
    run(connection)
else:
    with make_engine(settings.DATABASE_URL).connect() as connection:
        run(connection)
