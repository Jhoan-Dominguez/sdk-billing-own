"""Pestaña Cuenta: información y eliminación de la cuenta (correo + 2FA)."""

import streamlit as st

from compras import bootstrap
from compras.application import categories as category_service
from compras.application import users as user_service
from compras.domain import auth, security
from compras.domain.ports.identity import IdentityError
from compras.presentation.streamlit.components.settings.context import SettingsContext
from compras.presentation.streamlit.components.settings.security import confirmation_flow, execute


def render(ctx: SettingsContext) -> None:
    viewer = ctx.viewer
    with bootstrap.unit_of_work() as uow:
        user = user_service.get(uow, viewer.user_id)
        usage = category_service.usage(uow, owner_id=viewer.user_id)
        providers, otp_enabled = [], False
        if ctx.kc and not ctx.kc_error:
            try:
                providers = ctx.kc.linked_providers()
                otp_enabled = ctx.kc.otp_enabled_since() is not False
            except IdentityError:
                pass
        with st.container(border=True):
            st.subheader("Información de la cuenta")
            created = ctx.kc_user.get("created") or user.created_at
            info = {
                "Correo electrónico": user.email or "—",
                "Rol": auth.ROLE_LABELS.get(viewer.role, viewer.role),
                "Cuenta creada": f"{created:%d/%m/%Y}" if created else "—",
                "Último inicio de sesión": f"{user.last_login_at:%d/%m/%Y %H:%M}",
                "Acceso con": ", ".join(["Correo y contraseña", *[p.capitalize() for p in providers]]),
                "Verificación en dos pasos": "Activada" if otp_enabled else "Desactivada",
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
                return
            st.write(
                "Se borrarán de forma permanente tu cuenta, todas tus compras, archivos adjuntos, "
                "avatar, buzones conectados y categorías personales. Esta acción no se puede deshacer."
            )
            if ctx.keycloak_unavailable():
                return
            ready = confirmation_flow(
                ctx,
                uow,
                security.DELETE_ACCOUNT,
                otp_enabled=otp_enabled,
                start_label="Solicitar eliminación de la cuenta",
                start_icon=":material/delete_forever:",
                final_label="Eliminar definitivamente",
                final_icon=":material/delete_forever:",
                danger=True,
            )
            if ready:
                execute(ctx, uow, ready)
