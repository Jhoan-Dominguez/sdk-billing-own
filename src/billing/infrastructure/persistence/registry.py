"""Motores de persistencia disponibles (BILLING_PERSISTENCE).

Cada motor es un paquete con un módulo `backend.py` que expone `create(settings)` y
devuelve un PersistenceBackend. Para añadir un motor (MongoDB, DynamoDB...): crear
su paquete implementando los repositorios de domain/ports/repositories.py y añadir
aquí una línea. Para quitarlo: borrar la línea y el paquete.
"""

import importlib
from typing import Protocol

from billing.domain.ports.repositories import UnitOfWork


class PersistenceBackend(Protocol):
    name: str

    def unit_of_work(self) -> UnitOfWork: ...

    def init_schema(self) -> None:
        """Crea o migra el esquema (idempotente)."""
        ...


BACKENDS: dict[str, str] = {
    "sql": "billing.infrastructure.persistence.sqlalchemy.backend",
    "memory": "billing.infrastructure.persistence.memory.backend",
}


class UnknownBackend(ValueError):
    pass


def create(name: str, settings) -> PersistenceBackend:
    try:
        module = BACKENDS[name]
    except KeyError:
        raise UnknownBackend(f"BILLING_PERSISTENCE desconocido: {name!r}. Opciones: {', '.join(BACKENDS)}") from None
    return importlib.import_module(module).create(settings)
