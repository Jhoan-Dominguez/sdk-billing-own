from billing.infrastructure.persistence.memory.store import MemoryStore
from billing.infrastructure.persistence.memory.unit_of_work import MemoryUnitOfWork


class MemoryBackend:
    """PersistenceBackend en memoria (ver infrastructure/persistence/registry.py)."""

    name = "memory"

    def __init__(self) -> None:
        self.store = MemoryStore()

    def unit_of_work(self) -> MemoryUnitOfWork:
        return MemoryUnitOfWork(self.store)

    def init_schema(self) -> None:
        self.store.init_schema()


def create(_settings) -> MemoryBackend:
    return MemoryBackend()
