"""Auditoría de las acciones de los administradores."""

from billing.domain.auth import Viewer
from billing.domain.models import AuditEntry, User
from billing.domain.ports.repositories import UnitOfWork


def label(user: User) -> str:
    return user.email or user.display_name


def record(
    uow: UnitOfWork,
    actor: Viewer,
    action: str,
    *,
    target: User | None = None,
    target_id: str | None = None,
    target_label: str | None = None,
    details: dict | None = None,
) -> AuditEntry:
    """Guarda la entrada en su propia transacción (también si la acción borró al usuario)."""
    entry = AuditEntry(
        actor_id=actor.user_id,
        actor_label=actor.name[:254],
        action=action,
        target_user_id=target.id if target else target_id,
        target_label=(label(target) if target else target_label or None),
        details=details or None,
    )
    uow.audit_log.add(entry)
    uow.commit()
    return entry


def entries(
    uow: UnitOfWork, *, limit: int = 500, action: str | None = None, target_user_id: str | None = None
) -> list[AuditEntry]:
    return uow.audit_log.list(limit=limit, action=action, target_user_id=target_user_id)
