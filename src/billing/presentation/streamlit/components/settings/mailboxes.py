"""Pestaña Correo bancario: buzones IMAP de los que se leen las notificaciones del banco."""

import streamlit as st

from billing import bootstrap, settings
from billing.application.bank_emails import mailboxes as mailbox_service
from billing.application.bank_emails import sync
from billing.domain.errors import ValidationError
from billing.domain.models import MailboxConnection
from billing.domain.ports.crypto import CipherError
from billing.domain.ports.mail import MailError
from billing.presentation.streamlit.components.layout import flash
from billing.presentation.streamlit.components.settings.context import SettingsContext

HELP = """
**Gmail:** `imap.gmail.com`, puerto 993, SSL. Usa una *contraseña de aplicación*
(Cuenta de Google → Seguridad → Verificación en 2 pasos → Contraseñas de aplicaciones).
**Outlook / Hotmail:** `outlook.office365.com`, puerto 993, SSL.
**Desarrollo (GreenMail):** servidor `greenmail` desde Docker o `localhost` en local, puerto 3143,
sin SSL; usuario `cliente@compras.example.com`, contraseña `Bandeja-Compras-2026`.
Envía alertas de prueba con `make bank-samples`.

La app solo **lee** (no marca como leído, no borra ni mueve correos) y únicamente los de los
remitentes que indiques. La contraseña se guarda cifrada.
"""


def _form(key: str, mailbox: MailboxConnection | None) -> tuple[mailbox_service.MailboxForm, str | None]:
    """Formulario de alta/edición; devuelve (datos, botón pulsado)."""
    m = mailbox
    with st.form(key, enter_to_submit=False):
        c1, c2, c3 = st.columns([3, 1, 1], vertical_alignment="bottom")
        host = c1.text_input("Servidor IMAP *", value=m.host if m else "", placeholder="imap.gmail.com")
        port = c2.number_input("Puerto", value=m.port if m else 993, min_value=1, max_value=65535, step=1)
        use_ssl = c3.checkbox("SSL", value=m.use_ssl if m else True)
        c1, c2 = st.columns(2)
        username = c1.text_input("Usuario *", value=m.username if m else "", placeholder="tu@gmail.com")
        password = c2.text_input(
            "Contraseña de aplicación" + ("" if m else " *"),
            type="password",
            placeholder="Déjala vacía para conservar la actual" if m else "",
        )
        c1, c2 = st.columns([1, 3])
        folder = c1.text_input("Carpeta", value=m.folder if m else "INBOX")
        senders = c2.text_input(
            "Remitentes del banco",
            value=m.sender_filter if m else mailbox_service.DEFAULT_SENDERS,
            help="Direcciones o dominios separados por coma (p. ej. @bancolombia.com.co). Vacío = todos.",
        )
        enabled = st.toggle("Sincronizar automáticamente", value=m.enabled if m else True)
        b1, b2 = st.columns(2)
        save = b1.form_submit_button("Guardar", type="primary", icon=":material/save:", width="stretch")
        test = b2.form_submit_button("Probar conexión", icon=":material/lan:", width="stretch")
    form = mailbox_service.MailboxForm(
        host=host,
        port=int(port),
        username=username,
        password=password or None,
        use_ssl=use_ssl,
        folder=folder,
        sender_filter=senders,
        enabled=enabled,
    )
    return form, "save" if save else "test" if test else None


def _test(form, mailbox=None) -> None:
    try:
        message = mailbox_service.test_connection(bootstrap.mailbox_gateway(), bootstrap.secret_cipher(), form, mailbox)
    except (ValidationError, MailError, CipherError) as e:
        st.error(str(e), icon=":material/error:")
    else:
        st.success(message, icon=":material/check_circle:")


def _status(mailbox: MailboxConnection) -> None:
    if mailbox.last_error:
        st.error(f"Último error: {mailbox.last_error}", icon=":material/error:")
    synced = f"{mailbox.last_sync_at:%d/%m/%Y %H:%M}" if mailbox.last_sync_at else "nunca"
    state = "activa" if mailbox.enabled else "pausada"
    st.caption(
        f"Sincronización {state} · última: {synced} · {mailbox.imported_count} movimientos importados · "
        f"cada {settings.MAIL_SYNC_INTERVAL // 60 or 1} min con el worker"
    )


def render(ctx: SettingsContext) -> None:
    owner = ctx.viewer.user_id
    try:
        bootstrap.secret_cipher()
    except CipherError as e:
        st.error(f"{e} Pide a un administrador que la configure.", icon=":material/key_off:")
        return

    st.write(
        "Conecta el correo donde recibes las alertas de tu banco (compras con tarjeta, retiros, "
        "transferencias). Cada alerta nueva aparece en **Importar facturas** como borrador para revisar."
    )
    with st.expander("Cómo conectar Gmail, Outlook o el buzón de pruebas", icon=":material/help:"):
        st.markdown(HELP)

    with bootstrap.unit_of_work() as uow:
        boxes = mailbox_service.for_owner(uow, owner)
        for mailbox in boxes:
            with st.container(border=True):
                head, sync_col = st.columns([3, 1], vertical_alignment="center")
                head.subheader(f":material/mail: {mailbox.username}")
                if sync_col.button(
                    "Sincronizar ahora", key=f"sync-{mailbox.id}", icon=":material/sync:", width="stretch"
                ):
                    with st.spinner("Leyendo correos nuevos…"):
                        report = sync.sync_mailbox(
                            uow,
                            mailbox,
                            gateway=bootstrap.mailbox_gateway(),
                            cipher=bootstrap.secret_cipher(),
                            parser=bootstrap.bank_parser(),
                            storage=ctx.storage,
                            batch=settings.MAIL_SYNC_BATCH,
                        )
                    flash(report.summary())
                    st.rerun()
                _status(mailbox)
                with st.expander("Editar", icon=":material/edit:"):
                    form, pressed = _form(f"mailbox-{mailbox.id}", mailbox)
                    if pressed == "test":
                        _test(form, mailbox)
                    elif pressed == "save":
                        try:
                            mailbox_service.update(uow, bootstrap.secret_cipher(), mailbox, form)
                        except ValidationError as e:
                            uow.rollback()
                            st.error(str(e), icon=":material/error:")
                        else:
                            flash("Buzón actualizado")
                            st.rerun()
                    with st.popover("Desconectar buzón", icon=":material/link_off:"):
                        st.write("Se borra la conexión; los borradores ya importados se conservan.")
                        if st.button("Sí, desconectar", key=f"confirm-delete-mailbox-{mailbox.id}"):
                            mailbox_service.delete(uow, mailbox)
                            flash("Buzón desconectado")
                            st.rerun()

        if len(boxes) < mailbox_service.MAX_MAILBOXES:
            with st.container(border=True):
                st.subheader("Conectar un buzón")
                form, pressed = _form(f"mailbox-new-{st.session_state.get('mailbox_no', 0)}", None)
                if pressed == "test":
                    _test(form)
                elif pressed == "save":
                    try:
                        mailbox_service.create(uow, bootstrap.secret_cipher(), form, owner_id=owner)
                    except ValidationError as e:
                        uow.rollback()
                        st.error(str(e), icon=":material/error:")
                    else:
                        st.session_state["mailbox_no"] = st.session_state.get("mailbox_no", 0) + 1
                        flash("Buzón conectado: pulsa «Sincronizar ahora» o espera al worker")
                        st.rerun()
