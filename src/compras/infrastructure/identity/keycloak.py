"""Keycloak como proveedor de identidad.

- KeycloakActions: URLs de "application initiated actions" (cambiar contraseña,
  activar 2FA) que se completan en las páginas de Keycloak (tema `compras`); la app
  nunca ve contraseñas ni secretos TOTP. Keycloak vuelve con
  `?kc_action_status=success|cancelled|error`.
- KeycloakAccountAdmin: API de administración con la cuenta de servicio
  `compras-admin-api` (roles view-users/manage-users del realm). Puede tocar a
  cualquier usuario del realm, así que bootstrap solo la crea para el usuario
  autenticado.
"""

import time
from datetime import datetime
from urllib.parse import urlencode

import httpx

from compras.domain.ports.identity import IdentityError


def from_millis(ms: int | None) -> datetime | None:
    return datetime.fromtimestamp(ms / 1000) if ms else None


class KeycloakActions:
    def __init__(self, public_url: str, realm: str, client_id: str, app_url: str) -> None:
        self._auth_url = f"{public_url}/realms/{realm}/protocol/openid-connect/auth"
        self._client_id = client_id
        self._app_url = app_url

    def url(self, action: str, return_path: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": f"{self._app_url}{return_path}",
                "response_type": "code",
                "scope": "openid",
                "kc_action": action,
            }
        )
        return f"{self._auth_url}?{query}"


class ServiceAccountToken:
    """Token de la cuenta de servicio (client credentials), renovado al caducar."""

    def __init__(self, internal_url: str, realm: str, client_id: str, client_secret: str) -> None:
        self._url = f"{internal_url}/realms/{realm}/protocol/openid-connect/token"
        self._client = (client_id, client_secret)
        self._token: str | None = None
        self._expires = 0.0

    def get(self) -> str:
        if self._token and time.monotonic() < self._expires:
            return self._token
        client_id, secret = self._client
        try:
            response = httpx.post(
                self._url,
                data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret},
                timeout=10,
            )
        except httpx.HTTPError as e:
            raise IdentityError(f"No se pudo contactar con Keycloak: {e}") from e
        if response.status_code != 200:
            raise IdentityError(f"Keycloak rechazó la cuenta de servicio ({response.status_code}).")
        data = response.json()
        self._token = data["access_token"]
        self._expires = time.monotonic() + data.get("expires_in", 60) - 10
        return self._token


class KeycloakAccountAdmin:
    """AccountAdmin para un usuario concreto."""

    def __init__(self, token: ServiceAccountToken, internal_url: str, realm: str, user_id: str) -> None:
        self._token = token
        self._user_url = f"{internal_url}/admin/realms/{realm}/users/{user_id}"

    def _request(self, method: str, path: str = "", **kwargs) -> httpx.Response:
        try:
            response = httpx.request(
                method,
                self._user_url + path,
                headers={"Authorization": f"Bearer {self._token.get()}"},
                timeout=10,
                **kwargs,
            )
        except httpx.HTTPError as e:
            raise IdentityError(f"No se pudo contactar con Keycloak: {e}") from e
        if response.status_code >= 400:
            detail = response.json().get("errorMessage", "") if response.content else ""
            raise IdentityError(f"Keycloak respondió {response.status_code}. {detail}".strip())
        return response

    def _raw_user(self) -> dict:
        return self._request("GET").json()

    def _credentials(self) -> list[dict]:
        return self._request("GET", "/credentials").json()

    def profile(self) -> dict:
        user = self._raw_user()
        return {
            "username": user.get("username"),
            "email": user.get("email"),
            "firstName": user.get("firstName", ""),
            "lastName": user.get("lastName", ""),
            "created": from_millis(user.get("createdTimestamp")),
        }

    def update_names(self, first_name: str, last_name: str) -> None:
        # PUT reemplaza lo enviado; se reenvían email y username para que la validación
        # del perfil de usuario (campos obligatorios) no falle.
        current = self._raw_user()
        self._request(
            "PUT",
            json={
                "username": current["username"],
                "email": current.get("email"),
                "firstName": first_name,
                "lastName": last_name,
            },
        )

    def linked_providers(self) -> list[str]:
        return [i["identityProvider"] for i in self._request("GET", "/federated-identity").json()]

    def has_password(self) -> bool:
        return any(c["type"] == "password" for c in self._credentials())

    def otp_enabled_since(self) -> datetime | None | bool:
        otp = [c for c in self._credentials() if c["type"] == "otp"]
        return from_millis(otp[0].get("createdDate")) if otp else False

    def remove_otp(self) -> None:
        for credential in self._credentials():
            if credential["type"] == "otp":
                self._request("DELETE", f"/credentials/{credential['id']}")

    def sessions(self) -> list[dict]:
        return [
            {
                "ip": s.get("ipAddress"),
                "start": from_millis(s.get("start")),
                "last_access": from_millis(s.get("lastAccess")),
            }
            for s in self._request("GET", "/sessions").json()
        ]

    def logout_everywhere(self) -> None:
        self._request("POST", "/logout")

    def delete(self) -> None:
        self._request("DELETE")
