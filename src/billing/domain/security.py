"""Acciones sensibles de la cuenta y qué confirmaciones exige cada una.

Todas piden confirmar un enlace enviado al correo del usuario. Las que tocan el 2FA o
borran la cuenta piden además el código 2FA (si el usuario lo tiene activado), que se
verifica volviendo a iniciar sesión en el proveedor de identidad.
"""

from dataclasses import dataclass
from datetime import timedelta

CHANGE_PASSWORD = "change_password"
UPDATE_OTP = "update_otp"
REMOVE_OTP = "remove_otp"
DELETE_ACCOUNT = "delete_account"


@dataclass(frozen=True)
class Purpose:
    label: str  # "cambiar tu contraseña" (completa "Confirma que quieres ...")
    title: str  # título corto para la interfaz y el asunto del correo
    # Si el usuario tiene 2FA, exigir también su código.
    otp_if_enabled: bool


PURPOSES: dict[str, Purpose] = {
    CHANGE_PASSWORD: Purpose("cambiar tu contraseña", "Cambio de contraseña", otp_if_enabled=False),
    UPDATE_OTP: Purpose(
        "cambiar el dispositivo de verificación en dos pasos", "Cambio de verificación en dos pasos", True
    ),
    REMOVE_OTP: Purpose("desactivar la verificación en dos pasos", "Desactivar verificación en dos pasos", True),
    DELETE_ACCOUNT: Purpose("eliminar tu cuenta y todos tus datos", "Eliminación de la cuenta", True),
}

# Validez del enlace del correo (y de toda la solicitud).
CONFIRMATION_TTL = timedelta(minutes=30)
# Tiempo mínimo entre dos correos para la misma acción.
RESEND_COOLDOWN = timedelta(seconds=60)
# La reautenticación con 2FA debe ser de hace menos de esto al volver a la app.
REAUTH_MAX_AGE = timedelta(minutes=5)
# Valores del claim `amr` (Authentication Method Reference) que prueban el 2FA.
OTP_AMR_VALUES = frozenset({"otp", "totp", "mfa"})


def requires_otp(purpose: str, otp_enabled: bool) -> bool:
    return PURPOSES[purpose].otp_if_enabled and otp_enabled
