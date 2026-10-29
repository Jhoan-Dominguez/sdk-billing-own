"""Descripción neutra del esquema de datos (la vista "Modelo de datos" del administrador).

La rellena el motor de persistencia que lo soporte (PersistenceBackend.describe_schema);
la presentación no sabe de SQLAlchemy.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    primary_key: bool = False
    default: str | None = None


@dataclass(frozen=True)
class ForeignKeyInfo:
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]
    on_delete: str | None = None  # CASCADE, SET NULL... (None = no hacer nada)


@dataclass(frozen=True)
class IndexInfo:
    name: str
    columns: tuple[str, ...]  # expresiones (lower(name)) se muestran como texto
    unique: bool


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: list[ColumnInfo]
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    row_count: int | None = None


@dataclass(frozen=True)
class MigrationInfo:
    revision: str
    description: str
    applied: bool


@dataclass(frozen=True)
class SchemaInfo:
    engine: str  # postgresql, sqlite...
    tables: list[TableInfo]
    migrations: list[MigrationInfo] = field(default_factory=list)
    current_revision: str | None = None
    head_revision: str | None = None

    @property
    def pending_migrations(self) -> list[MigrationInfo]:
        return [m for m in self.migrations if not m.applied]
