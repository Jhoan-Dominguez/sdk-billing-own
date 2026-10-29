"""Keycloak como proveedor de identidad.

- KeycloakActions: URLs de "application initiated actions" (cambiar contraseña,
  activar 2FA) que se completan en las páginas de Keycloak (tema `billing`); la app
  nunca ve contraseñas ni secretos TOTP. Keycloak vuelve con
  `?kc_action_status=success|cancelled|error`.
- KeycloakAccountAdmin: API de administración con la cuenta de servicio
  `billing-admin-api` (roles view-users/manage-users del realm). Puede tocar a
  cualquier usuario del realm, así que bootstrap solo la crea para el usuario
  autenticado.
- KeycloakUserDirectory / KeycloakManagedAccount: lo mismo para los administradores
  (bloquear, cambiar rol, invitar...). bootstrap.user_directory() solo se usa en las
  páginas que exigen `viewer.manages_users`.
- KeycloakReauthenticator: reautenticación para acciones sensibles
  (`prompt=login`, `max_age=0`): Keycloak vuelve a pedir contraseña y, si el usuario
  lo tiene, el código 2FA. La app canjea el `code` con el secreto del cliente y
  valida el ID token (firma con el JWKS del realm, emisor, audiencia, nonce); el
  claim `amr` (mapper "amr" del cliente) dice si se usó el 2FA.
"""

import contextlib
import time
from datetime import datetime
from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from billing.domain.ports.identity import IdentityError, IdentityNotFound, ManagedAccount


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


def admin_request(token: ServiceAccountToken, method: str, url: str, **kwargs) -> httpx.Response:
    """Llamada a la API de administración; los errores se convierten en IdentityError."""
    try:
        response = httpx.request(method, url, headers={"Authorization": f"Bearer {token.get()}"}, timeout=10, **kwargs)
    except httpx.HTTPError as e:
        raise IdentityError(f"No se pudo contactar con Keycloak: {e}") from e
    if response.status_code >= 400:
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        detail = (body.get("errorMessage") or body.get("error") or "") if isinstance(body, dict) else ""
        error = IdentityNotFound if response.status_code == 404 else IdentityError
        raise error(f"Keycloak respondió {response.status_code}. {detail}".strip())
    return response


class KeycloakAccountAdmin:
    """AccountAdmin para un usuario concreto."""

    def __init__(self, token: ServiceAccountToken, internal_url: str, realm: str, user_id: str) -> None:
        self._token = token
        self._user_url = f"{internal_url}/admin/realms/{realm}/users/{user_id}"

    def _request(self, method: str, path: str = "", **kwargs) -> httpx.Response:
        return admin_request(self._token, method, self._user_url + path, **kwargs)

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

    def remove_otp(self, created_before: datetime | None = None) -> int:
        removed = 0
        for credential in self._credentials():
            if credential["type"] != "otp":
                continue
            created = from_millis(credential.get("createdDate"))
            if created_before is not None and created is not None and created >= created_before:
                continue  # el dispositivo nuevo (cambio de 2FA) se conserva
            self._request("DELETE", f"/credentials/{credential['id']}")
            removed += 1
        return removed

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


class KeycloakManagedAccount(KeycloakAccountAdmin):
    """ManagedAccount: la cuenta de otro usuario vista por un administrador.

    `redirect_uri` es adonde lleva el enlace del correo de acciones al terminar; tiene que
    estar entre las URIs válidas del cliente en el realm.
    """

    def __init__(
        self, token: ServiceAccountToken, internal_url: str, realm: str, user_id: str, client_id: str, redirect_uri: str
    ) -> None:
        super().__init__(token, internal_url, realm, user_id)
        self._client_id = client_id
        self._redirect_uri = redirect_uri

    def delete(self) -> None:
        # Si la cuenta ya no está en Keycloak (borrada desde su consola), el administrador
        # solo tiene que limpiar los datos de la app.
        with contextlib.suppress(IdentityNotFound):
            super().delete()

    def representation(self) -> dict:
        user = self._raw_user()
        roles = self._request("GET", "/role-mappings/realm/composite").json()
        return {
            "username": user.get("username"),
            "email": user.get("email"),
            "firstName": user.get("firstName", ""),
            "lastName": user.get("lastName", ""),
            "emailVerified": bool(user.get("emailVerified")),
            "enabled": bool(user.get("enabled", True)),
            "roles": sorted(r["name"] for r in roles),
        }

    def set_enabled(self, enabled: bool) -> None:
        # Se reenvían username y email: la validación del perfil de usuario los exige.
        current = self._raw_user()
        self._request("PUT", json={"username": current["username"], "email": current.get("email"), "enabled": enabled})

    def set_role(self, role: str, app_roles: tuple[str, ...]) -> None:
        mapped = self._request("GET", "/role-mappings/realm").json()
        stale = [r for r in mapped if r["name"] in app_roles and r["name"] != role]
        if stale:
            self._request("DELETE", "/role-mappings/realm", json=stale)
        if role not in {r["name"] for r in mapped}:
            available = self._request("GET", "/role-mappings/realm/available").json()
            target = next((r for r in available if r["name"] == role), None)
            if target is None:
                raise IdentityError(f"El rol {role!r} no existe en el realm.")
            self._request("POST", "/role-mappings/realm", json=[target])

    def send_actions_email(self, actions: list[str], *, lifespan_seconds: int = 3 * 24 * 3600) -> None:
        self._request(
            "PUT",
            "/execute-actions-email",
            params={"client_id": self._client_id, "redirect_uri": self._redirect_uri, "lifespan": lifespan_seconds},
            json=actions,
        )


