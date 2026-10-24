"""Configuración: perfil, seguridad, cuenta, correo bancario, preferencias, categorías
y (administradores) agentes IA.

Todo actúa sobre el usuario autenticado (viewer.user_id); nunca sobre otro. Las
pestañas grandes viven en components/settings/.
"""

import pandas as pd
import streamlit as st

from compras import bootstrap
from compras.application import categories as category_service
from compras.application import users as user_service
from compras.domain.catalog import CURRENCIES, FALLBACK_CATEGORY, PAYMENT_METHODS
from compras.domain.errors import ValidationError
from compras.domain.ports.identity import IdentityError
from compras.presentation.streamlit.components.layout import flash
from compras.presentation.streamlit.components.profile import avatar
from compras.presentation.streamlit.components.session import current_viewer, user_claims
from compras.presentation.streamlit.components.settings import account, agents, mailboxes, security
from compras.presentation.streamlit.components.settings.context import SettingsContext

viewer = current_viewer()
ctx = SettingsContext.load(viewer, user_claims())
kc, kc_user, storage = ctx.kc, ctx.kc_user, ctx.storage
keycloak_unavailable = ctx.keycloak_unavailable

st.title("Configuración")
# Vuelta de los enlaces de confirmación, de la verificación 2FA o de Keycloak.
security.handle_return(ctx)

labels = [
    ":material/person: Perfil",
    ":material/shield_lock: Seguridad",
    ":material/badge: Cuenta",
    ":material/forward_to_inbox: Correo bancario",
    ":material/tune: Preferencias",
    ":material/category: Categorías",
]
if viewer.manages_agents:
    labels.append(":material/smart_toy: Agentes IA")
tabs = st.tabs(labels)
profile_tab, security_tab, account_tab, mailbox_tab, prefs_tab, categories_tab = tabs[:6]

# --- Perfil ---------------------------------------------------------------------

with profile_tab, bootstrap.unit_of_work() as uow:
    user = user_service.get(uow, viewer.user_id)
    left, right = st.columns([1, 2], gap="large")

    with left, st.container(border=True):
        st.subheader("Avatar")
        avatar(user, viewer.name, size=112)
        upload = st.file_uploader(
            "Nueva imagen",
            type=["png", "jpg", "jpeg", "webp"],
            key=f"avatar-{st.session_state.get('avatar_no', 0)}",
        )
        st.caption("PNG, JPG o WEBP de hasta 5 MB. Se recorta en cuadrado.")
        save_col, remove_col = st.columns(2)
        if save_col.button("Guardar", type="primary", disabled=upload is None, width="stretch", key="avatar-save"):
            try:
                user_service.set_avatar(uow, storage, user, upload.getvalue())
            except ValidationError as e:
                st.error(str(e), icon=":material/error:")
            else:
                st.session_state["avatar_no"] = st.session_state.get("avatar_no", 0) + 1
                flash("Avatar actualizado")
                st.rerun()
        if remove_col.button("Quitar", disabled=not user.avatar_name, width="stretch", key="avatar-remove"):
            user_service.remove_avatar(uow, storage, user)
            flash("Avatar eliminado")
            st.rerun()

    with right, st.container(border=True):
        st.subheader("Datos personales")
        if not keycloak_unavailable():
            with st.form("profile", enter_to_submit=False):
                c1, c2 = st.columns(2)
                first = c1.text_input("Nombre", value=kc_user.get("firstName", ""), max_chars=100)
                last = c2.text_input("Apellido", value=kc_user.get("lastName", ""), max_chars=100)
                st.text_input(
                    "Correo electrónico",
                    value=kc_user.get("email", ""),
                    disabled=True,
                    help="El correo es tu usuario de acceso y no se puede cambiar desde aquí.",
                )
                if st.form_submit_button("Guardar cambios", type="primary", icon=":material/save:"):
                    try:
                        user_service.update_profile(uow, kc, user, first, last)
                    except (ValidationError, IdentityError) as e:
                        uow.rollback()
                        st.error(str(e), icon=":material/error:")
                    else:
                        flash("Datos personales actualizados")
                        st.rerun()

# --- Seguridad, cuenta y correo bancario ----------------------------------------

with security_tab:
    security.render(ctx)

with account_tab:
    account.render(ctx)

with mailbox_tab:
    mailboxes.render(ctx)

# --- Preferencias ---------------------------------------------------------------

