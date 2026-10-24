"""Servicio de confirmaciones de seguridad.

Flujo de una acción sensible (domain/security.py):

1. `request()`   crea la solicitud y envía un enlace de un solo uso al correo.
2. `confirm_email()`  el usuario abre el enlace (con su sesión iniciada).
3. Si la acción exige 2FA: `start_otp_check()` devuelve la URL de reautenticación
   del proveedor de identidad y `verify_otp()` valida la vuelta (claim `amr`).
4. Con todos los pasos hechos (`is_ready`), la página ejecuta la acción con
   application/security/account_actions.py, que marca la solicitud como usada.

Los tokens y `state` se guardan como SHA-256; los valores en claro solo viajan en el
correo y en la URL de vuelta.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from compras.domain import security
from compras.domain.errors import ValidationError
from compras.domain.models import SecurityConfirmation, User
from compras.domain.ports.identity import IdentityError, Reauthenticator
from compras.domain.ports.mail import EmailContent, Mailer
from compras.domain.ports.repositories import UnitOfWork

QUERY_TOKEN = "confirmar"  # parámetro de la URL del enlace del correo


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now()


@dataclass(frozen=True)
class Requested:
    confirmation: SecurityConfirmation
    link: str


def active(uow: UnitOfWork, user_id: str, *, now: datetime | None = None) -> dict[str, SecurityConfirmation]:
    """La solicitud vigente de cada propósito (la más reciente)."""
    now = now or _now()
    result: dict[str, SecurityConfirmation] = {}
    for confirmation in uow.confirmations.for_user(user_id):
        if confirmation.is_active(now) and confirmation.purpose not in result:
            result[confirmation.purpose] = confirmation
    return result


def request(
    uow: UnitOfWork,
    mailer: Mailer,
    user: User,
    purpose: str,
    *,
    otp_enabled: bool,
    link_base: str,
    now: datetime | None = None,
) -> Requested:
    """Crea la solicitud, anula las anteriores del mismo propósito y envía el correo.

    `link_base` es la URL de la página que recibe el enlace (p. ej. .../configuracion).
    Lanza ValidationError si no hay correo o se pidió otro hace menos de RESEND_COOLDOWN,
    y MailError si el correo no sale (la solicitud no se guarda).
    """
    now = now or _now()
    if purpose not in security.PURPOSES:
        raise ValidationError(f"Acción desconocida: {purpose}")
    if not user.email:
        raise ValidationError("Tu cuenta no tiene correo electrónico; no se puede enviar la confirmación.")
    previous = [c for c in uow.confirmations.for_user(user.id) if c.purpose == purpose and c.is_active(now)]
    if previous and now - previous[0].created_at < security.RESEND_COOLDOWN:
        seconds = int((security.RESEND_COOLDOWN - (now - previous[0].created_at)).total_seconds()) + 1
        raise ValidationError(f"Ya te enviamos un correo. Espera {seconds} s para pedir otro.")

    token = secrets.token_urlsafe(32)
    confirmation = SecurityConfirmation(
        user_id=user.id,
        purpose=purpose,
        token_hash=_hash(token),
        requires_otp=security.requires_otp(purpose, otp_enabled),
        expires_at=now + security.CONFIRMATION_TTL,
    )
    # Se fija aquí (no lo pone la base) para comparar siempre con el mismo reloj.
    confirmation.created_at = now
    link = f"{link_base}?{QUERY_TOKEN}={token}"
    spec = security.PURPOSES[purpose]
    minutes = int(security.CONFIRMATION_TTL.total_seconds() // 60)
    paragraphs = [
        f"Hola {user.display_name}:",
        f"Recibimos una solicitud para {spec.label} en Registro de compras.",
        "Para continuar, confirma que fuiste tú abriendo el enlace con tu sesión iniciada.",
    ]
    if confirmation.requires_otp:
        paragraphs.append("Después te pediremos tu contraseña y el código de tu app de verificación en dos pasos.")
    paragraphs.append(f"El enlace funciona una sola vez y caduca en {minutes} minutos.")
    mailer.send(
        EmailContent(
            to=user.email,
            subject=f"Confirma: {spec.title.lower()}",
            title=spec.title,
            paragraphs=paragraphs,
            action_label="Confirmar que fui yo",
            action_url=link,
            footer=(
                "Si no fuiste tú, ignora este correo: no se hará ningún cambio. Te recomendamos cambiar tu contraseña."
            ),
        )
    )
    for old in previous:
        old.cancelled_at = now
    uow.confirmations.add(confirmation)
    uow.commit()
    return Requested(confirmation, link)


def confirm_email(uow: UnitOfWork, token: str, *, user_id: str, now: datetime | None = None) -> SecurityConfirmation:
    """Marca el correo como confirmado. El enlace solo vale para el usuario que lo pidió."""
    now = now or _now()
    confirmation = uow.confirmations.by_token_hash(_hash(token or ""))
    if confirmation is None or confirmation.user_id != user_id:
        raise ValidationError("El enlace no es válido para tu cuenta. Inicia sesión con la cuenta que lo pidió.")
    if not confirmation.is_active(now):
        raise ValidationError("El enlace caducó o ya se usó. Vuelve a solicitar la acción.")
    if confirmation.email_confirmed_at is None:
        confirmation.email_confirmed_at = now
        uow.commit()
    return confirmation


def start_otp_check(
    uow: UnitOfWork,
    reauth: Reauthenticator,
    confirmation: SecurityConfirmation,
    *,
    login_hint: str | None,
    return_path: str,
    now: datetime | None = None,
) -> str:
    """URL a la que redirigir para pedir contraseña + código 2FA."""
    now = now or _now()
    if not confirmation.is_active(now) or not confirmation.email_confirmed:
        raise ValidationError("Primero confirma el enlace que te enviamos por correo.")
    state = secrets.token_urlsafe(24)
    confirmation.reauth_state_hash = _hash(state)
    uow.commit()
    # El nonce se deriva del state: llega de vuelta sin guardarlo aparte.
    return reauth.start_url(state=state, nonce=_hash("nonce:" + state), login_hint=login_hint, return_path=return_path)


def verify_otp(
    uow: UnitOfWork,
    reauth: Reauthenticator,
    *,
    state: str,
    code: str,
    user_id: str,
    return_path: str,
    now: datetime | None = None,
) -> SecurityConfirmation:
    """Valida la vuelta de la reautenticación: mismo usuario, reciente y con 2FA."""
    now = now or _now()
    confirmation = uow.confirmations.by_state_hash(_hash(state or ""))
    if confirmation is None or confirmation.user_id != user_id or not confirmation.is_active(now):
        raise ValidationError("La verificación no corresponde a una solicitud vigente. Vuelve a intentarlo.")
    confirmation.reauth_state_hash = None  # el state vale una sola vez, salga bien o mal
    try:
        claims = reauth.verify(code=code, nonce=_hash("nonce:" + state), return_path=return_path)
    except IdentityError as e:
        uow.commit()
        raise ValidationError(str(e)) from e
    if claims.get("sub") != user_id:
        uow.commit()
        raise ValidationError("Iniciaste sesión con otra cuenta. Usa la cuenta que pidió la acción.")
    auth_time = claims.get("auth_time")
    fresh_after = max(now - security.REAUTH_MAX_AGE, confirmation.created_at - timedelta(seconds=5))
    if not isinstance(auth_time, int | float) or datetime.fromtimestamp(auth_time) < fresh_after:
        uow.commit()
        raise ValidationError("La verificación no es reciente. Vuelve a intentarlo.")
    amr = claims.get("amr") or []
    if isinstance(amr, str):
        amr = [amr]
    if confirmation.requires_otp and not security.OTP_AMR_VALUES & {str(v).lower() for v in amr}:
        uow.commit()
        raise ValidationError("No se verificó el código de dos pasos. Vuelve a intentarlo.")
    confirmation.otp_verified_at = now
    uow.commit()
    return confirmation


def cancel(uow: UnitOfWork, confirmation: SecurityConfirmation, *, now: datetime | None = None) -> None:
    confirmation.cancelled_at = now or _now()
    uow.commit()


def mark_started(uow: UnitOfWork, confirmation: SecurityConfirmation, *, now: datetime | None = None) -> None:
    """La acción se inició en el proveedor de identidad (p. ej. pantalla de contraseña)."""
    confirmation.started_at = now or _now()
    uow.commit()


def complete(uow: UnitOfWork, confirmation: SecurityConfirmation, *, now: datetime | None = None) -> None:
    """Consume la solicitud: no podrá usarse otra vez."""
    if not confirmation.is_ready:
        raise ValidationError("Faltan pasos por confirmar.")
    confirmation.completed_at = now or _now()
    uow.commit()
