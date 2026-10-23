"""Configuración: perfil, seguridad, cuenta, preferencias y categorías.

Todo actúa sobre el usuario autenticado (viewer.user_id); nunca sobre otro.
"""

import time

import pandas as pd
import streamlit as st

from compras import bootstrap
from compras.application import categories as category_service
from compras.application import users as user_service
from compras.domain import auth
from compras.domain.catalog import CURRENCIES, FALLBACK_CATEGORY, PAYMENT_METHODS
from compras.domain.errors import ValidationError
from compras.domain.ports.identity import ACTION_CONFIGURE_TOTP, ACTION_UPDATE_PASSWORD, IdentityError
from compras.presentation.streamlit.components.layout import flash
from compras.presentation.streamlit.components.profile import avatar
from compras.presentation.streamlit.components.session import current_viewer, user_claims

RETURN_PATH = "/configuracion"  # Keycloak vuelve aquí tras las acciones de la cuenta

viewer = current_viewer()
claims = user_claims()

st.title("Configuración")

# Vuelta desde una acción de Keycloak (cambiar contraseña, activar 2FA).
ACTION_MESSAGES = {
    ACTION_UPDATE_PASSWORD: "Contraseña actualizada",
    ACTION_CONFIGURE_TOTP: "Verificación en dos pasos activada",
}
if status := st.query_params.get("kc_action_status"):
    action = st.query_params.get("kc_action", "")
    if status == "success":
        st.toast(ACTION_MESSAGES.get(action, "Cambios guardados"), icon=":material/check_circle:")
    elif status == "cancelled":
        st.toast("Acción cancelada", icon=":material/info:")
    else:
        st.toast("Keycloak no pudo completar la acción", icon=":material/error:")
    st.query_params.clear()  # quita también el `code` que añade Keycloak a la URL

kc = bootstrap.account_admin(viewer.user_id)
actions = bootstrap.account_actions()
storage = bootstrap.file_storage()
kc_user: dict = {}
kc_error = None if kc else "La gestión de la cuenta no está configurada (falta KEYCLOAK_ADMIN_API_SECRET)."
if kc:
    try:
        kc_user = kc.profile()
    except IdentityError as e:
        kc_error = str(e)


def keycloak_unavailable() -> bool:
    if kc_error:
        st.warning(kc_error, icon=":material/cloud_off:")
    return kc_error is not None


def needs_recent_login(action: str) -> bool:
    """Para acciones sensibles: pide volver a iniciar sesión si el login no es reciente."""
    if auth.recently_authenticated(claims, time.time()):
        return False
    minutes = auth.RECENT_AUTH_SECONDS // 60
    st.info(
        f"Por seguridad, para {action} debes haber iniciado sesión en los últimos {minutes} minutos.",
        icon=":material/lock_clock:",
    )
    st.button("Volver a iniciar sesión", on_click=st.logout, icon=":material/login:", key=f"relogin-{action}")
    return True


profile_tab, security_tab, account_tab, prefs_tab, categories_tab = st.tabs(
    [
        ":material/person: Perfil",
        ":material/shield_lock: Seguridad",
        ":material/badge: Cuenta",
        ":material/tune: Preferencias",
        ":material/category: Categorías",
    ]
)

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

# --- Seguridad ------------------------------------------------------------------


def load_security() -> tuple | None:
    try:
        return kc.has_password(), kc.otp_enabled_since(), kc.sessions()
    except IdentityError as e:
        st.error(str(e), icon=":material/error:")
        return None