class KeycloakUserDirectory:
    """UserDirectory: todas las cuentas del realm."""

    PAGE = 500

    def __init__(self, token: ServiceAccountToken, internal_url: str, realm: str, client_id: str, redirect_uri: str):
        self._token = token
        self._internal_url = internal_url
        self._realm = realm
        self._users_url = f"{internal_url}/admin/realms/{realm}/users"
        self._client_id = client_id
        self._redirect_uri = redirect_uri

    def account(self, user_id: str) -> ManagedAccount:
        return KeycloakManagedAccount(
            self._token, self._internal_url, self._realm, user_id, self._client_id, self._redirect_uri
        )

    def statuses(self) -> dict[str, dict]:
        result: dict[str, dict] = {}
        first = 0
        while True:
            params = {"briefRepresentation": "false", "first": first, "max": self.PAGE}
            page = admin_request(self._token, "GET", self._users_url, params=params).json()
            for user in page:
                result[user["id"]] = {
                    "enabled": bool(user.get("enabled", True)),
                    "email_verified": bool(user.get("emailVerified")),
                    "otp": bool(user.get("totp")),
                    "created": from_millis(user.get("createdTimestamp")),
                }
            if len(page) < self.PAGE:
                return result
            first += self.PAGE

    def find_by_email(self, email: str) -> str | None:
        params = {"email": email, "exact": "true"}
        users = admin_request(self._token, "GET", self._users_url, params=params).json()
        return users[0]["id"] if users else None

    def create(self, *, email: str, first_name: str, last_name: str, role: str, email_verified: bool = False) -> str:
        response = admin_request(
            self._token,
            "POST",
            self._users_url,
            json={
                "username": email,
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
                "enabled": True,
                "emailVerified": email_verified,
            },
        )
        # Keycloak devuelve la URL del usuario creado en Location (…/users/<id>).
        user_id = response.headers.get("Location", "").rstrip("/").rpartition("/")[2]
        if not user_id:
            raise IdentityError("Keycloak no devolvió el id de la cuenta creada.")
        self.account(user_id).set_role(role, (role,))
        return user_id


class KeycloakReauthenticator:
    def __init__(
        self, public_url: str, internal_url: str, realm: str, client_id: str, client_secret: str, app_url: str
    ) -> None:
        self._auth_url = f"{public_url}/realms/{realm}/protocol/openid-connect/auth"
        self._issuer = f"{public_url}/realms/{realm}"
        self._token_url = f"{internal_url}/realms/{realm}/protocol/openid-connect/token"
        self._jwks_url = f"{internal_url}/realms/{realm}/protocol/openid-connect/certs"
        self._client = (client_id, client_secret)
        self._app_url = app_url

    def start_url(self, *, state: str, nonce: str, login_hint: str | None, return_path: str) -> str:
        params = {
            "client_id": self._client[0],
            "redirect_uri": f"{self._app_url}{return_path}",
            "response_type": "code",
            "scope": "openid",
            "state": state,
            "nonce": nonce,
            # Fuerza a pedir de nuevo las credenciales aunque haya sesión SSO.
            "prompt": "login",
            "max_age": "0",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{self._auth_url}?{urlencode(params)}"

    def verify(self, *, code: str, nonce: str, return_path: str) -> dict:
        client_id, secret = self._client
        try:
            response = httpx.post(
                self._token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": f"{self._app_url}{return_path}",
                    "client_id": client_id,
                    "client_secret": secret,
                },
                timeout=10,
            )
            if response.status_code != 200:
                raise IdentityError("Keycloak no aceptó la verificación; vuelve a intentarlo.")
            keys = KeySet.import_key_set(httpx.get(self._jwks_url, timeout=10).json())
        except httpx.HTTPError as e:
            raise IdentityError(f"No se pudo contactar con Keycloak: {e}") from e
        try:
            token = jwt.decode(response.json()["id_token"], keys)
            jwt.JWTClaimsRegistry(
                iss={"essential": True, "value": self._issuer},
                aud={"essential": True, "value": client_id},
                nonce={"essential": True, "value": nonce},
                sub={"essential": True},
            ).validate(token.claims)
        except (JoseError, KeyError, ValueError) as e:
            raise IdentityError(f"El token de verificación no es válido: {e}") from e
        return dict(token.claims)
