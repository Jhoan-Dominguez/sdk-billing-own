"""Engine, fábrica de sesiones y migraciones (Alembic)."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from billing.infrastructure.persistence.sqlalchemy.orm import start_mappers

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def make_engine(url: str) -> Engine:
    """Engine para cualquier URL que soporte SQLAlchemy (postgresql+psycopg, sqlite, mysql+pymysql...)."""
    # pre_ping descarta conexiones cortadas (p. ej. tras reiniciar el contenedor de Postgres).
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        # SQLite no aplica las claves foráneas (ni sus ON DELETE CASCADE) si no se pide.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    start_mappers()
    # expire_on_commit=False: los objetos siguen legibles tras confirmar (p. ej. para mostrarlos).
    return sessionmaker(bind=engine, expire_on_commit=False)


def migrate(engine: Engine) -> None:
    """Aplica las migraciones pendientes."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        tables = inspect(connection)
        if tables.has_table("purchases") and not tables.has_table("alembic_version"):
            # Base creada con create_all antes de usar migraciones: equivale a 0001.
            command.stamp(alembic_cfg, "0001")
        command.upgrade(alembic_cfg, "head")
