"""Utilidades de las páginas de administración."""

from datetime import datetime

import streamlit as st

from billing import bootstrap
from billing.domain.auth import Viewer
from billing.domain.errors import PermissionDenied, ValidationError
from billing.domain.ports.identity import IdentityError, UserDirectory
from billing.presentation.streamlit.components.session import current_viewer

# Errores de una acción de administración que se muestran tal cual.
ACTION_ERRORS = (IdentityError, PermissionDenied, ValidationError)


def require_manager() -> Viewer:
    """Viewer con `manages_users`; cualquier otro se detiene (la navegación ya lo oculta)."""
    viewer = current_viewer()
    if not viewer.manages_users:
        st.error("No tienes permiso para ver esta página.", icon=":material/block:")
        st.stop()
    return viewer


def user_directory() -> UserDirectory | None:
    directory = bootstrap.user_directory()
    if directory is None:
        st.warning(
            "La gestión de cuentas no está configurada (falta KEYCLOAK_ADMIN_API_SECRET).", icon=":material/cloud_off:"
        )
    return directory


@st.cache_data(ttl=30, show_spinner=False)
def identity_statuses() -> tuple[dict[str, dict], str | None]:
    """Estado de todas las cuentas en el proveedor (30 s de caché; ver `refresh_statuses`)."""
    directory = bootstrap.user_directory()
    if directory is None:
        return {}, None
    try:
        return directory.statuses(), None
    except IdentityError as e:
        return {}, str(e)


def refresh_statuses() -> None:
    identity_statuses.clear()


def human_bytes(size: int | None) -> str:
    size = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:,.0f} {unit}" if unit == "B" else f"{size:,.1f} {unit}"
        size /= 1024
    return f"{size:,.1f} GB"


def when(value: datetime | None, *, with_time: bool = True) -> str:
    if value is None:
        return "—"
    return f"{value:%d/%m/%Y %H:%M}" if with_time else f"{value:%d/%m/%Y}"
