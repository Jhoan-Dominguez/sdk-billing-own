"""Usuarios (administradores): cuentas, cifras de uso, acciones de soporte, exportación,
restauración e invitaciones. Nunca muestra el contenido de las compras."""

import pandas as pd
import streamlit as st

from billing import bootstrap
from billing.application.admin import accounts, backup
from billing.domain.auth import ADMIN, CUSTOMER, ROLE_LABELS, ROLES
from billing.presentation.streamlit.components.admin import (
    ACTION_ERRORS,
    human_bytes,
    identity_statuses,
    refresh_statuses,
    require_manager,
    user_directory,
    when,
)
from billing.presentation.streamlit.components.layout import flash

viewer = require_manager()
directory = user_directory()
storage = bootstrap.file_storage()

st.title("Usuarios")


def done(message: str) -> None:
    refresh_statuses()
    st.session_state.pop("user_export", None)
    flash(message)
    st.rerun()


# --- Diálogos -------------------------------------------------------------------


@st.dialog("Invitar usuario")
def invite_dialog() -> None:
    st.caption("Se crea la cuenta y le llega un correo para verificarla y fijar su contraseña.")
    with st.form(f"invite-{st.session_state.get('invite_no', 0)}"):
        email = st.text_input("Correo electrónico")
        first, last = st.columns(2)
        first_name = first.text_input("Nombre")
        last_name = last.text_input("Apellido")
        role = st.selectbox("Rol", ROLES, index=ROLES.index(CUSTOMER), format_func=ROLE_LABELS.get)
        submitted = st.form_submit_button("Enviar invitación", type="primary", icon=":material/send:")
    if submitted:
        try:
            with bootstrap.unit_of_work() as uow:
                accounts.invite(
                    uow, directory, viewer, email=email, first_name=first_name, last_name=last_name, role=role
                )
        except ACTION_ERRORS as e:
            st.error(str(e), icon=":material/error:")
            return
        st.session_state["invite_no"] = st.session_state.get("invite_no", 0) + 1
        done(f"Invitación enviada a {email.strip()}")


@st.dialog("Restaurar desde una exportación", width="large")
def restore_dialog() -> None:
    st.caption(
        "Sube el ZIP que generó **Exportar datos**. Se recrea la cuenta (si ya no existe) con sus compras, "
        "archivos, categorías y buzones; el usuario recibe un correo para fijar su contraseña."
    )
    upload = st.file_uploader(
        "Exportación (.zip)", type=["zip"], key=f"restore-{st.session_state.get('restore_no', 0)}"
    )
    if upload is None:
        return
    raw = upload.getvalue()
    try:
        with bootstrap.unit_of_work() as uow:
            plan = backup.plan_restore(uow, directory, viewer, raw)
    except ACTION_ERRORS as e:
        st.error(str(e), icon=":material/error:")
        return

    manifest, identity = plan.archive.manifest, plan.archive.identity
    name = " ".join(filter(None, [identity.get("firstName"), identity.get("lastName")])) or plan.archive.user_row.get(
        "name"
    )
    st.markdown(
        f"- **Usuario:** {name or '—'} ({plan.archive.email})\n"
        f"- **Rol:** {ROLE_LABELS.get(plan.archive.role, plan.archive.role)}\n"
        f"- **Exportado:** {manifest.get('exported_at', '—').replace('T', ' ')} por {manifest.get('exported_by', '—')}"
    )
    counts = plan.counts
    cols = st.columns(4)
    cols[0].metric("Compras", counts["purchases"])
    cols[1].metric("Archivos", counts["attachments"])
    cols[2].metric("Categorías propias", counts["categories"])
    cols[3].metric("Buzones", counts["mailbox_connections"])
    if manifest.get("missing_files"):
        st.warning(f"{len(manifest['missing_files'])} archivo(s) ya faltaban al exportar.", icon=":material/warning:")
    if plan.blocked_reason:
        st.error(plan.blocked_reason, icon=":material/block:")
        return
    if plan.account_id is None:
        st.info("La cuenta no existe: se creará de nuevo con un id nuevo.", icon=":material/person_add:")
    elif plan.existing_user:
        st.warning(
            "Ya existe una cuenta con ese correo que usa la app: los datos se **sumarán** a los suyos.",
            icon=":material/merge:",
        )
    else:
        st.info("Ya existe una cuenta con ese correo: los datos se cargarán en ella.", icon=":material/link:")
    if st.button("Restaurar", type="primary", icon=":material/settings_backup_restore:"):
        try:
            with bootstrap.unit_of_work() as uow, st.spinner("Restaurando…"):
                result = backup.restore_user(uow, storage, directory, bootstrap.secret_cipher(), viewer, raw)
        except ACTION_ERRORS as e:
            st.error(str(e), icon=":material/error:")
            return
        st.session_state["restore_no"] = st.session_state.get("restore_no", 0) + 1
        warnings = f" Avisos: {' '.join(result.warnings)}" if result.warnings else ""
        done(f"Cuenta {plan.archive.email} restaurada ({result.restored['purchases']} compras).{warnings}")


# --- Resumen ----------------------------------------------------------------------

