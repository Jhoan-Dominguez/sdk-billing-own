"""Proveedor de identidad (hoy Keycloak): cuenta del usuario autenticado."""

from datetime import datetime
from typing import Protocol

# Acciones que el usuario completa en las pantallas del proveedor de identidad
# (la app nunca ve contraseñas ni secretos de 2FA).
ACTION_UPDATE_PASSWORD = "UPDATE_PASSWORD"
ACTION_CONFIGURE_TOTP = "CONFIGURE_TOTP"
ACTION_VERIFY_EMAIL = "VERIFY_EMAIL"


class IdentityError(RuntimeError):
    pass


class IdentityNotFound(IdentityError):
    """La cuenta no existe en el proveedor de identidad."""


class AccountAdmin(Protocol):
    """Operaciones sobre UNA cuenta: la del usuario autenticado."""

    def profile(self) -> dict:
        """firstName, lastName, email, username, created (datetime | None)."""
        ...

    def update_names(self, first_name: str, last_name: str) -> None: ...
    def linked_providers(self) -> list[str]: ...
    def has_password(self) -> bool: ...
    def otp_enabled_since(self) -> datetime | None | bool:
        """False si no tiene 2FA; si lo tiene, su fecha de alta (o None si se desconoce)."""
        ...

    def remove_otp(self, created_before: datetime | None = None) -> int:
        """Borra los dispositivos 2FA (solo los creados antes de `created_before` si se
        indica) y devuelve cuántos borró."""
        ...

    def sessions(self) -> list[dict]:
        """Sesiones abiertas: ip, start, last_access (datetime)."""
        ...

    def logout_everywhere(self) -> None: ...
    def delete(self) -> None: ...


class ManagedAccount(AccountAdmin, Protocol):
    """Lo que un administrador puede hacer sobre la cuenta de OTRO usuario."""

    def representation(self) -> dict:
        """Ficha exportable: username, email, firstName, lastName, emailVerified, enabled, roles."""
        ...

    def set_enabled(self, enabled: bool) -> None: ...
    def set_role(self, role: str, app_roles: tuple[str, ...]) -> None:
        """Deja `role` como único rol de la app (de `app_roles`) asignado directamente."""
        ...

    def send_actions_email(self, actions: list[str], *, lifespan_seconds: int = 3 * 24 * 3600) -> None:
        """Envía el correo del proveedor para completar `actions` (cambiar contraseña, verificar...)."""
        ...


class UserDirectory(Protocol):
    """Todas las cuentas del proveedor de identidad (solo para administradores)."""

    def account(self, user_id: str) -> ManagedAccount: ...
    def statuses(self) -> dict[str, dict]:
        """Por id: enabled, email_verified, otp (bool), created (datetime | None)."""
        ...

    def find_by_email(self, email: str) -> str | None:
        """Id de la cuenta con ese correo, o None."""
        ...

    def create(self, *, email: str, first_name: str, last_name: str, role: str, email_verified: bool = False) -> str:
        """Crea la cuenta (sin contraseña) con el rol indicado y devuelve su id."""
        ...


class AccountActions(Protocol):
    def url(self, action: str, return_path: str) -> str:
        """URL que abre la acción en el proveedor y vuelve a `return_path` de la app."""
        ...


class Reauthenticator(Protocol):
    """Vuelve a pedir el inicio de sesión completo (contraseña + 2FA si lo tiene)
    para confirmar una acción sensible, y verifica el resultado en el servidor."""

    def start_url(self, *, state: str, nonce: str, login_hint: str | None, return_path: str) -> str: ...

    def verify(self, *, code: str, nonce: str, return_path: str) -> dict:
        """Canjea el `code` devuelto y devuelve los claims del ID token ya validado
        (firma, emisor, audiencia y nonce). Lanza IdentityError si algo no cuadra."""
        ...
