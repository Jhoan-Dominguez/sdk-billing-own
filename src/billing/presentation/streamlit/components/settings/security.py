"""Pestaña Seguridad y vuelta de los enlaces de confirmación y de Keycloak.

Cada acción sensible pasa por el servicio de confirmaciones
(application/security/confirmations.py): correo → (código 2FA) → acción.
"""

import pandas as pd
import streamlit as st

from billing import bootstrap
from billing.application import users as user_service
from billing.application.security import account_actions, confirmations
from billing.domain import security
from billing.domain.errors import ValidationError
from billing.domain.models import SecurityConfirmation
from billing.domain.ports.identity import ACTION_CONFIGURE_TOTP, ACTION_UPDATE_PASSWORD, IdentityError
from billing.domain.ports.mail import MailError
from billing.presentation.streamlit.components.layout import flash
from billing.presentation.streamlit.components.settings.context import RETURN_PATH, SettingsContext

ACTION_MESSAGES = {
    ACTION_UPDATE_PASSWORD: "Contraseña actualizada",
    ACTION_CONFIGURE_TOTP: "Verificación en dos pasos activada",
}


def handle_return(ctx: SettingsContext) -> None:
    """Procesa los parámetros con los que se vuelve a esta página y los limpia:

    - `confirmar`: enlace del correo de confirmación.
    - `state` + `code`: vuelta de la reautenticación con 2FA.
    - `kc_action_status`: vuelta de una acción de Keycloak (contraseña, 2FA).
    """
    params = st.query_params
    if token := params.get(confirmations.QUERY_TOKEN):
        with bootstrap.unit_of_work() as uow:
            try:
                confirmation = confirmations.confirm_email(uow, token, user_id=ctx.viewer.user_id)
            except ValidationError as e:
                st.session_state["security_error"] = str(e)
            else:
                flash("Correo confirmado" + (": falta verificar tu código 2FA" if confirmation.requires_otp else ""))
        params.clear()
        st.rerun()

    if (state := params.get("state")) and "kc_action_status" not in params:
        code, error = params.get("code"), params.get("error")
        with bootstrap.unit_of_work() as uow:
            if error or not code:
                st.session_state["security_error"] = "Verificación cancelada."
            else:
                try:
                    confirmation = confirmations.verify_otp(
                        uow,
                        bootstrap.reauthenticator(),
                        state=state,
                        code=code,
                        user_id=ctx.viewer.user_id,
                        return_path=RETURN_PATH,
                    )
                except ValidationError as e:
                    st.session_state["security_error"] = str(e)
                else:
                    flash("Identidad verificada con tu código 2FA")
        params.clear()
        st.rerun()

    if status := params.get("kc_action_status"):
        action = params.get("kc_action", "")
        if status == "success":
            with bootstrap.unit_of_work() as uow:
                try:
                    message = account_actions.finish_identity_action(uow, ctx.kc, ctx.viewer.user_id, action)
                except IdentityError as e:
                    message = f"Keycloak no pudo terminar el cambio: {e}"
            st.toast(message or ACTION_MESSAGES.get(action, "Cambios guardados"), icon=":material/check_circle:")
        elif status == "cancelled":
            st.toast("Acción cancelada", icon=":material/info:")
        else:
            st.toast("Keycloak no pudo completar la acción", icon=":material/error:")
        params.clear()  # quita también el `code` que añade Keycloak a la URL

    if error := st.session_state.pop("security_error", None):
        st.error(error, icon=":material/error:")


def _otp_url(uow, confirmation: SecurityConfirmation, email: str | None) -> str:
    """URL de reautenticación; el `state` se genera una vez por solicitud y sesión."""
    key = f"reauth-url-{confirmation.id}"
    if key not in st.session_state or confirmation.reauth_state_hash is None:
        st.session_state[key] = confirmations.start_otp_check(
            uow, bootstrap.reauthenticator(), confirmation, login_hint=email, return_path=RETURN_PATH
        )
    return st.session_state[key]


def confirmation_flow(
    ctx: SettingsContext,
    uow,
    purpose: str,
    *,
    otp_enabled: bool,
    start_label: str,
    start_icon: str,
    final_label: str,
    final_icon: str,
    danger: bool = False,
) -> SecurityConfirmation | None:
    """Pinta el estado de la acción `purpose` y sus botones.

    Devuelve la solicitud si está lista y el usuario pulsó el botón final de una
    acción que se ejecuta en la app; las que siguen en Keycloak muestran un enlace.
    """
    user = user_service.get(uow, ctx.viewer.user_id)
    current = confirmations.active(uow, ctx.viewer.user_id).get(purpose)
    spec = security.PURPOSES[purpose]

    if current is None:
        needs_otp = security.requires_otp(purpose, otp_enabled)
        st.caption(
            "Te enviaremos un enlace de confirmación a tu correo"
            + (" y después te pediremos tu código 2FA." if needs_otp else ".")
        )
        if st.button(start_label, icon=start_icon, key=f"start-{purpose}"):
            try:
                confirmations.request(
                    uow,
                    bootstrap.mailer(),
                    user,
                    purpose,
                    otp_enabled=otp_enabled,
                    link_base=ctx.link_base,
                )
            except (ValidationError, MailError) as e:
                uow.rollback()
                st.error(str(e), icon=":material/error:")
            else:
                flash(f"Te enviamos un correo a {user.email} para confirmar")
                st.rerun()
        return None

    steps = [("Confirmar el enlace enviado a tu correo", current.email_confirmed)]
    if current.requires_otp:
        steps.append(("Verificar tu código 2FA", current.otp_verified))
    st.markdown(
        "\n".join(
            f"- {':material/check_circle:' if done else ':material/radio_button_unchecked:'} {label}"
            for label, done in steps
        )
    )
    st.caption(f"Solicitud de {spec.title.lower()} · caduca a las {current.expires_at:%H:%M}.")

    result = None
    if not current.email_confirmed:
        st.info(f"Abre el enlace que enviamos a **{user.email}** con esta sesión iniciada.", icon=":material/mail:")
    elif not current.otp_verified:
        st.link_button(
            "Verificar con mi código 2FA",
            _otp_url(uow, current, user.email),
            type="primary",
            icon=":material/pin:",
        )
    elif purpose in account_actions.IDENTITY_ACTIONS:
        url = account_actions.continue_url(
            uow, current, ctx.actions, user_id=ctx.viewer.user_id, return_path=RETURN_PATH
        )
        st.link_button(final_label, url, type="primary", icon=final_icon)
    elif st.button(final_label, icon=final_icon, key=f"confirm-delete-{purpose}" if danger else f"final-{purpose}"):
        result = current

    c1, c2 = st.columns(2)
    if c1.button("Reenviar correo", key=f"resend-{purpose}", icon=":material/forward_to_inbox:", width="stretch"):
        try:
            confirmations.request(
                uow, bootstrap.mailer(), user, purpose, otp_enabled=otp_enabled, link_base=ctx.link_base
            )
        except (ValidationError, MailError) as e:
            uow.rollback()
            st.error(str(e), icon=":material/error:")
        else:
            flash("Correo reenviado")
            st.rerun()
    if c2.button("Cancelar solicitud", key=f"cancel-{purpose}", icon=":material/close:", width="stretch"):
        confirmations.cancel(uow, current)
        flash("Solicitud cancelada")
        st.rerun()
    return result


