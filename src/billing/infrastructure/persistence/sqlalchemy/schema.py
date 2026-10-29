"""Descripción del esquema real de la base (lo que hay, no lo que dice tables.py) y de
las migraciones de Alembic, para la vista "Modelo de datos"."""

import warnings

import sqlalchemy as sa
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from billing.domain.schema import ColumnInfo, ForeignKeyInfo, IndexInfo, MigrationInfo, SchemaInfo, TableInfo
from billing.infrastructure.persistence.sqlalchemy.database import MIGRATIONS_DIR


def _indexes(inspector: sa.Inspector, name: str) -> list[IndexInfo]:
    result = []
    with warnings.catch_warnings():
        # SQLite no refleja índices sobre expresiones (uq_categories_owner_name_portable).
        warnings.simplefilter("ignore", sa.exc.SAWarning)
        indexes = inspector.get_indexes(name)
        constraints = inspector.get_unique_constraints(name)
    for index in indexes:
        # Los índices sobre expresiones (lower(name)) traen None en column_names.
        expressions = index.get("expressions") or index["column_names"]
        result.append(IndexInfo(index["name"], tuple(str(e) for e in expressions), bool(index["unique"])))
    for constraint in constraints:
        result.append(IndexInfo(constraint["name"] or "(única)", tuple(constraint["column_names"]), True))
    return sorted(result, key=lambda i: i.name)


def _migrations(connection: sa.Connection) -> tuple[list[MigrationInfo], str | None, str | None]:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    script = ScriptDirectory.from_config(cfg)
    current = MigrationContext.configure(connection).get_current_revision()
    ordered = list(reversed(list(script.walk_revisions())))  # de la primera a la última
    applied = {r.revision for r in script.iterate_revisions(current, "base")} if current else set()
    migrations = [MigrationInfo(r.revision, (r.doc or "").strip(), r.revision in applied) for r in ordered]
    return migrations, current, script.get_current_head()


def describe(engine: sa.Engine) -> SchemaInfo:
    inspector = sa.inspect(engine)
    tables = []
    with engine.connect() as connection:
        for name in sorted(inspector.get_table_names()):
            if name == "alembic_version":
                continue
            primary = set(inspector.get_pk_constraint(name).get("constrained_columns") or [])
            columns = [
                ColumnInfo(
                    name=c["name"],
                    type=str(c["type"]),
                    nullable=bool(c["nullable"]),
                    primary_key=c["name"] in primary,
                    default=str(c["default"]) if c.get("default") is not None else None,
                )
                for c in inspector.get_columns(name)
            ]
            foreign_keys = [
                ForeignKeyInfo(
                    columns=tuple(fk["constrained_columns"]),
                    ref_table=fk["referred_table"],
                    ref_columns=tuple(fk["referred_columns"]),
                    on_delete=(fk.get("options") or {}).get("ondelete"),
                )
                for fk in inspector.get_foreign_keys(name)
            ]
            rows = connection.execute(sa.select(sa.func.count()).select_from(sa.table(name))).scalar_one()
            tables.append(TableInfo(name, columns, foreign_keys, _indexes(inspector, name), rows))
        migrations, current, head = _migrations(connection)
    return SchemaInfo(engine.dialect.name, tables, migrations, current, head)
