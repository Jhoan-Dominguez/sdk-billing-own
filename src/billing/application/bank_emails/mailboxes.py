"""Alta, edición, prueba y baja de los buzones IMAP de un usuario."""

from dataclasses import dataclass

from billing.domain.errors import ValidationError
from billing.domain.models import MailboxConnection
from billing.domain.ports.crypto import SecretCipher
from billing.domain.ports.mail import MailboxGateway
from billing.domain.ports.repositories import UnitOfWork
from billing.domain.values import clean_str

# Remitentes sugeridos al crear un buzón (dominios de las alertas de bancos colombianos).
DEFAULT_SENDERS = (
    "@notificacionesbancolombia.com, @bancolombia.com.co, @davivienda.com, @bbva.com.co, "
    "@bancodebogota.com.co, @nequi.com.co"
)
MAX_MAILBOXES = 5


@dataclass
class MailboxForm:
    host: str
    port: int
    username: str
    password: str | None  # None/vacío al editar = conservar la actual
    use_ssl: bool = True
    folder: str = "INBOX"
    sender_filter: str = DEFAULT_SENDERS
    enabled: bool = True


def _validate(form: MailboxForm) -> MailboxForm:
    host, username = clean_str(form.host), clean_str(form.username)
    errors = []
    if not host:
        errors.append("Servidor: obligatorio")
    if not username:
        errors.append("Usuario: obligatorio")
    if not 1 <= int(form.port or 0) <= 65535:
        errors.append("Puerto: entre 1 y 65535")
    if errors:
        raise ValidationError("\n".join(errors))
    senders = ", ".join(s.strip() for s in (form.sender_filter or "").split(",") if s.strip())
    return MailboxForm(
        host=host.lower(),
        port=int(form.port),
        username=username,
        password=form.password,
        use_ssl=bool(form.use_ssl),
        folder=clean_str(form.folder) or "INBOX",
        sender_filter=senders,
        enabled=bool(form.enabled),
    )


def get(uow: UnitOfWork, mailbox_id: int, *, owner_id: str) -> MailboxConnection | None:
    """El buzón si existe y es del usuario (nunca se gestionan buzones ajenos)."""
    mailbox = uow.mailboxes.get(mailbox_id)
    return mailbox if mailbox is not None and mailbox.owner_id == owner_id else None


def for_owner(uow: UnitOfWork, owner_id: str) -> list[MailboxConnection]:
    return uow.mailboxes.for_owner(owner_id)


def create(uow: UnitOfWork, cipher: SecretCipher, form: MailboxForm, *, owner_id: str) -> MailboxConnection:
    form = _validate(form)
    if not form.password:
        raise ValidationError("Contraseña: obligatoria")
    if len(uow.mailboxes.for_owner(owner_id)) >= MAX_MAILBOXES:
        raise ValidationError(f"Puedes conectar como máximo {MAX_MAILBOXES} buzones.")
    mailbox = MailboxConnection(
        owner_id=owner_id,
        host=form.host,
        port=form.port,
        username=form.username,
        password_encrypted=cipher.encrypt(form.password),
        use_ssl=form.use_ssl,
        folder=form.folder,
        sender_filter=form.sender_filter,
        enabled=form.enabled,
    )
    uow.mailboxes.add(mailbox)
    uow.commit()
    return mailbox


def update(uow: UnitOfWork, cipher: SecretCipher, mailbox: MailboxConnection, form: MailboxForm) -> None:
    form = _validate(form)
    moved = (form.host, form.username, form.folder) != (mailbox.host, mailbox.username, mailbox.folder)
    mailbox.host, mailbox.port, mailbox.username = form.host, form.port, form.username
    mailbox.use_ssl, mailbox.folder, mailbox.enabled = form.use_ssl, form.folder, form.enabled
    mailbox.sender_filter = form.sender_filter
    if form.password:
        mailbox.password_encrypted = cipher.encrypt(form.password)
    if moved:  # otro buzón o carpeta: se empieza a leer de cero
        mailbox.uid_validity, mailbox.last_uid = None, 0
    mailbox.last_error = None
    uow.commit()


def delete(uow: UnitOfWork, mailbox: MailboxConnection) -> None:
    """Los borradores ya importados se conservan (pierden solo el vínculo al buzón)."""
    for att in uow.attachments.drafts(owner_id=mailbox.owner_id):
        if att.mailbox_id == mailbox.id:
            att.mailbox_id = None
    uow.mailboxes.delete(mailbox)
    uow.commit()


def test_connection(gateway: MailboxGateway, cipher: SecretCipher, form: MailboxForm, mailbox=None) -> str:
    """Conecta con los datos del formulario (o la contraseña guardada) y devuelve un
    resumen. Lanza MailError o ValidationError."""
    form = _validate(form)
    password = form.password or (cipher.decrypt(mailbox.password_encrypted) if mailbox else "")
    if not password:
        raise ValidationError("Contraseña: obligatoria")
    with gateway.open(
        host=form.host,
        port=form.port,
        username=form.username,
        password=password,
        use_ssl=form.use_ssl,
        folder=form.folder,
    ) as box:
        box.fetch_new(0, senders=[], limit=0)  # abre la carpeta: falla si no existe
    return f"Conexión correcta con {form.host}. Carpeta {form.folder!r} disponible."