with security_tab:
    if not keycloak_unavailable() and (security := load_security()):
        has_password, otp_since, sessions = security

        with st.container(border=True):
            st.subheader("Contraseña")
            st.write(
                "Se cambia en la pantalla segura de inicio de sesión; la aplicación nunca ve tu contraseña."
                if has_password
                else "Tu cuenta entra con un proveedor externo. Puedes crear también una contraseña."
            )
            st.link_button(
                "Cambiar contraseña" if has_password else "Crear contraseña",
                actions.url(ACTION_UPDATE_PASSWORD, RETURN_PATH),
                icon=":material/password:",
            )

        with st.container(border=True):
            st.subheader("Verificación en dos pasos (2FA)")
            if otp_since is not False:
                created = otp_since
                st.success(
                    "Activada con una app de autenticación" + (f" desde el {created:%d/%m/%Y}." if created else "."),
                    icon=":material/verified_user:",
                )
                with st.popover("Desactivar 2FA", icon=":material/remove_moderator:"):
                    if not needs_recent_login("desactivar la verificación en dos pasos"):
                        st.write("Tu cuenta quedará protegida solo con la contraseña.")
                        if st.button("Sí, desactivar", key="confirm-delete-otp"):
                            try:
                                kc.remove_otp()
                            except IdentityError as e:
                                st.error(str(e), icon=":material/error:")
                            else:
                                flash("Verificación en dos pasos desactivada")
                                st.rerun()
            else:
                st.write(
                    "Añade un código temporal de una app como Google Authenticator, Microsoft "
                    "Authenticator o FreeOTP al iniciar sesión."
                )
                st.link_button(
                    "Activar 2FA",
                    actions.url(ACTION_CONFIGURE_TOTP, RETURN_PATH),
                    type="primary",
                    icon=":material/phonelink_lock:",
                )

        with st.container(border=True):
            st.subheader("Sesiones abiertas")
            if sessions:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Dirección IP": s["ip"],
                                "Inicio": s["start"],
                                "Última actividad": s["last_access"],
                            }
                            for s in sessions
                        ]
                    ),
                    hide_index=True,
                    column_config={
                        "Inicio": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                        "Última actividad": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                    },
                )
            else:
                st.caption("No hay sesiones abiertas en el servidor de identidad.")
            if st.button("Cerrar sesión en todos los dispositivos", icon=":material/devices_off:"):
                try:
                    kc.logout_everywhere()
                except IdentityError as e:
                    st.error(str(e), icon=":material/error:")
                else:
                    st.logout()

# --- Cuenta ---------------------------------------------------------------------

with account_tab, bootstrap.unit_of_work() as uow:
    user = user_service.get(uow, viewer.user_id)
    usage = category_service.usage(uow, owner_id=viewer.user_id)
    with st.container(border=True):
        st.subheader("Información de la cuenta")
        providers = []
        if kc and not kc_error:
            try:
                providers = kc.linked_providers()
            except IdentityError:
                providers = []
        created = kc_user.get("created") or user.created_at
        info = {
            "Correo electrónico": user.email or "—",
            "Rol": auth.ROLE_LABELS.get(viewer.role, viewer.role),
            "Cuenta creada": f"{created:%d/%m/%Y}" if created else "—",
            "Último inicio de sesión": f"{user.last_login_at:%d/%m/%Y %H:%M}",
            "Acceso con": ", ".join(["Correo y contraseña", *[p.capitalize() for p in providers]]),
            "Compras registradas": f"{sum(usage.values()):,}",
            "ID de usuario": f"`{user.id}`",
        }
        st.markdown("\n".join(f"- **{label}:** {value}" for label, value in info.items()))

    with st.container(border=True):
        st.subheader(":red[Eliminar cuenta]")
        if not viewer.can_delete_own_account:
            st.caption(
                "Las cuentas de administrador no se pueden eliminar desde aquí; pide a otro "
                "administrador que lo haga desde la consola de Keycloak."
            )
        else:
            st.write(
                "Se borrarán de forma permanente tu cuenta, todas tus compras, archivos adjuntos, "
                "avatar y categorías personales. Esta acción no se puede deshacer."
            )
            with st.popover("Eliminar mi cuenta", icon=":material/delete_forever:"):
                if not keycloak_unavailable() and not needs_recent_login("eliminar tu cuenta"):
                    typed = st.text_input(f"Escribe tu correo ({user.email}) para confirmar")
                    confirmed = typed.strip().lower() == (user.email or "").lower() and bool(user.email)
                    if st.button("Eliminar definitivamente", key="confirm-delete-account", disabled=not confirmed):
                        try:
                            user_service.delete_account(uow, storage, kc, user)
                        except IdentityError as e:
                            st.error(str(e), icon=":material/error:")
                        else:
                            st.logout()

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