def _load(ctx: SettingsContext) -> tuple | None:
    try:
        return ctx.kc.has_password(), ctx.kc.otp_enabled_since(), ctx.kc.sessions()
    except IdentityError as e:
        st.error(str(e), icon=":material/error:")
        return None


def render(ctx: SettingsContext) -> None:
    if ctx.keycloak_unavailable() or not (loaded := _load(ctx)):
        return
    has_password, otp_since, sessions = loaded
    otp_enabled = otp_since is not False

    with bootstrap.unit_of_work() as uow:
        with st.container(border=True):
            st.subheader("Contraseña")
            if has_password:
                st.write("Se cambia en la pantalla segura de inicio de sesión; la aplicación nunca ve tu contraseña.")
                confirmation_flow(
                    ctx,
                    uow,
                    security.CHANGE_PASSWORD,
                    otp_enabled=otp_enabled,
                    start_label="Cambiar contraseña",
                    start_icon=":material/password:",
                    final_label="Escribir la nueva contraseña",
                    final_icon=":material/password:",
                )
            else:
                st.write("Tu cuenta entra con un proveedor externo. Puedes crear también una contraseña.")
                st.link_button(
                    "Crear contraseña",
                    ctx.actions.url(ACTION_UPDATE_PASSWORD, RETURN_PATH),
                    icon=":material/password:",
                )

        with st.container(border=True):
            st.subheader("Verificación en dos pasos (2FA)")
            if otp_enabled:
                st.success(
                    "Activada con una app de autenticación"
                    + (f" desde el {otp_since:%d/%m/%Y}." if otp_since else "."),
                    icon=":material/verified_user:",
                )
                change, remove = st.tabs(["Cambiar de dispositivo", "Desactivar"])
                with change:
                    st.write("Configura una app nueva; la anterior deja de valer al terminar.")
                    confirmation_flow(
                        ctx,
                        uow,
                        security.UPDATE_OTP,
                        otp_enabled=True,
                        start_label="Cambiar dispositivo 2FA",
                        start_icon=":material/phonelink_setup:",
                        final_label="Configurar el nuevo dispositivo",
                        final_icon=":material/qr_code_scanner:",
                    )
                with remove:
                    st.write("Tu cuenta quedará protegida solo con la contraseña.")
                    ready = confirmation_flow(
                        ctx,
                        uow,
                        security.REMOVE_OTP,
                        otp_enabled=True,
                        start_label="Desactivar 2FA",
                        start_icon=":material/remove_moderator:",
                        final_label="Sí, desactivar 2FA",
                        final_icon=":material/remove_moderator:",
                        danger=True,
                    )
                    if ready:
                        execute(ctx, uow, ready)
            else:
                st.write(
                    "Al iniciar sesión te pediremos además un código temporal de una app como Google "
                    "Authenticator, Microsoft Authenticator o FreeOTP. Si no lo activas, entras solo con tu contraseña."
                )
                st.link_button(
                    "Activar 2FA",
                    ctx.actions.url(ACTION_CONFIGURE_TOTP, RETURN_PATH),
                    type="primary",
                    icon=":material/phonelink_lock:",
                )

    with st.container(border=True):
        st.subheader("Sesiones abiertas")
        if sessions:
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Dirección IP": s["ip"], "Inicio": s["start"], "Última actividad": s["last_access"]}
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
                ctx.kc.logout_everywhere()
            except IdentityError as e:
                st.error(str(e), icon=":material/error:")
            else:
                st.logout()


def execute(ctx: SettingsContext, uow, confirmation: SecurityConfirmation) -> None:
    """Ejecuta una acción lista (desactivar 2FA, eliminar la cuenta)."""
    user = user_service.get(uow, ctx.viewer.user_id)
    try:
        outcome = account_actions.execute(uow, confirmation, account=ctx.kc, storage=ctx.storage, user=user)
    except (ValidationError, IdentityError) as e:
        st.error(str(e), icon=":material/error:")
        return
    if outcome.logged_out:
        st.logout()
    flash(outcome.message)
    st.rerun()
