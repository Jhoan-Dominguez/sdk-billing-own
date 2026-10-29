"""Gestión de las cuentas de los demás usuarios (roles con `manages_users`).

Cada acción comprueba el permiso, aplica el cambio en el proveedor de identidad y luego
en la app, y queda en la auditoría. Nadie actúa sobre su propia cuenta desde aquí y
siempre queda al menos un administrador activo.
"""

from dataclasses import dataclass, field
from datetime import datetime

from billing.application import users as user_service
from billing.application.admin import audit
from billing.domain import admin
from billing.domain.auth import ADMIN, ROLES, Viewer
from billing.domain.errors import PermissionDenied, ValidationError
from billing.domain.models import User
from billing.domain.ports.identity import ACTION_UPDATE_PASSWORD, ACTION_VERIFY_EMAIL, UserDirectory
from billing.domain.ports.repositories import UnitOfWork
from billing.domain.ports.storage import FileStorage
from billing.domain.values import clean_str


@dataclass
class AccountRow:
    """Una cuenta en el panel: datos del usuario y cifras de uso (nunca importes)."""

    user: User
    purchases: int = 0
    files: int = 0
    bytes: int = 0
    drafts: int = 0
    mailboxes: int = 0
    mailbox_errors: int = 0
    # Del proveedor de identidad (vacío si no responde): enabled, email_verified, otp, created.
    identity: dict = field(default_factory=dict)

    # La app la conoce pero el proveedor de identidad no (borrada desde su consola).
    identity_missing: bool = False

    @property
    def blocked(self) -> bool:
        return self.user.is_disabled or self.identity.get("enabled") is False


def require_manager(actor: Viewer) -> None:
    if not actor.manages_users:
        raise PermissionDenied("Solo un administrador puede gestionar cuentas.")


def get(uow: UnitOfWork, actor: Viewer, user_id: str) -> User | None:
    require_manager(actor)
    return uow.users.get(user_id)


def overview(uow: UnitOfWork, actor: Viewer, statuses: dict[str, dict] | None = None) -> list[AccountRow]:
    """Todas las cuentas con sus cifras de uso.

    `statuses` = UserDirectory.statuses(); None si no se pudo leer (no se marca ninguna
    cuenta como ausente del proveedor).
    """
    require_manager(actor)
    purchases = uow.purchases.count_by_owner()
    files = uow.attachments.usage_by_owner()
    mailboxes = uow.mailboxes.all()
    rows = []
    for user in uow.users.list():
        usage = files.get(user.id, {})
        own = [m for m in mailboxes if m.owner_id == user.id]
        rows.append(
            AccountRow(
                user=user,
                purchases=purchases.get(user.id, 0),
                files=usage.get("files", 0),
                bytes=usage.get("bytes", 0),
                drafts=usage.get("drafts", 0),
                mailboxes=len(own),
                mailbox_errors=sum(1 for m in own if m.enabled and m.last_error),
                identity=(statuses or {}).get(user.id, {}),
                identity_missing=statuses is not None and user.id not in statuses,
            )
        )
    return rows


def _check_target(uow: UnitOfWork, actor: Viewer, user: User, *, removes_admin: bool = False) -> None:
    require_manager(actor)
    if user.id == actor.user_id:
        raise PermissionDenied("No puedes aplicar esta acción a tu propia cuenta (usa Configuración).")
    if removes_admin and user.role == ADMIN:
        others = [u for u in uow.users.list(ADMIN) if u.id != user.id and not u.is_disabled]
        if not others:
            raise PermissionDenied("Debe quedar al menos un administrador activo.")


def block(uow: UnitOfWork, directory: UserDirectory, actor: Viewer, user: User) -> None:
    """Deshabilita la cuenta en el proveedor, cierra sus sesiones y la marca en la app."""
    _check_target(uow, actor, user, removes_admin=True)
    account = directory.account(user.id)
    account.set_enabled(False)
    account.logout_everywhere()
    user.disabled_at = datetime.now()
    uow.commit()
    audit.record(uow, actor, admin.BLOCK_USER, target=user)