with prefs_tab, bootstrap.unit_of_work() as uow:
    user = user_service.get(uow, viewer.user_id)
    names = [c.name for c in category_service.visible_to(uow, owner_id=viewer.user_id)]
    with st.container(border=True):
        st.subheader("Valores por defecto")
        st.caption("Se usan al registrar compras nuevas y en los resúmenes.")
        with st.form("preferences", enter_to_submit=False):
            current = user_service.currency(user)
            options = CURRENCIES if current in CURRENCIES else [current, *CURRENCIES]
            c1, c2, c3 = st.columns(3)
            currency = c1.selectbox("Moneda preferida", options, index=options.index(current), accept_new_options=True)
            payment = c2.selectbox(
                "Método de pago",
                PAYMENT_METHODS,
                index=PAYMENT_METHODS.index(user.default_payment_method)
                if user.default_payment_method in PAYMENT_METHODS
                else None,
                placeholder="Sin especificar",
            )
            category = c3.selectbox(
                "Categoría",
                names,
                index=names.index(user.default_category) if user.default_category in names else None,
                placeholder="Sin especificar",
            )
            if st.form_submit_button("Guardar preferencias", type="primary", icon=":material/save:"):
                try:
                    user_service.update_preferences(
                        uow, user, currency=currency, payment_method=payment, category=category
                    )
                except ValidationError as e:
                    uow.rollback()
                    st.error(str(e), icon=":material/error:")
                else:
                    flash("Preferencias guardadas")
                    st.rerun()

# --- Categorías -----------------------------------------------------------------

with categories_tab, bootstrap.unit_of_work() as uow:
    # Un admin elige qué gestiona: las generales (de todos) o las suyas.
    scope_owner: str | None = viewer.user_id
    if viewer.manages_global_categories:
        scope = st.segmented_control(
            "Ámbito",
            ["Generales", "Mis categorías"],
            default="Generales",
            key="category_scope",
            required=True,
            label_visibility="collapsed",
        )
        scope_owner = None if scope == "Generales" else viewer.user_id

    categories = category_service.visible_to(uow, owner_id=viewer.user_id)
    usage = category_service.usage(uow, owner_id=None if scope_owner is None else viewer.user_id)
    manageable = [c for c in categories if c.owner_id == scope_owner and viewer.can_manage_category(c.owner_id)]

    left, right = st.columns([3, 2], gap="large")
    with left, st.container(border=True):
        st.subheader("Categorías disponibles")
        st.caption(
            "Las generales las comparten todos los usuarios"
            + (" (las gestionas tú como administrador)." if viewer.manages_global_categories else ".")
            + " Las personales solo las ves tú."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Categoría": c.name,
                        "Tipo": "General" if c.is_global else "Personal",
                        "Compras": usage.get(c.name, 0),
                    }
                    for c in categories
                ]
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Compras": st.column_config.NumberColumn(
                    help="Compras de todos los usuarios" if scope_owner is None else "Tus compras"
                )
            },
        )

    with right:
        label = "general" if scope_owner is None else "personal"
        with st.container(border=True):
            st.subheader(f"Nueva categoría {label}")
            with st.form("new-category", clear_on_submit=True, enter_to_submit=True):
                name = st.text_input("Nombre", max_chars=50, placeholder="p. ej. Mascotas")
                if st.form_submit_button("Crear", type="primary", icon=":material/add:"):
                    try:
                        category_service.create(uow, name, owner_id=scope_owner)
                    except ValidationError as e:
                        uow.rollback()
                        st.error(str(e), icon=":material/error:")
                    else:
                        flash(f"Categoría «{name.strip()}» creada")
                        st.rerun()

        with st.container(border=True):
            st.subheader("Editar o eliminar")
            editable = [c for c in manageable if not c.is_protected]
            if not editable:
                st.caption(f"No tienes categorías {label}es que editar.")
            else:
                chosen = st.selectbox(
                    "Categoría",
                    [c.id for c in editable],
                    format_func=lambda cid: next(c.name for c in editable if c.id == cid),
                    key=f"category-pick-{label}",
                )
                target = category_service.get(uow, chosen)
                new_name = st.text_input("Nuevo nombre", value=target.name, max_chars=50, key=f"rename-{chosen}")
                c1, c2 = st.columns(2)
                if c1.button("Renombrar", icon=":material/edit:", width="stretch", key="rename-category"):
                    try:
                        old = target.name
                        moved = category_service.rename(uow, target, new_name)
                    except ValidationError as e:
                        uow.rollback()
                        st.error(str(e), icon=":material/error:")
                    else:
                        flash(f"«{old}» ahora es «{target.name}» ({moved} compras actualizadas)")
                        st.rerun()
                with c2.popover("Eliminar", icon=":material/delete:", width="stretch"):
                    st.write(f"Las compras con «{target.name}» pasarán a «{FALLBACK_CATEGORY}».")
                    if st.button("Sí, eliminar", key="confirm-delete-category"):
                        old = target.name
                        moved = category_service.delete(uow, target)
                        flash(f"Categoría «{old}» eliminada ({moved} compras movidas a {FALLBACK_CATEGORY})")
                        st.rerun()

# --- Agentes IA (administradores) -----------------------------------------------

if viewer.manages_agents:
    with tabs[6]:
        agents.render(ctx)
