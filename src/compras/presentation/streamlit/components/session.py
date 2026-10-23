"""Sesión del usuario en Streamlit: login (Keycloak vía st.login), Viewer y esquema."""

import streamlit as st

from compras import bootstrap
from compras.domain.auth import Viewer


@st.cache_resource
def ensure_database() -> bool:
    """Aplica las migraciones una vez por proceso."""
    bootstrap.init_database()
    return True


def user_claims() -> dict:
    """Claims del ID token del usuario (`is_logged_in`, `roles`, `name`, `auth_time`...)."""
    return st.user.to_dict()


def current_viewer() -> Viewer:
    """Usuario de la sesión; lo fija app.py tras validar el login.

    Si una página se ejecuta sin pasar por la entrada (sin Viewer), se detiene: nunca
    se muestran datos sin saber de quién son.
    """
    viewer = st.session_state.get("viewer")
    if not isinstance(viewer, Viewer):
        st.error("Sesión no válida. Vuelve a iniciar sesión.", icon=":material/lock:")
        st.stop()
    return viewer


def auth_configured() -> bool:
    try:
        return "auth" in st.secrets
    except FileNotFoundError:  # sin secrets.toml
        return False


def start_login() -> None:
    st.login("keycloak")


def login_screen() -> None:
    """Sin sesión: redirige a la pantalla de login (tema `compras` de Keycloak).

    El formulario de correo/contraseña, Google y "Crear cuenta" viven en Keycloak
    (infra/docker/keycloak/themes/compras): la app nunca recibe contraseñas.
    """
    if not auth_configured():
        st.error(
            "La autenticación no está configurada. Genera `.streamlit/secrets.toml` con "
            "`python scripts/write_secrets.py` (ver README.md).",
            icon=":material/key_off:",
        )
        return
    st.caption(":material/progress_activity: Redirigiendo al inicio de sesión…")
    start_login()
