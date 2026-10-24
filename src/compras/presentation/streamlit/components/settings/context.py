from dataclasses import dataclass, field

import streamlit as st

from compras import bootstrap
from compras.domain.auth import Viewer
from compras.domain.ports.identity import AccountActions, AccountAdmin, IdentityError
from compras.domain.ports.storage import FileStorage

RETURN_PATH = "/configuracion"  # Keycloak y los enlaces de los correos vuelven aquí


@dataclass
class SettingsContext:
    """Lo que comparten las pestañas: usuario, cuenta en Keycloak y adaptadores."""

    viewer: Viewer
    claims: dict
    kc: AccountAdmin | None
    actions: AccountActions
    storage: FileStorage
    kc_user: dict = field(default_factory=dict)
    kc_error: str | None = None

    @classmethod
    def load(cls, viewer: Viewer, claims: dict) -> "SettingsContext":
        ctx = cls(
            viewer=viewer,
            claims=claims,
            kc=bootstrap.account_admin(viewer.user_id),
            actions=bootstrap.account_actions(),
            storage=bootstrap.file_storage(),
        )
        if ctx.kc is None:
            ctx.kc_error = "La gestión de la cuenta no está configurada (falta KEYCLOAK_ADMIN_API_SECRET)."
        else:
            try:
                ctx.kc_user = ctx.kc.profile()
            except IdentityError as e:
                ctx.kc_error = str(e)
        return ctx

    def keycloak_unavailable(self) -> bool:
        if self.kc_error:
            st.warning(self.kc_error, icon=":material/cloud_off:")
        return self.kc_error is not None

    @property
    def link_base(self) -> str:
        from compras import settings

        return settings.APP_PUBLIC_URL + RETURN_PATH
