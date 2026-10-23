"""Repositorios SQL: implementan compras.domain.ports.repositories."""

from collections.abc import Iterable
from datetime import date

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from compras.domain.models import Attachment, Category, Purchase, User


class _Repository:
    model: type

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, key):
        return self.session.get(self.model, key)

    def add(self, obj) -> None:
        self.session.add(obj)

    def delete(self, obj) -> None:
        self.session.delete(obj)


class SqlUserRepository(_Repository):
    model = User

    def list(self, role: str | None = None) -> list[User]:
        query = select(User).order_by(User.name, User.username)
        if role:
            query = query.where(User.role == role)
        return list(self.session.scalars(query))

    def replace_default_category(self, old: str, new: str | None, *, owner_id: str | None) -> None:
        query = update(User).where(User.default_category == old)
        if owner_id is not None:
            query = query.where(User.id == owner_id)
        self.session.execute(query.values(default_category=new))


class SqlPurchaseRepository(_Repository):
    model = Purchase

    def between(self, start: date, end: date, *, owner_id: str | None) -> list[Purchase]:
        query = (
            select(Purchase)
            .where(Purchase.purchase_date >= start, Purchase.purchase_date < end)
            .order_by(Purchase.purchase_date.desc(), Purchase.id.desc())
        )
        if owner_id is not None:
            query = query.where(Purchase.owner_id == owner_id)
        return list(self.session.scalars(query))

    def by_owner(self, owner_id: str) -> list[Purchase]:
        return list(self.session.scalars(select(Purchase).where(Purchase.owner_id == owner_id)))

    def count_by_category(self, *, owner_id: str | None) -> dict[str, int]:
        query = select(Purchase.category, func.count()).group_by(Purchase.category)
        if owner_id is not None:
            query = query.where(Purchase.owner_id == owner_id)
        return dict(self.session.execute(query).all())

    def reassign_category(
        self, old: str, new: str, *, owner_id: str | None, exclude_owner_ids: Iterable[str] = ()
    ) -> int:
        query = update(Purchase).where(Purchase.category == old)
        if owner_id is not None:
            query = query.where(Purchase.owner_id == owner_id)
        if excluded := list(exclude_owner_ids):
            query = query.where(Purchase.owner_id.not_in(excluded))
        return self.session.execute(query.values(category=new)).rowcount


class SqlAttachmentRepository(_Repository):
    model = Attachment

    def drafts(self, *, owner_id: str | None) -> list[Attachment]:
        query = select(Attachment).where(Attachment.purchase_id.is_(None)).order_by(Attachment.id.desc())
        if owner_id is not None:
            query = query.where(Attachment.owner_id == owner_id)
        return list(self.session.scalars(query))

    def same_content(self, sha256: str, *, owner_id: str, exclude_id: int) -> list[Attachment]:
        query = select(Attachment).where(
            Attachment.sha256 == sha256, Attachment.owner_id == owner_id, Attachment.id != exclude_id
        )
        return list(self.session.scalars(query))


class SqlCategoryRepository(_Repository):
    model = Category

    def visible_to(self, owner_id: str | None) -> list[Category]:
        scope = Category.owner_id.is_(None)
        if owner_id is not None:
            scope = or_(scope, Category.owner_id == owner_id)
        return list(self.session.scalars(select(Category).where(scope)))

    def find_name(self, name: str, *, owner_id: str | None, exclude_id: int | None = None) -> Category | None:
        query = select(Category).where(
            func.lower(Category.name) == name.lower(),
            or_(Category.owner_id.is_(None), Category.owner_id == owner_id),
        )
        if exclude_id is not None:
            query = query.where(Category.id != exclude_id)
        return self.session.scalars(query).first()

    def owners_with_personal(self, name: str) -> list[str]:
        query = select(Category.owner_id).where(
            Category.owner_id.is_not(None), func.lower(Category.name) == name.lower()
        )
        return list(self.session.scalars(query))
