"""Entrada de la app web: login, registro del usuario, navegación por rol y barra lateral.

Se arranca con `python -m compras` (o `streamlit run` sobre este archivo).
"""

from pathlib import Path

import streamlit as st

from compras import bootstrap
from compras.application import imports
from compras.application import users as user_service
from compras.application.agents.registry import INVOICE
from compras.domain import auth
from compras.presentation.streamlit.components.layout import apply_styles, show_flash
from compras.presentation.streamlit.components.profile import avatar, current_user
from compras.presentation.streamlit.components.session import ensure_database, login_screen, user_claims

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
    st.button("Cerrar sesión", on_click=st.logout, icon=":material/logout:")
    st.stop()

ensure_database()
# Registrar/actualizar al usuario una vez por sesión (o si cambia de cuenta).
if st.session_state.get("synced_user") != viewer.user_id:
    with bootstrap.unit_of_work() as uow:
        user_service.sync_from_claims(uow, claims, viewer.role)
    st.session_state["synced_user"] = viewer.user_id
st.session_state["viewer"] = viewer  # las páginas lo leen con session.current_viewer()

# --- Navegación según el rol -------------------------------------------------

with bootstrap.unit_of_work() as uow:
    pending = len(imports.drafts(uow, owner_id=viewer.user_id))


def page(name: str, title: str, icon: str, **kwargs) -> st.Page:
    return st.Page(PAGES_DIR / f"{name}.py", title=title, icon=icon, url_path=name, **kwargs)


pages = {
    "resumen": page("resumen", "Resumen general", ":material/dashboard:", default=True),
    "tabla_resumen": page("tabla_resumen", "Tabla resumen", ":material/table_view:"),
    "importar": page(
        "importar", f"Importar facturas ({pending})" if pending else "Importar facturas", ":material/document_scanner:"
    ),
    "comparativa": page("comparativa", "Comparativa de clientes", ":material/groups:"),
    "configuracion": page("configuracion", "Configuración", ":material/settings:"),
}
current_page = st.navigation([p for name, p in pages.items() if auth.can_view(viewer.role, name)])

with st.sidebar:
    user = current_user(viewer)
    pic, who = st.columns([1, 3], vertical_alignment="center")
    with pic:
        avatar(user, viewer.name)
    who.markdown(f"**{user.display_name if user else viewer.name}**  \n:green-badge[{auth.ROLE_LABELS[viewer.role]}]")
    st.button("Cerrar sesión", on_click=st.logout, icon=":material/logout:", width="stretch")
    st.divider()
    provider, model, _ = bootstrap.agent_choice(INVOICE)
    st.caption(f"Lector de facturas: **{provider}**" + (f" · `{model}`" if model else " · solo reglas locales"))

show_flash()
current_page.run()
