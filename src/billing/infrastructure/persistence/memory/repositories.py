"""Repositorios en memoria: implementan billing.domain.ports.repositories."""

from collections.abc import Iterable
from datetime import date

from billing.infrastructure.persistence.memory.store import State


class _Repository:
    collection: str
    key = "id"

    def __init__(self, state: State, pending: list) -> None:
        self.state = state
        self.rows = state.rows[self.collection]
        self._pending = pending  # objetos añadidos que reciben id en commit()

    def get(self, key):
        return self.rows.get(key)

    def add(self, obj) -> None:
        self._pending.append((self.collection, obj))

    def delete(self, obj) -> None:
        self.rows.pop(getattr(obj, self.key, None), None)

    def _all(self) -> list:
        return list(self.rows.values())


class MemoryUserRepository(_Repository):
    collection = "users"

    def add(self, user) -> None:
        self.rows[user.id] = user
        super().add(user)

    def delete(self, user) -> None:
        super().delete(user)
        # ON DELETE CASCADE / SET NULL del esquema SQL.
        for name in ("categories", "confirmations", "mailboxes"):
            rows = self.state.rows[name]
            for key in [
                k for k, row in rows.items() if getattr(row, "owner_id", getattr(row, "user_id", None)) == user.id
            ]:
                rows.pop(key)
        for setting in self.state.rows["agent_settings"].values():
            if setting.updated_by == user.id:
                setting.updated_by = None

    def list(self, role: str | None = None):
        users = [u for u in self._all() if role is None or u.role == role]
        return sorted(users, key=lambda u: (u.name or "", u.username))

    def replace_default_category(self, old: str, new: str | None, *, owner_id: str | None) -> None:
        for user in self._all():
            if user.default_category == old and (owner_id is None or user.id == owner_id):
                user.default_category = new


class MemoryPurchaseRepository(_Repository):
    collection = "purchases"

    def delete(self, purchase) -> None:
        super().delete(purchase)
        attachments = self.state.rows["attachments"]
        for key in [k for k, a in attachments.items() if a.purchase_id == getattr(purchase, "id", None)]:
            attachments.pop(key)

    def _visible(self, owner_id: str | None):
        return [p for p in self._all() if owner_id is None or p.owner_id == owner_id]

    def between(self, start: date, end: date, *, owner_id: str | None):
        rows = [p for p in self._visible(owner_id) if start <= p.purchase_date < end]
        return sorted(rows, key=lambda p: (p.purchase_date, p.id), reverse=True)

    def by_owner(self, owner_id: str):
        return self._visible(owner_id)

    def count_by_category(self, *, owner_id: str | None) -> dict[str, int]:
        counts: dict[str, int] = {}
        for purchase in self._visible(owner_id):
            counts[purchase.category] = counts.get(purchase.category, 0) + 1
        return counts

    def reassign_category(
        self, old: str, new: str, *, owner_id: str | None, exclude_owner_ids: Iterable[str] = ()
    ) -> int:
        excluded = set(exclude_owner_ids)
        changed = 0
        for purchase in self._visible(owner_id):
            if purchase.category == old and purchase.owner_id not in excluded:
                purchase.category = new
                changed += 1
        return changed


class MemoryAttachmentRepository(_Repository):
    collection = "attachments"

    def drafts(self, *, owner_id: str | None):
        rows = [a for a in self._all() if a.purchase_id is None and (owner_id is None or a.owner_id == owner_id)]
        return sorted(rows, key=lambda a: a.id, reverse=True)

    def same_content(self, sha256: str, *, owner_id: str, exclude_id: int):
        return [a for a in self._all() if a.sha256 == sha256 and a.owner_id == owner_id and a.id != exclude_id]

    def by_message_id(self, message_id: str, *, owner_id: str):
        return next((a for a in self._all() if a.message_id == message_id and a.owner_id == owner_id), None)


class MemoryCategoryRepository(_Repository):
    collection = "categories"

    def visible_to(self, owner_id: str | None):
        return [c for c in self._all() if c.owner_id is None or (owner_id is not None and c.owner_id == owner_id)]

    def find_name(self, name: str, *, owner_id: str | None, exclude_id: int | None = None):
        return next(
            (
                c
                for c in self._all()
                if c.name.lower() == name.lower() and c.owner_id in (None, owner_id) and c.id != exclude_id
            ),
            None,
        )

    def owners_with_personal(self, name: str) -> list[str]:
        return [c.owner_id for c in self._all() if c.owner_id is not None and c.name.lower() == name.lower()]


class MemoryConfirmationRepository(_Repository):
    collection = "confirmations"

    def by_token_hash(self, token_hash: str):
        return next((c for c in self._all() if c.token_hash == token_hash), None)

    def by_state_hash(self, state_hash: str):
        return next((c for c in self._all() if c.reauth_state_hash == state_hash), None)

    def for_user(self, user_id: str):
        return sorted((c for c in self._all() if c.user_id == user_id), key=lambda c: c.id, reverse=True)

    def delete_for_user(self, user_id: str) -> None:
        for key in [k for k, c in self.rows.items() if c.user_id == user_id]:
            self.rows.pop(key)


class MemoryAgentSettingRepository(_Repository):
    collection = "agent_settings"
    key = "agent"

    def add(self, setting) -> None:
        self.rows[setting.agent] = setting
        super().add(setting)

    def list(self):
        return sorted(self._all(), key=lambda s: s.agent)


class MemoryMailboxRepository(_Repository):
    collection = "mailboxes"

    def for_owner(self, owner_id: str):
        return sorted((m for m in self._all() if m.owner_id == owner_id), key=lambda m: m.id)

    def enabled(self):
        return sorted((m for m in self._all() if m.enabled), key=lambda m: m.id)
