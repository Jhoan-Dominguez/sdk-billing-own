"""Entrada de la app web: login, registro del usuario, navegación por rol y barra lateral.

Se arranca con `python -m billing` (o `streamlit run` sobre este archivo).
"""

from pathlib import Path

import streamlit as st

from billing import bootstrap
from billing.application import imports
from billing.application import users as user_service
from billing.application.agents.registry import INVOICE
from billing.domain import auth
from billing.presentation.streamlit.components.layout import apply_styles, show_flash
from billing.presentation.streamlit.components.profile import avatar, current_user
from billing.presentation.streamlit.components.session import (
    ensure_database,
    login_screen,
    logout,
    reload_on_back_cache,
    user_claims,
)

PAGES_DIR = Path(__file__).resolve().parent / "pages"

st.set_page_config(page_title="Registro de compras", page_icon=":material/receipt_long:", layout="wide")
apply_styles()

# --- Autenticación (Keycloak vía OIDC) ---------------------------------------

claims = user_claims()
if not claims.get("is_logged_in"):
    login_screen()
    st.stop()

viewer = auth.viewer_from_claims(claims)
if viewer is None:
    st.error(
        "Tu usuario no tiene un rol asignado en esta aplicación. Pide a un administrador que te asigne "
        f"uno de: {', '.join(auth.ROLES)}.",
        icon=":material/block:",
    )
    st.button("Cerrar sesión", on_click=logout, icon=":material/logout:")
    st.stop()

ensure_database()
# Registrar/actualizar al usuario una vez por sesión (o si cambia de cuenta).
if st.session_state.get("synced_user") != viewer.user_id:
    with bootstrap.unit_of_work() as uow:
        user_service.sync_from_claims(uow, claims, viewer.role)
    st.session_state["synced_user"] = viewer.user_id
st.session_state["viewer"] = viewer  # las páginas lo leen con session.current_viewer()

user = current_user(viewer)
if user is not None and user.is_disabled:
    # Bloqueada por un administrador: Keycloak ya no deja iniciar sesión, pero una sesión
    # abierta de Streamlit seguiría viva hasta aquí.
    st.error("Tu cuenta está bloqueada. Contacta con un administrador.", icon=":material/block:")
    st.button("Cerrar sesión", on_click=logout, icon=":material/logout:")
    st.stop()

# --- Navegación según el rol -------------------------------------------------

pending = 0
if auth.can_view(viewer.role, "imports"):
    with bootstrap.unit_of_work() as uow:
        pending = len(imports.drafts(uow, owner_id=viewer.user_id))

# Archivo en pages/ -> (URL en español, título, icono).
PAGE_SPECS = {
    "summary": ("resumen", "Resumen general", ":material/dashboard:"),
    "summary_table": ("tabla_resumen", "Tabla resumen", ":material/table_view:"),
    "imports": (
        "importar",
        f"Importar facturas ({pending})" if pending else "Importar facturas",
        ":material/document_scanner:",
    ),
    "users": ("usuarios", "Usuarios", ":material/manage_accounts:"),
    "ml_models": ("modelos", "Modelos de predicción", ":material/model_training:"),
    "system": ("sistema", "Estado del sistema", ":material/monitor_heart:"),
    "audit": ("auditoria", "Auditoría", ":material/history:"),
    "data_model": ("modelo-de-datos", "Modelo de datos", ":material/schema:"),
    "settings": ("configuracion", "Configuración", ":material/settings:"),
}
ADMIN_SECTION = ("users", "ml_models", "system", "audit", "data_model")

visible = [name for name in PAGE_SPECS if auth.can_view(viewer.role, name)]
pages = {
    name: st.Page(
        PAGES_DIR / f"{name}.py",
        url_path=PAGE_SPECS[name][0],
        title=PAGE_SPECS[name][1],
        icon=PAGE_SPECS[name][2],
        default=name == visible[0],  # la primera página del rol es la de inicio
    )
    for name in visible
}
admin_pages = [page for name, page in pages.items() if name in ADMIN_SECTION]
if admin_pages:
    others = [page for name, page in pages.items() if name not in ADMIN_SECTION]
    current_page = st.navigation({"Administración": admin_pages, "Cuenta": others})
else:
    current_page = st.navigation(list(pages.values()))

with st.sidebar:
    pic, who = st.columns([1, 3], vertical_alignment="center")
    with pic:
        avatar(user, viewer.name)
    who.markdown(f"**{user.display_name if user else viewer.name}**  \n:green-badge[{auth.ROLE_LABELS[viewer.role]}]")
    st.button("Cerrar sesión", on_click=logout, icon=":material/logout:", width="stretch")
    st.divider()
    provider, model, _ = bootstrap.agent_choice(INVOICE)
    st.caption(f"Lector de facturas: **{provider}**" + (f" · `{model}`" if model else " · solo reglas locales"))
    reload_on_back_cache()  # al final de la barra lateral: su bloque vacío no se nota

show_flash()
current_page.run()
