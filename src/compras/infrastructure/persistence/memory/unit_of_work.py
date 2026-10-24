from datetime import datetime

from compras.infrastructure.persistence.memory.repositories import (
    MemoryAgentSettingRepository,
    MemoryAttachmentRepository,
    MemoryCategoryRepository,
    MemoryConfirmationRepository,
    MemoryMailboxRepository,
    MemoryPurchaseRepository,
    MemoryUserRepository,
)
from compras.infrastructure.persistence.memory.store import MemoryStore

# Campos que en SQL rellena la base (server_default) y aquí rellena commit().
TIMESTAMP_FIELDS = ("created_at", "uploaded_at", "last_login_at", "updated_at")


class MemoryUnitOfWork:
    """Implementa compras.domain.ports.repositories.UnitOfWork sobre un MemoryStore."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def __enter__(self) -> "MemoryUnitOfWork":
        self._begin()
        return self

    def __exit__(self, *exc) -> None:
        self._pending = []  # lo no confirmado se descarta con la copia

    def _begin(self) -> None:
        self._state = self._store.snapshot()
        self._pending: list = []
        self.users = MemoryUserRepository(self._state, self._pending)
        self.purchases = MemoryPurchaseRepository(self._state, self._pending)
        self.attachments = MemoryAttachmentRepository(self._state, self._pending)
        self.categories = MemoryCategoryRepository(self._state, self._pending)
        self.confirmations = MemoryConfirmationRepository(self._state, self._pending)
        self.agent_settings = MemoryAgentSettingRepository(self._state, self._pending)
        self.mailboxes = MemoryMailboxRepository(self._state, self._pending)

    def _assign(self, collection: str, obj) -> None:
        now = datetime.now()
        for name in TIMESTAMP_FIELDS:
            if name in getattr(obj, "__dataclass_fields__", {}) and not hasattr(obj, name):
                setattr(obj, name, now)
        if hasattr(obj, "updated_at"):
            obj.updated_at = now
        if "id" in obj.__dataclass_fields__ and collection not in ("users",) and not hasattr(obj, "id"):
            self._state.sequences[collection] += 1
            obj.id = self._state.sequences[collection]
            self._state.rows[collection][obj.id] = obj

    def commit(self) -> None:
        for collection, obj in self._pending:
            self._assign(collection, obj)
        self._pending.clear()
        users = self._state.rows["users"]
        # Relaciones que en SQL resuelve el ORM: líneas, adjuntos y dueño de cada compra.
        for purchase in self._state.rows["purchases"].values():
            purchase.owner = users.get(purchase.owner_id)
            for item in purchase.items:
                if not hasattr(item, "id"):
                    self._state.item_sequence += 1
                    item.id = self._state.item_sequence
            for att in purchase.attachments:
                if not hasattr(att, "id"):
                    self._assign("attachments", att)
                att.purchase_id = purchase.id
        self._store.publish(self._state)

    def rollback(self) -> None:
        self._begin()
