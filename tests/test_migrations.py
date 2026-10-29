import json

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from billing.infrastructure.persistence.sqlalchemy.database import MIGRATIONS_DIR


def migrate(engine: sa.Engine, revision: str, *, down: bool = False) -> None:
    # Igual que database.migrate(): env.py usa la conexión que se le pasa.
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        (command.downgrade if down else command.upgrade)(cfg, revision)


def test_0006_translates_stored_values(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    migrate(engine, "0005")
    meta = {
        "document_type": "notificacion_bancaria",
        "method": "reglas",
        "bank": {"transaction_type": "retiro", "card_type": "debito"},
    }
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO users (id, username, name, role, created_at, last_login_at) "
                "VALUES ('u', 'u', 'U', 'cliente', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO purchases (owner_id, purchase_date, vendor, category, currency, total, source, "
                "created_at) "
                "VALUES ('u', '2026-01-01', 'v', 'Otros', 'COP', 1, 'banco', CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO attachments (owner_id, original_name, stored_name, content_type, kind, size, sha256, "
                "uploaded_at, extraction_meta) VALUES ('u', 'a', 'a', 'x', 'imagen', 1, 's', CURRENT_TIMESTAMP, :m)"
            ),
            {"m": json.dumps(meta)},
        )

    def stored():
        with engine.connect() as conn:
            return (
                conn.scalar(sa.text("SELECT role FROM users")),
                conn.scalar(sa.text("SELECT source FROM purchases")),
                conn.execute(sa.text("SELECT kind, extraction_meta FROM attachments")).one(),
            )

    migrate(engine, "0006")
    role, source, (kind, raw_meta) = stored()
    assert (role, source, kind) == ("customer", "bank", "image")
    assert json.loads(raw_meta) == {
        "document_type": "bank_notification",
        "method": "rules",
        "bank": {"transaction_type": "withdrawal", "card_type": "debit"},
    }

    migrate(engine, "0005", down=True)
    role, source, (kind, raw_meta) = stored()
    assert (role, source, kind) == ("cliente", "banco", "imagen")
    assert json.loads(raw_meta) == meta
    engine.dispose()


# El id "[sqlite]" la manda al final (conftest): el mapeo de SQLAlchemy rompe el adaptador en memoria.
@pytest.mark.parametrize("engine", ["sqlite"])
def test_describe_schema_reflects_database_and_migrations(tmp_path, engine):
    from billing.infrastructure.persistence.sqlalchemy.backend import SqlAlchemyBackend

    backend = SqlAlchemyBackend(f"sqlite:///{tmp_path / 'd.db'}")
    backend.init_schema()
    schema = backend.describe_schema()
    tables = {t.name: t for t in schema.tables}
    assert {"users", "purchases", "admin_audit_log", "ml_models", "ml_training_runs"} <= set(tables)
    assert "alembic_version" not in tables
    assert schema.current_revision == schema.head_revision and not schema.pending_migrations
    fk = next(fk for fk in tables["ml_models"].foreign_keys if fk.ref_table == "ml_training_runs")
    assert fk.columns == ("run_id",) and fk.on_delete == "SET NULL"
    assert next(c for c in tables["users"].columns if c.name == "id").primary_key
    backend.engine.dispose()
