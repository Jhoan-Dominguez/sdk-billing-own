"""Roles y permisos de la app.

La identidad la gestiona Keycloak (OIDC) a través de `st.login`; los roles llegan en
el claim `roles` del ID token (mapper "realm roles" del cliente `billing-app`). Aquí
solo se decide qué puede hacer cada rol, sin depender de Streamlit para poder probarlo.
"""

from collections.abc import Mapping
from dataclasses import dataclass

ADMIN = "admin"
CLIENTE = "cliente"

# Orden de prioridad: si un usuario tiene varios roles, gana el primero.
ROLES = (ADMIN, CLIENTE)

ROLE_LABELS = {ADMIN: "Administrador", CLIENTE: "Cliente"}

# Páginas visibles por rol (presentation/streamlit/pages/).
PAGES_BY_ROLE: dict[str, tuple[str, ...]] = {
    ADMIN: ("resumen", "tabla_resumen", "importar", "comparativa", "configuracion"),
    CLIENTE: ("resumen", "tabla_resumen", "importar", "configuracion"),
}

# Roles que pueden ver los datos de todos los usuarios (análisis y comparativas).
# El resto solo ve lo que es suyo.
SEES_ALL_ROLES = frozenset({ADMIN})

# Roles que gestionan las categorías generales (las de todos los usuarios).
MANAGES_GLOBAL_CATEGORIES_ROLES = frozenset({ADMIN})

# Roles que no pueden eliminar su propia cuenta desde la app (evita quedarse sin admin).
CANNOT_SELF_DELETE_ROLES = frozenset({ADMIN})

# Roles que eligen el proveedor y el modelo LLM de los agentes (afecta a todos).
MANAGES_AGENTS_ROLES = frozenset({ADMIN})

# Las acciones sensibles de la cuenta (contraseña, 2FA, eliminarla) exigen confirmar
# por correo y, si hay 2FA, el código: ver domain/security.py.


@dataclass(frozen=True)
class Viewer:
    """El usuario que está usando la app; decide qué datos puede ver y modificar."""

    user_id: str  # claim `sub` de Keycloak (= users.id)
    role: str
    name: str

    @property
    def sees_all(self) -> bool:
        return self.role in SEES_ALL_ROLES

    def owner_filter(self, selected: str | None = None) -> str | None:
        """`owner_id` con el que filtrar consultas; None = sin filtro (todos).

        `selected` es el cliente que eligió un administrador (None = todos). Para el
        resto de roles se ignora: siempre quedan limitados a sus propios datos.
        """
        return selected if self.sees_all else self.user_id

    def can_modify(self, owner_id: str) -> bool:
        # Ver datos ajenos no implica poder cambiarlos: solo el dueño edita o borra.
        return owner_id == self.user_id

    @property
    def manages_global_categories(self) -> bool:
        return self.role in MANAGES_GLOBAL_CATEGORIES_ROLES

    def can_manage_category(self, owner_id: str | None) -> bool:
        """Personales: solo su dueño. Generales (owner_id None): roles autorizados."""
        return self.manages_global_categories if owner_id is None else owner_id == self.user_id

    @property
    def can_delete_own_account(self) -> bool:
        return self.role not in CANNOT_SELF_DELETE_ROLES

    @property
    def manages_agents(self) -> bool:
        return self.role in MANAGES_AGENTS_ROLES


def roles_from_claims(claims: Mapping) -> set[str]:
    """Roles conocidos presentes en los claims del ID token."""
    raw = claims.get("roles") or []
    if isinstance(raw, str):  # un único rol puede llegar como string
        raw = [raw]
    return {r for r in raw if r in ROLES}


def primary_role(claims: Mapping) -> str | None:
    """Rol efectivo del usuario, o None si no tiene ninguno de la app."""
    roles = roles_from_claims(claims)
    return next((r for r in ROLES if r in roles), None)


def can_view(role: str | None, page: str) -> bool:
    return role is not None and page in PAGES_BY_ROLE.get(role, ())


def viewer_from_claims(claims: Mapping) -> Viewer | None:
    """Viewer de un usuario autenticado con rol de la app, o None."""
    role = primary_role(claims)
    if role is None or not claims.get("sub"):
        return None
    return Viewer(user_id=claims["sub"], role=role, name=display_name(claims))


def display_name(claims: Mapping) -> str:
    return claims.get("name") or claims.get("preferred_username") or claims.get("email") or "Usuario"