def unblock(uow: UnitOfWork, directory: UserDirectory, actor: Viewer, user: User) -> None:
    _check_target(uow, actor, user)
    directory.account(user.id).set_enabled(True)
    user.disabled_at = None
    uow.commit()
    audit.record(uow, actor, admin.UNBLOCK_USER, target=user)


def delete(uow: UnitOfWork, storage: FileStorage, directory: UserDirectory, actor: Viewer, user: User) -> None:
    """Borra la cuenta y todos sus datos (igual que el borrado desde Configuración)."""
    _check_target(uow, actor, user, removes_admin=True)
    target_id, target_label, role = user.id, audit.label(user), user.role
    user_service.delete_account(uow, storage, directory.account(user.id), user)
    audit.record(uow, actor, admin.DELETE_USER, target_id=target_id, target_label=target_label, details={"role": role})


def change_role(uow: UnitOfWork, directory: UserDirectory, actor: Viewer, user: User, role: str) -> None:
    """Cambia el rol en el proveedor y cierra sus sesiones para que el nuevo rol aplique ya."""
    if role not in ROLES:
        raise ValidationError(f"Rol desconocido: {role!r}.")
    _check_target(uow, actor, user, removes_admin=role != ADMIN)
    if role == user.role:
        return
    old = user.role
    account = directory.account(user.id)
    account.set_role(role, ROLES)
    account.logout_everywhere()
    user.role = role
    uow.commit()
    audit.record(uow, actor, admin.CHANGE_ROLE, target=user, details={"from": old, "to": role})


def logout(uow: UnitOfWork, directory: UserDirectory, actor: Viewer, user: User) -> None:
    _check_target(uow, actor, user)
    directory.account(user.id).logout_everywhere()
    audit.record(uow, actor, admin.LOGOUT_USER, target=user)


def force_password_change(uow: UnitOfWork, directory: UserDirectory, actor: Viewer, user: User) -> None:
    """Envía el correo del proveedor para fijar una contraseña nueva y cierra sus sesiones."""
    _check_target(uow, actor, user)
    account = directory.account(user.id)
    account.send_actions_email([ACTION_UPDATE_PASSWORD])
    account.logout_everywhere()
    audit.record(uow, actor, admin.FORCE_PASSWORD_CHANGE, target=user)


def remove_otp(uow: UnitOfWork, directory: UserDirectory, actor: Viewer, user: User) -> int:
    """Quita la verificación en dos pasos (p. ej. perdió el teléfono). Devuelve cuántos dispositivos."""
    _check_target(uow, actor, user)
    removed = directory.account(user.id).remove_otp()
    audit.record(uow, actor, admin.REMOVE_OTP, target=user, details={"devices": removed})
    return removed


def resend_verification(uow: UnitOfWork, directory: UserDirectory, actor: Viewer, user: User) -> None:
    _check_target(uow, actor, user)
    directory.account(user.id).send_actions_email([ACTION_VERIFY_EMAIL])
    audit.record(uow, actor, admin.RESEND_VERIFICATION, target=user)


def invite(uow: UnitOfWork, directory: UserDirectory, actor: Viewer, *, email, first_name, last_name, role: str) -> str:
    """Crea la cuenta y le envía el correo para verificarla y fijar su contraseña.

    El usuario aparece en la app (tabla users) en su primer inicio de sesión.
    """
    require_manager(actor)
    email, first, last = (clean_str(email) or "").lower(), clean_str(first_name), clean_str(last_name)
    if "@" not in email or len(email) > 254:
        raise ValidationError("Correo electrónico no válido.")
    if not first or not last:
        raise ValidationError("Nombre y apellido son obligatorios.")
    if role not in ROLES:
        raise ValidationError(f"Rol desconocido: {role!r}.")
    if directory.find_by_email(email):
        raise ValidationError("Ya existe una cuenta con ese correo.")
    user_id = directory.create(email=email, first_name=first, last_name=last, role=role)
    directory.account(user_id).send_actions_email([ACTION_VERIFY_EMAIL, ACTION_UPDATE_PASSWORD])
    audit.record(uow, actor, admin.INVITE_USER, target_id=user_id, target_label=email, details={"role": role})
    return user_id
