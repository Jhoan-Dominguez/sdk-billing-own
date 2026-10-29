from billing.domain.schema import SchemaInfo
from billing.infrastructure.persistence.sqlalchemy import schema
from billing.infrastructure.persistence.sqlalchemy.database import make_engine, make_session_factory, migrate
from billing.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyUnitOfWork


class SqlAlchemyBackend:
    """PersistenceBackend para cualquier motor de SQLAlchemy (la URL elige el motor:
    PostgreSQL hoy; SQLite o MySQL cambiando solo BILLING_DATABASE_URL)."""

    name = "sql"

    def __init__(self, url: str) -> None:
        self.engine = make_engine(url)
        self._session_factory = make_session_factory(self.engine)

    def unit_of_work(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._session_factory)

    def init_schema(self) -> None:
        migrate(self.engine)

    def describe_schema(self) -> SchemaInfo:
        return schema.describe(self.engine)


def create(settings) -> SqlAlchemyBackend:
    return SqlAlchemyBackend(settings.DATABASE_URL)