statuses, identity_error = identity_statuses() if directory else ({}, None)
if identity_error:
    st.warning(f"No se pudo leer el estado de las cuentas en Keycloak: {identity_error}", icon=":material/cloud_off:")

with bootstrap.unit_of_work() as uow:
    rows = accounts.overview(uow, viewer, statuses if directory and not identity_error else None)

customers = [r for r in rows if r.user.role == CUSTOMER]
k1, k2, k3, k4 = st.columns(4)
k1.metric("Clientes", len(customers))
k2.metric("Administradores", sum(1 for r in rows if r.user.role == ADMIN))
k3.metric("Bloqueadas", sum(1 for r in rows if r.blocked))
k4.metric("Con 2FA", sum(1 for r in rows if r.identity.get("otp")))

search, role_col, state_col, invite_col, restore_col = st.columns([2, 1, 1, 1, 1], vertical_alignment="bottom")
query = search.text_input("Buscar", placeholder="Nombre o correo", label_visibility="collapsed")
role_filter = role_col.selectbox(
    "Rol",
    [None, *ROLES],
    format_func=lambda r: "Todos los roles" if r is None else ROLE_LABELS[r],
    label_visibility="collapsed",
)
state_filter = state_col.selectbox(
    "Estado",
    ["all", "active", "blocked"],
    format_func={"all": "Todos", "active": "Activas", "blocked": "Bloqueadas"}.get,
    label_visibility="collapsed",
)
if invite_col.button("Invitar", icon=":material/person_add:", width="stretch", disabled=directory is None):
    invite_dialog()
if restore_col.button("Restaurar", icon=":material/upload_file:", width="stretch", disabled=directory is None):
    restore_dialog()

needle = query.strip().lower()
shown = [
    r
    for r in rows
    if (not needle or needle in (r.user.display_name or "").lower() or needle in (r.user.email or "").lower())
    and (role_filter is None or r.user.role == role_filter)
    and (state_filter == "all" or (state_filter == "blocked") == r.blocked)
]


def state_label(row: accounts.AccountRow) -> str:
    if row.identity_missing:
        return "Sin cuenta en Keycloak"
    if row.blocked:
        return "Bloqueada"
    if row.identity and not row.identity.get("email_verified"):
        return "Sin verificar"
    return "Activa"


df = pd.DataFrame(
    [
        {
            "id": r.user.id,
            "Nombre": r.user.display_name,
            "Correo": r.user.email,
            "Rol": ROLE_LABELS.get(r.user.role, r.user.role),
            "Estado": state_label(r),
            "2FA": bool(r.identity.get("otp")),
            "Alta": r.user.created_at,
            "Último acceso": r.user.last_login_at,
            "Compras": r.purchases,
            "Borradores": r.drafts,
            "Archivos": human_bytes(r.bytes),
            "Buzones": f"{r.mailboxes} ({r.mailbox_errors} con error)" if r.mailbox_errors else str(r.mailboxes),
        }
        for r in shown
    ],
    columns=[
        "id",
        "Nombre",
        "Correo",
        "Rol",
        "Estado",
        "2FA",
        "Alta",
        "Último acceso",
        "Compras",
        "Borradores",
        "Archivos",
        "Buzones",
    ],
)
selection = st.dataframe(
    df,
    hide_index=True,
    column_order=[c for c in df.columns if c != "id"],
    column_config={
        "Alta": st.column_config.DatetimeColumn(format="DD/MM/YYYY"),
        "Último acceso": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
        "2FA": st.column_config.CheckboxColumn(),
        "Compras": st.column_config.NumberColumn(help="Cuántas compras tiene (nunca sus importes)"),
    },
    on_select="rerun",
    selection_mode="single-row",
    key=f"users-table-{needle}-{role_filter}-{state_filter}",
)
st.caption(
    "Las cuentas aparecen aquí tras su primer inicio de sesión. Se muestran cifras de uso, nunca el detalle "
    "ni los importes de las compras."
)
if not selection.selection.rows:
    st.stop()

# --- Cuenta seleccionada ----------------------------------------------------------

selected_id = df.iloc[selection.selection.rows[0]]["id"]
row = next(r for r in shown if r.user.id == selected_id)
user = row.user
is_self = user.id == viewer.user_id

st.divider()
st.subheader(f"{user.display_name} · {user.email or user.username}")
info, actions = st.columns([2, 3], gap="large")
with info:
    created = row.identity.get("created") or user.created_at
    st.markdown(
        "\n".join(
            f"- **{label}:** {value}"
            for label, value in [
                ("Rol", ROLE_LABELS.get(user.role, user.role)),
                ("Estado", state_label(row) + (f" desde {when(user.disabled_at)}" if user.disabled_at else "")),
                ("Cuenta creada", when(created, with_time=False)),
                ("Último inicio de sesión", when(user.last_login_at)),
                ("Correo verificado", "Sí" if row.identity.get("email_verified") else "No"),
                ("Verificación en dos pasos", "Activada" if row.identity.get("otp") else "Desactivada"),
                ("Compras / borradores", f"{row.purchases:,} / {row.drafts:,}"),
                ("Archivos", f"{row.files:,} ({human_bytes(row.bytes)})"),
                ("Buzones", f"{row.mailboxes} ({row.mailbox_errors} con error)"),
                ("ID", f"`{user.id}`"),
            ]
        )
    )

