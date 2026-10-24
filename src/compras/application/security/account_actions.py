"""Ejecución de las acciones sensibles una vez confirmadas (confirmations.py).

- Cambiar contraseña y cambiar el 2FA se completan en las pantallas del proveedor de
  identidad: `continue_url()` da el enlace y `finish_identity_action()` cierra la
  solicitud cuando el proveedor vuelve con éxito.
- Desactivar el 2FA y eliminar la cuenta se ejecutan aquí (`execute()`).
"""

from dataclasses import dataclass
from datetime import datetime

from compras.application import users as user_service
from compras.application.security import confirmations
from compras.domain import security
from compras.domain.errors import ValidationError
from compras.domain.models import SecurityConfirmation, User
from compras.domain.ports.identity import ACTION_CONFIGURE_TOTP, ACTION_UPDATE_PASSWORD, AccountActions, AccountAdmin
from compras.domain.ports.repositories import UnitOfWork
from compras.domain.ports.storage import FileStorage

# Propósito -> acción del proveedor de identidad que lo completa.
IDENTITY_ACTIONS = {security.CHANGE_PASSWORD: ACTION_UPDATE_PASSWORD, security.UPDATE_OTP: ACTION_CONFIGURE_TOTP}


@dataclass(frozen=True)
class Outcome:
    message: str
    logged_out: bool = False  # la cuenta ya no existe: cerrar la sesión


def _check(confirmation: SecurityConfirmation, user_id: str, now: datetime) -> None:
    if confirmation.user_id != user_id or not confirmation.is_active(now):
        raise ValidationError("La solicitud ya no está vigente.")
    if not confirmation.is_ready:
        raise ValidationError("Faltan pasos por confirmar.")


def continue_url(
    uow: UnitOfWork,
    confirmation: SecurityConfirmation,
    actions: AccountActions,
    *,
    user_id: str,
    return_path: str,
    now: datetime | None = None,
) -> str:
    """Enlace a la pantalla del proveedor que completa la acción (contraseña o 2FA)."""
    now = now or datetime.now()
    _check(confirmation, user_id, now)
    action = IDENTITY_ACTIONS.get(confirmation.purpose)
    if action is None:
        raise ValidationError("Esta acción se ejecuta desde la aplicación.")
    if confirmation.started_at is None:
        # Desde aquí, los dispositivos 2FA anteriores son los que se borrarán al terminar.
        confirmations.mark_started(uow, confirmation, now=now)
    return actions.url(action, return_path)


def finish_identity_action(
    uow: UnitOfWork, account: AccountAdmin | None, user_id: str, action: str, *, now: datetime | None = None
) -> str | None:
    """El proveedor volvió con éxito de `action`: cierra la solicitud correspondiente.

    Para el cambio de 2FA borra los dispositivos anteriores (así quien cancela a mitad
    no se queda sin 2FA). Devuelve un mensaje, o None si no había solicitud en curso
    (p. ej. al activar el 2FA por primera vez, que no necesita confirmación).
    """
    now = now or datetime.now()
    purpose = next((p for p, a in IDENTITY_ACTIONS.items() if a == action), None)
    pending = [
        c
        for c in uow.confirmations.for_user(user_id)
        if c.purpose == purpose and c.started_at is not None and c.is_active(now)
    ]
    if not pending:
        return None
    confirmation = pending[0]
    if purpose == security.UPDATE_OTP and account is not None:
        removed = account.remove_otp(created_before=confirmation.started_at)
        confirmations.complete(uow, confirmation, now=now)
        return f"Dispositivo de verificación cambiado ({removed} anterior(es) eliminado(s))."
    confirmations.complete(uow, confirmation, now=now)
    return "Contraseña actualizada."


def execute(
    uow: UnitOfWork,
    confirmation: SecurityConfirmation,
    *,
    account: AccountAdmin,
    storage: FileStorage,
    user: User,
    now: datetime | None = None,
) -> Outcome:
    """Desactiva el 2FA o elimina la cuenta. La solicitud queda consumida."""
    now = now or datetime.now()
    _check(confirmation, user.id, now)
    if confirmation.purpose == security.REMOVE_OTP:
        account.remove_otp()
        confirmations.complete(uow, confirmation, now=now)
        return Outcome("Verificación en dos pasos desactivada.")
    if confirmation.purpose == security.DELETE_ACCOUNT:
        confirmations.complete(uow, confirmation, now=now)
        user_service.delete_account(uow, storage, account, user)
        return Outcome("Tu cuenta se eliminó.", logged_out=True)
    raise ValidationError("Esta acción se completa en la pantalla de inicio de sesión.")
