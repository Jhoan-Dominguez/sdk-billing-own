"""Correo: envío de avisos (Mailer) y lectura de buzones IMAP (MailboxGateway)."""

from dataclasses import dataclass, field
from typing import Protocol, Self


class MailError(RuntimeError):
    """No se pudo enviar o leer el correo (servidor caído, credenciales, etc.)."""


@dataclass(frozen=True)
class EmailContent:
    """Un correo transaccional. El adaptador lo maqueta en texto y HTML con el diseño
    común (infrastructure/mail/templates), así la aplicación no escribe HTML."""

    to: str
    subject: str
    title: str
    paragraphs: list[str]
    action_label: str | None = None
    action_url: str | None = None
    footer: str = "Si no fuiste tú, ignora este correo: no se hará ningún cambio."


class Mailer(Protocol):
    def send(self, email: EmailContent) -> None:
        """Envía el correo o lanza MailError."""
        ...


@dataclass(frozen=True)
class FetchedMessage:
    uid: int
    raw: bytes  # correo completo (RFC 822)


@dataclass
class FetchResult:
    uid_validity: int
    messages: list[FetchedMessage] = field(default_factory=list)
    # Último UID revisado (incluye los descartados por remitente): desde aquí sigue la próxima vez.
    last_uid: int = 0


class Mailbox(Protocol):
    """Una carpeta abierta de un buzón."""

    def __enter__(self) -> Self: ...
    def __exit__(self, *exc) -> None: ...

    def fetch_new(self, after_uid: int, *, senders: list[str], limit: int) -> FetchResult:
        """Correos con UID > `after_uid` cuyo remitente coincide con `senders`
        (direcciones completas o dominios con @). Lista vacía = todos."""
        ...


class MailboxGateway(Protocol):
    def open(self, *, host: str, port: int, username: str, password: str, use_ssl: bool, folder: str) -> Mailbox:
        """Conecta e inicia sesión; lanza MailError si falla."""
        ...