with actions:
    if is_self:
        st.info("Es tu cuenta: gestiónala desde **Configuración**.", icon=":material/person:")
        st.stop()
    if directory is None:
        st.stop()

    def run(action, message: str, *args) -> None:
        try:
            with bootstrap.unit_of_work() as uow:
                target = accounts.get(uow, viewer, user.id)
                action(uow, directory, viewer, target, *args)
        except ACTION_ERRORS as e:
            st.error(str(e), icon=":material/error:")
            return
        done(message)

    with st.container(border=True):
        st.markdown("**Datos**")
        st.caption(
            "Exportación completa (filas de la base, archivos y ficha de la cuenta) para poder recrear al usuario "
            "con **Restaurar**. Contiene datos personales: guárdala en un lugar seguro."
        )
        export = st.session_state.get("user_export")
        if export and export[0] == user.id:
            st.download_button(
                "Descargar exportación",
                export[2],
                file_name=export[1],
                mime="application/zip",
                type="primary",
                icon=":material/download:",
                on_click=lambda: st.session_state.pop("user_export", None),
            )
        elif st.button("Exportar datos", icon=":material/archive:"):
            with bootstrap.unit_of_work() as uow, st.spinner("Preparando la exportación…"):
                target = accounts.get(uow, viewer, user.id)
                raw = backup.export_user(uow, storage, viewer, target, directory.account(user.id))
            st.session_state["user_export"] = (user.id, backup.export_filename(user), raw)
            st.rerun()

    if row.identity_missing:
        st.warning(
            "Esta cuenta ya no existe en Keycloak (se borró desde su consola): solo puedes exportar o eliminar "
            "sus datos en la app.",
            icon=":material/person_off:",
        )
    else:
        with st.container(border=True):
            st.markdown("**Acceso**")
            c1, c2 = st.columns(2)
            if row.blocked:
                if c1.button("Desbloquear", icon=":material/lock_open:", width="stretch"):
                    run(accounts.unblock, f"Cuenta de {user.display_name} desbloqueada")
            else:
                with c1.popover("Bloquear", icon=":material/block:", width="stretch"):
                    st.write("No podrá iniciar sesión y se cerrarán sus sesiones abiertas. Sus datos se conservan.")
                    if st.button("Sí, bloquear", key="confirm-delete-block"):
                        run(accounts.block, f"Cuenta de {user.display_name} bloqueada")
            with c2.popover("Cambiar rol", icon=":material/badge:", width="stretch"):
                new_role = st.selectbox("Nuevo rol", ROLES, index=ROLES.index(user.role), format_func=ROLE_LABELS.get)
                st.caption("Se cierran sus sesiones para que el nuevo rol aplique al volver a entrar.")
                if st.button("Aplicar", disabled=new_role == user.role):
                    run(accounts.change_role, f"{user.display_name} ahora es {ROLE_LABELS[new_role].lower()}", new_role)

        with st.container(border=True):
            st.markdown("**Soporte**")
            s1, s2 = st.columns(2)
            if s1.button("Cerrar sesiones", icon=":material/logout:", width="stretch"):
                run(accounts.logout, f"Sesiones de {user.display_name} cerradas")
            if s2.button("Forzar cambio de contraseña", icon=":material/password:", width="stretch"):
                run(accounts.force_password_change, f"Correo de cambio de contraseña enviado a {user.email}")
            s3, s4 = st.columns(2)
            if s3.button(
                "Quitar 2FA", icon=":material/phonelink_erase:", width="stretch", disabled=not row.identity.get("otp")
            ):
                run(accounts.remove_otp, f"Verificación en dos pasos quitada a {user.display_name}")
            if s4.button(
                "Reenviar verificación",
                icon=":material/mark_email_unread:",
                width="stretch",
                disabled=bool(row.identity.get("email_verified")),
            ):
                run(accounts.resend_verification, f"Correo de verificación enviado a {user.email}")

    with st.container(border=True):
        st.markdown(":red[**Eliminar cuenta**]")
        st.caption(
            "Borra la cuenta en Keycloak y todos sus datos y archivos. No se puede deshacer: exporta antes sus datos "
            "si quieres poder recrearla."
        )
        with st.popover("Eliminar cuenta", icon=":material/delete_forever:"):
            typed = st.text_input(f"Escribe **{user.email or user.username}** para confirmar")
            if st.button(
                "Eliminar definitivamente",
                key="confirm-delete-user",
                disabled=typed.strip() != (user.email or user.username),
            ):
                try:
                    with bootstrap.unit_of_work() as uow:
                        target = accounts.get(uow, viewer, user.id)
                        accounts.delete(uow, storage, directory, viewer, target)
                except ACTION_ERRORS as e:
                    st.error(str(e), icon=":material/error:")
                else:
                    done(f"Cuenta de {user.display_name} eliminada")
