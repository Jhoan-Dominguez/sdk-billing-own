"""Entorno de Alembic. La metadata es el esquema de tables.py.

database.migrate() pasa su propia conexión; desde la CLI (`alembic upgrade head`)
se conecta con COMPRAS_DATABASE_URL / POSTGRES_* (billing.settings).
"""

from alembic import context

from billing import settings
from billing.infrastructure.persistence.sqlalchemy.database import make_engine
from billing.infrastructure.persistence.sqlalchemy.tables import index_applies, metadata


def run(connection) -> None:
    dialect = connection.dialect.name

    def include_object(obj, name, type_, reflected, compare_to) -> bool:
        return type_ != "index" or index_applies(name, dialect)

    context.configure(connection=connection, target_metadata=metadata, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


if (connection := context.config.attributes.get("connection")) is not None:
    run(connection)
else:
    with make_engine(settings.DATABASE_URL).connect() as connection:
        run(connection)
