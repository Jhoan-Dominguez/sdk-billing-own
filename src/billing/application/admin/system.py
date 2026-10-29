"""Estado del sistema, métricas de uso (sin importes) y retención de datos."""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from billing.application import imports
from billing.application.admin import audit
from billing.application.admin.accounts import require_manager
from billing.domain import admin
from billing.domain.auth import Viewer
from billing.domain.models import MailboxConnection, User
from billing.domain.ports.repositories import UnitOfWork
from billing.domain.ports.storage import FileStorage

# --- Servicios ------------------------------------------------------------------


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    ok: bool
    detail: str


def check_services(checks: dict[str, Callable[[], str | None]]) -> list[ServiceStatus]:
    """Ejecuta cada comprobación (bootstrap.service_checks); un fallo no detiene las demás."""
    result = []
    for name, check in checks.items():
        try:
            result.append(ServiceStatus(name, True, check() or "OK"))
        except Exception as e:  # cualquier fallo del servicio se muestra, no se propaga
            result.append(ServiceStatus(name, False, str(e) or type(e).__name__))
    return result


# --- Buzones y worker -------------------------------------------------------------


@dataclass
class MailboxHealth:
    total: int = 0
    enabled: int = 0
    failing: list[tuple[User | None, MailboxConnection]] = field(default_factory=list)
    stale: list[tuple[User | None, MailboxConnection]] = field(default_factory=list)
    last_sync: datetime | None = None
    # None: no hay buzones activos y no se puede saber si el worker corre.
    worker_ok: bool | None = None


def mailbox_health(
    uow: UnitOfWork, actor: Viewer, *, interval_seconds: int, now: datetime | None = None
) -> MailboxHealth:
    """El worker corre en otro contenedor: su latido visible es la última sincronización."""
    require_manager(actor)
    now = now or datetime.now()
    users = {u.id: u for u in uow.users.list()}
    mailboxes = uow.mailboxes.all()
    enabled = [m for m in mailboxes if m.enabled]
    # Tres intervalos sin sincronizar = el worker no está pasando (o ese buzón se atasca).
    limit = now - timedelta(seconds=3 * max(interval_seconds, 60))
    health = MailboxHealth(total=len(mailboxes), enabled=len(enabled))
    health.failing = [(users.get(m.owner_id), m) for m in enabled if m.last_error]
    health.stale = [(users.get(m.owner_id), m) for m in enabled if not m.last_sync_at or m.last_sync_at < limit]
    syncs = [m.last_sync_at for m in enabled if m.last_sync_at]
    health.last_sync = max(syncs) if syncs else None
    if enabled:
        health.worker_ok = health.last_sync is not None and health.last_sync >= limit
    return health


# --- Agentes IA -----------------------------------------------------------------


@dataclass
class ExtractionStats:
    document_type: str
    method: str  # llm | rules
    provider: str | None
    model: str | None
    total: int = 0
    errors: int = 0
    durations: list[int] = field(default_factory=list)

    @property
    def error_pct(self) -> float:
        return 100 * self.errors / self.total if self.total else 0.0

    @property
    def avg_seconds(self) -> float | None:
        return sum(self.durations) / len(self.durations) / 1000 if self.durations else None


def extraction_stats(uow: UnitOfWork, actor: Viewer, *, days: int = 30, now: datetime | None = None):
    """Extracciones de los últimos `days` días por tipo de documento, método, proveedor y modelo."""
    require_manager(actor)
    since = (now or datetime.now()) - timedelta(days=days)
    groups: dict[tuple, ExtractionStats] = {}
    for _uploaded, meta, failed in uow.attachments.extraction_log(since):
        meta = meta or {}
        key = (
            meta.get("document_type") or "invoice",
            meta.get("method") or "rules",
            meta.get("provider"),
            meta.get("model"),
        )
        stats = groups.setdefault(key, ExtractionStats(*key))
        stats.total += 1
        stats.errors += failed
        if meta.get("duration_ms"):
            stats.durations.append(int(meta["duration_ms"]))
    return sorted(groups.values(), key=lambda s: -s.total)


# --- Métricas de uso -------------------------------------------------------------


@dataclass
class UsageMetrics:
    users_by_role: dict[str, int]
    active_30d: int
    new_30d: int
    blocked: int
    pending_drafts: int
    files: int
    bytes: int
    purchases: int
    # (mes "YYYY-MM", origen, compras registradas ese mes): cuántas, nunca cuánto dinero.
    monthly_by_source: list[tuple[str, str, int]]


def usage_metrics(uow: UnitOfWork, actor: Viewer, *, months: int = 6, now: datetime | None = None) -> UsageMetrics:
    require_manager(actor)
    now = now or datetime.now()
    recent = now - timedelta(days=30)
    users = uow.users.list()
    usage = uow.attachments.usage_by_owner().values()
    first_month = date(now.year, now.month, 1)
    for _ in range(months - 1):
        first_month = (first_month - timedelta(days=1)).replace(day=1)
    return UsageMetrics(
        users_by_role=dict(Counter(u.role for u in users)),
        active_30d=sum(1 for u in users if u.last_login_at >= recent),
        new_30d=sum(1 for u in users if u.created_at >= recent),
        blocked=sum(1 for u in users if u.is_disabled),
        pending_drafts=sum(u["drafts"] for u in usage),
        files=sum(u["files"] for u in usage),
        bytes=sum(u["bytes"] for u in usage),
        purchases=sum(uow.purchases.count_by_owner().values()),
        monthly_by_source=uow.purchases.monthly_count_by_source(first_month),
    )


# --- Retención --------------------------------------------------------------------


@dataclass(frozen=True)
class StaleDrafts:
    count: int
    bytes: int
    users: int


def _stale_drafts(uow: UnitOfWork, older_than_days: int, now: datetime | None):
    cutoff = (now or datetime.now()) - timedelta(days=older_than_days)
    # owner_id=None: todos los usuarios; los borradores nunca salen de este módulo.
    return [att for att in imports.drafts(uow, owner_id=None) if att.uploaded_at < cutoff]


def stale_drafts(uow: UnitOfWork, actor: Viewer, *, older_than_days: int, now: datetime | None = None) -> StaleDrafts:
    require_manager(actor)
    drafts = _stale_drafts(uow, older_than_days, now)
    return StaleDrafts(len(drafts), sum(a.size for a in drafts), len({a.owner_id for a in drafts}))


def purge_stale_drafts(
    uow: UnitOfWork, storage: FileStorage, actor: Viewer, *, older_than_days: int, now: datetime | None = None
) -> int:
    """Descarta los borradores sin revisar más antiguos que `older_than_days` (y sus archivos)."""
    require_manager(actor)
    drafts = _stale_drafts(uow, older_than_days, now)
    per_user: dict[str, int] = defaultdict(int)
    for att in drafts:
        per_user[att.owner_id] += 1
        imports.discard_draft(uow, storage, att)
    if drafts:
        audit.record(
            uow,
            actor,
            admin.PURGE_DRAFTS,
            details={"older_than_days": older_than_days, "drafts": len(drafts), "users": len(per_user)},
        )
    return len(drafts)


def inactive_users(
    uow: UnitOfWork, actor: Viewer, *, months: int, role: str | None = None, now: datetime | None = None
) -> list[User]:
    """Usuarios sin iniciar sesión en los últimos `months` meses, los más antiguos primero."""
    require_manager(actor)
    cutoff = (now or datetime.now()) - timedelta(days=30 * months)
    users = [u for u in uow.users.list(role) if u.last_login_at < cutoff]
    return sorted(users, key=lambda u: u.last_login_at)
