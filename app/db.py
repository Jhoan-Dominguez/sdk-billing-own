from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):
        # SQLite no aplica claves foráneas (ni ON DELETE CASCADE) si no se activa por conexión.
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


engine = make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(bind=None) -> None:
    from app import models  # noqa: F401  (registra las tablas en Base.metadata)

    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind or engine)


def get_session():
    with SessionLocal() as session:
        yield session
