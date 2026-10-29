"""Almacén en memoria con la semántica de una transacción.

Cada unidad de trabajo trabaja sobre una copia del estado; `commit()` la publica y
salir sin commit la descarta, como en una base de datos.
"""

import copy
import threading
from dataclasses import dataclass, field
from datetime import datetime

from billing.domain.catalog import DEFAULT_CATEGORIES
from billing.domain.models import Category

COLLECTIONS = (
    "users",
    "purchases",
    "attachments",
    "categories",
    "confirmations",
    "agent_settings",
    "mailboxes",
    "audit_log",
    "forecast_runs",
    "forecast_models",
    "forecasts",
)


@dataclass
class State:
    rows: dict[str, dict] = field(default_factory=lambda: {name: {} for name in COLLECTIONS})
    sequences: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COLLECTIONS, 0))
    item_sequence: int = 0


class MemoryStore:
    def __init__(self) -> None:
        self._state = State()
        self._lock = threading.Lock()
        self.initialized = False

    def snapshot(self) -> State:
        with self._lock:
            return copy.deepcopy(self._state)

    def publish(self, state: State) -> None:
        with self._lock:
            self._state = copy.deepcopy(state)

    def init_schema(self) -> None:
        """Equivalente a las migraciones: crea las categorías generales iniciales."""
        if self.initialized:
            return
        state = self.snapshot()
        now = datetime.now()
        for name in DEFAULT_CATEGORIES:
            state.sequences["categories"] += 1
            category = Category(name=name)
            category.id = state.sequences["categories"]
            category.created_at = now
            state.rows["categories"][category.id] = category
        self.publish(state)
        self.initialized = True
