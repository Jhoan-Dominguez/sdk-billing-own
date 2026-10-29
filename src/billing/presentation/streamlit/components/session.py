"""Sesión del usuario en Streamlit: login (Keycloak vía st.login), Viewer y esquema."""

import streamlit as st

from billing import bootstrap
from billing.domain.auth import Viewer


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


def logout() -> None:
    """Cierra la sesión: borra el estado de Streamlit (el `viewer`, filtros...) además de la cookie.

    `st.logout` solo limpia `st.user`; si el estado siguiera vivo, una sesión de Streamlit
    reutilizada (p. ej. al volver atrás en el navegador) conservaría los datos del usuario.
    """
    st.session_state.clear()
    st.logout()


# El navegador puede restaurar la página desde su caché de atrás/adelante (bfcache) con la
# interfaz de antes de cerrar sesión. Al detectarlo se recarga, y app.py vuelve a validar la
# sesión contra la cookie (que ya no existe) y redirige al login.
_RELOAD_ON_BACK_CACHE = """<script>
if (!window.__billingPageshow) {
  window.__billingPageshow = true;
  window.addEventListener("pageshow", (event) => { if (event.persisted) window.location.reload(); });
}
</script>"""


def reload_on_back_cache() -> None:
    st.html(_RELOAD_ON_BACK_CACHE, width="content", unsafe_allow_javascript=True)


def login_screen() -> None:
    """Sin sesión: redirige a la pantalla de login (tema `billing` de Keycloak).

    El formulario de correo/contraseña, Google y "Crear cuenta" viven en Keycloak
    (infra/docker/keycloak/themes/billing): la app nunca recibe contraseñas.
    """
    st.session_state.clear()  # nada de una sesión anterior sobrevive sin login
    if not auth_configured():
        st.error(
            "La autenticación no está configurada. Genera `.streamlit/secrets.toml` con "
            "`python scripts/write_secrets.py` (ver README.md).",
            icon=":material/key_off:",
        )
        return
    st.caption(":material/progress_activity: Redirigiendo al inicio de sesión…")
    start_login()
