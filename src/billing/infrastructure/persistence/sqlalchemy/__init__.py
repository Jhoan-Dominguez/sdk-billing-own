"""Persistencia con SQLAlchemy (PostgreSQL hoy; cualquier motor que soporte SQLAlchemy).

- tables.py          esquema (fuente de verdad de las migraciones de Alembic)
- orm.py             mapeo imperativo tabla <-> entidad del dominio
- repositories.py    implementación de los puertos de repositorio
- unit_of_work.py    transacción sobre los repositorios
- database.py        engine, sesiones y migraciones
"""
