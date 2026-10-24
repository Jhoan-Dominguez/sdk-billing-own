"""Proveedor de identidad (hoy Keycloak): cuenta del usuario autenticado."""

from datetime import datetime
from typing import Protocol

# Acciones que el usuario completa en las pantallas del proveedor de identidad
# (la app nunca ve contraseñas ni secretos de 2FA).
ACTION_UPDATE_PASSWORD = "UPDATE_PASSWORD"
ACTION_CONFIGURE_TOTP = "CONFIGURE_TOTP"


class IdentityError(RuntimeError):
    pass


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
