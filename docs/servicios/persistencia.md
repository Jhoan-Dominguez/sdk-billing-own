# Persistencia (base de datos intercambiable)

Los casos de uso solo conocen el puerto `UnitOfWork` (`domain/ports/repositories.py`). El
motor se elige con `COMPRAS_PERSISTENCE` y, para SQL, con la URL.

| `COMPRAS_PERSISTENCE` | Motor | Uso |
|---|---|---|
| `sql` (por defecto) | SQLAlchemy 2 + Alembic. Cualquier URL: **PostgreSQL** (por defecto), **SQLite**, **MySQL/MariaDB**… | Producción y desarrollo |
| `memory` | Diccionarios en el proceso | Pruebas, demos, desarrollo sin base |

Ejemplos:

```bash
# PostgreSQL del compose (por defecto: se construye desde POSTGRES_*)
COMPRAS_PERSISTENCE=sql
# SQLite en un archivo
COMPRAS_DATABASE_URL=sqlite:///data/compras.sqlite
# MySQL (instalar el driver: pip install pymysql)
COMPRAS_DATABASE_URL=mysql+pymysql://usuario:clave@localhost:3306/compras
# Sin base de datos (los datos se pierden al reiniciar)
COMPRAS_PERSISTENCE=memory
```

## Contrato (puertos)

`UnitOfWork` agrupa los repositorios de una transacción:

```python
with bootstrap.unit_of_work() as uow:
    purchase = uow.purchases.get(42)
    ...
    uow.commit()  # sin commit, los cambios se descartan al salir
```

| Repositorio | Métodos |
|---|---|
| `users` | `get`, `add`, `delete`, `list(role)`, `replace_default_category(old, new, owner_id)` |
| `purchases` | `get`, `add`, `delete`, `between(start, end, owner_id)`, `by_owner`, `count_by_category(owner_id)`, `reassign_category(old, new, owner_id, exclude_owner_ids)` |
| `attachments` | `get`, `add`, `delete`, `drafts(owner_id)`, `same_content(sha256, owner_id, exclude_id)`, `by_message_id(message_id, owner_id)` |
| `categories` | `get`, `add`, `delete`, `visible_to(owner_id)`, `find_name(name, owner_id, exclude_id)`, `owners_with_personal(name)` |
| `confirmations` | `get`, `add`, `by_token_hash`, `by_state_hash`, `for_user`, `delete_for_user` |
| `agent_settings` | `get`, `add`, `delete`, `list` |
| `mailboxes` | `get`, `add`, `delete`, `for_owner`, `enabled` |

Convenciones que todo motor debe respetar:

- `owner_id=None` significa «todos» y solo debe venir de `Viewer.owner_filter()`.
- Las relaciones `purchase.items`, `purchase.attachments` y `purchase.owner` deben estar
  disponibles mientras el bloque esté abierto; al confirmar un borrador, añadir el adjunto a
  `purchase.attachments` fija su `purchase_id`.
- Ids, `created_at`, `uploaded_at`, `last_login_at` y `updated_at` los asigna el almacenamiento.
- Cascadas: borrar una compra borra sus líneas y adjuntos; borrar un usuario borra sus
  categorías personales, confirmaciones y buzones, y deja `agent_settings.updated_by` en NULL.
- Los objetos leídos siguen legibles después del bloque.

## Registro de motores

`infrastructure/persistence/registry.py`:

```python
BACKENDS = {
    "sql": "compras.infrastructure.persistence.sqlalchemy.backend",
    "memory": "compras.infrastructure.persistence.memory.backend",
}
```

Cada módulo expone `create(settings) -> PersistenceBackend`, un objeto con `name`,
`unit_of_work()` e `init_schema()` (crear o migrar el esquema; idempotente). `bootstrap`
solo llama a `registry.create(settings.PERSISTENCE_BACKEND, settings)`.

## Adaptador SQL (`infrastructure/persistence/sqlalchemy/`)

| Archivo | Contenido |
|---|---|
| `tables.py` | Esquema (`MetaData`), índices por motor (`DIALECT_SPECIFIC_INDEXES`, `index_applies`) |
| `orm.py` | Mapeo imperativo de las dataclasses (`start_mappers`, una vez por proceso) |
| `repositories.py` | Repositorios con consultas `select`/`update`/`delete` |
| `unit_of_work.py` | `SqlAlchemyUnitOfWork`: una sesión por bloque; `__exit__` solo cierra la sesión |
| `database.py` | `make_engine` (con `pool_pre_ping`; en SQLite activa `PRAGMA foreign_keys=ON`), `make_session_factory` (`expire_on_commit=False`), `migrate` |
| `backend.py` | `SqlAlchemyBackend` |
| `migrations/` | Alembic (`env.py` filtra los índices de otro motor) |

Portabilidad: el índice único de categorías usa `NULLS NOT DISTINCT` en PostgreSQL y
`coalesce(owner_id, '')` en los demás; las migraciones usan `batch_alter_table` (SQLite
recrea la tabla); los `ON DELETE` se aplican en SQLite gracias al `PRAGMA`. `migrate()` marca
como `0001` las bases creadas antes de usar Alembic.

## Adaptador en memoria (`infrastructure/persistence/memory/`)

- `store.py`: `MemoryStore` con el estado (`State`: filas por colección y secuencias) y un
  candado. `init_schema()` crea las categorías generales iniciales.
- `unit_of_work.py`: cada bloque trabaja sobre una **copia profunda** del estado; `commit()`
  asigna ids y fechas, resuelve relaciones (dueño, líneas, adjuntos) y publica una copia, y
  salir sin commit la descarta. Mismo comportamiento transaccional que SQL.
- `repositories.py`: mismas consultas con filtros y ordenaciones en Python, incluidas las cascadas.

Los datos viven en el proceso: no se comparten entre la app y el worker, y se pierden al reiniciar.

## Añadir un motor (p. ej. MongoDB)

1. Crear `infrastructure/persistence/mongo/` con repositorios que cumplan los protocolos de
   `domain/ports/repositories.py` (guardando y reconstruyendo las dataclasses de `domain/models.py`).
2. Una unidad de trabajo con `__enter__`, `__exit__`, `commit`, `rollback` y los siete repositorios.
3. `backend.py` con `create(settings)` que devuelva un objeto con `unit_of_work()` e `init_schema()`.
4. Una línea en `BACKENDS` y, si hace falta, nuevas variables en `settings.py`.

Quitar un motor es borrar su carpeta y su línea. Ni el dominio, ni los casos de uso, ni la
interfaz cambian.

## Verificación realizada

El mismo recorrido de casos de uso (usuarios, categorías con unicidad, compras con líneas,
reasignación de categorías, borradores bancarios con `Message-ID`, compras similares,
confirmación de borradores, solicitudes de seguridad, configuración de agentes, buzones
cifrados, rollback sin commit y borrado de cuenta con cascadas) pasó sin cambios en
PostgreSQL 17, SQLite y memoria. `alembic upgrade head`, `downgrade 0002` y `alembic check` se
probaron en PostgreSQL y SQLite.
