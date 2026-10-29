"""Repositorios SQL: implementan billing.domain.ports.repositories."""

from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.orm import Session

from billing.domain.models import (
    AgentSetting,
    Attachment,
    AuditEntry,
    Category,
    ForecastModel,
    ForecastTrainingRun,
    MailboxConnection,
    Purchase,
    SecurityConfirmation,
    User,
)


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

    def count_by_owner(self) -> dict[str, int]:
        return dict(self.session.execute(select(Purchase.owner_id, func.count()).group_by(Purchase.owner_id)).all())

    def monthly_count_by_source(self, since: date) -> list[tuple[str, str, int]]:
        # Agrupar por mes en SQL depende del motor; se agrupa aquí (solo fecha y origen).
        query = select(Purchase.created_at, Purchase.source).where(Purchase.created_at >= since)
        counts = Counter((f"{created:%Y-%m}", source) for created, source in self.session.execute(query))
        return [(month, source, n) for (month, source), n in sorted(counts.items())]

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

    def by_message_id(self, message_id: str, *, owner_id: str) -> Attachment | None:
        query = select(Attachment).where(Attachment.message_id == message_id, Attachment.owner_id == owner_id)
        return self.session.scalars(query).first()

    def usage_by_owner(self) -> dict[str, dict[str, int]]:
        query = select(
            Attachment.owner_id,
            func.count(),
            func.coalesce(func.sum(Attachment.size), 0),
            func.sum(case((Attachment.purchase_id.is_(None), 1), else_=0)),
        ).group_by(Attachment.owner_id)
        return {
            owner: {"files": files, "bytes": int(size), "drafts": int(drafts or 0)}
            for owner, files, size, drafts in self.session.execute(query)
        }

    def extraction_log(self, since: datetime) -> list[tuple[datetime, dict | None, bool]]:
        query = (
            select(Attachment.uploaded_at, Attachment.extraction_meta, Attachment.extraction_error)
            .where(Attachment.uploaded_at >= since)
            .order_by(Attachment.uploaded_at)
        )
        return [(uploaded, meta, error is not None) for uploaded, meta, error in self.session.execute(query)]


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


class SqlSecurityConfirmationRepository(_Repository):
    model = SecurityConfirmation

    def by_token_hash(self, token_hash: str) -> SecurityConfirmation | None:
        query = select(SecurityConfirmation).where(SecurityConfirmation.token_hash == token_hash)
        return self.session.scalars(query).first()

    def by_state_hash(self, state_hash: str) -> SecurityConfirmation | None:
        query = select(SecurityConfirmation).where(SecurityConfirmation.reauth_state_hash == state_hash)
        return self.session.scalars(query).first()

    def for_user(self, user_id: str) -> list[SecurityConfirmation]:
        query = (
            select(SecurityConfirmation)
            .where(SecurityConfirmation.user_id == user_id)
            .order_by(SecurityConfirmation.id.desc())
        )
        return list(self.session.scalars(query))

    def delete_for_user(self, user_id: str) -> None:
        self.session.execute(delete(SecurityConfirmation).where(SecurityConfirmation.user_id == user_id))


class SqlAgentSettingRepository(_Repository):
    model = AgentSetting

    def list(self) -> list[AgentSetting]:
        return list(self.session.scalars(select(AgentSetting).order_by(AgentSetting.agent)))


class SqlMailboxRepository(_Repository):
    model = MailboxConnection

    def for_owner(self, owner_id: str) -> list[MailboxConnection]:
        query = select(MailboxConnection).where(MailboxConnection.owner_id == owner_id).order_by(MailboxConnection.id)
        return list(self.session.scalars(query))

    def enabled(self) -> list[MailboxConnection]:
        query = select(MailboxConnection).where(MailboxConnection.enabled.is_(True)).order_by(MailboxConnection.id)
        return list(self.session.scalars(query))

    def all(self) -> list[MailboxConnection]:
        return list(self.session.scalars(select(MailboxConnection).order_by(MailboxConnection.id)))


class SqlAuditRepository(_Repository):
    model = AuditEntry

    def list(
        self, *, limit: int = 500, action: str | None = None, target_user_id: str | None = None
    ) -> list[AuditEntry]:
        query = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
        if action is not None:
            query = query.where(AuditEntry.action == action)
        if target_user_id is not None:
            query = query.where(AuditEntry.target_user_id == target_user_id)
        return list(self.session.scalars(query))


class SqlForecastModelRepository(_Repository):
    model = ForecastModel

    def for_owner(self, owner_id: str) -> list[ForecastModel]:
        query = select(ForecastModel).where(ForecastModel.owner_id == owner_id).order_by(ForecastModel.id.desc())
        return list(self.session.scalars(query))

    def list(self, *, scope: str | None = None, status: str | None = None) -> list[ForecastModel]:
        query = select(ForecastModel).order_by(ForecastModel.id.desc())
        if scope is not None:
            query = query.where(ForecastModel.scope == scope)
        if status is not None:
            query = query.where(ForecastModel.status == status)
        return list(self.session.scalars(query))


class SqlForecastRunRepository(_Repository):
    model = ForecastTrainingRun

    def list(self, *, limit: int = 200) -> list[ForecastTrainingRun]:
        query = select(ForecastTrainingRun).order_by(ForecastTrainingRun.id.desc()).limit(limit)
        return list(self.session.scalars(query))
