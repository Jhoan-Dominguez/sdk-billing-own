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

    def remove_otp(self) -> None: ...
    def sessions(self) -> list[dict]:
        """Sesiones abiertas: ip, start, last_access (datetime)."""
        ...

    def logout_everywhere(self) -> None: ...
    def delete(self) -> None: ...


class AccountActions(Protocol):
    def url(self, action: str, return_path: str) -> str:
        """URL que abre la acción en el proveedor y vuelve a `return_path` de la app."""
        ...
