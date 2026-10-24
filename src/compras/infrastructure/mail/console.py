import logging

from compras.domain.ports.mail import EmailContent
from compras.infrastructure.mail.rendering import render_text

log = logging.getLogger("compras.mail")


class ConsoleMailer:
    """Mailer sin servidor: escribe el correo en el log (desarrollo sin Mailpit)."""

    def __init__(self) -> None:
        self.sent: list[EmailContent] = []

    def send(self, email: EmailContent) -> None:
        self.sent.append(email)
        log.warning("Correo para %s — %s\n%s", email.to, email.subject, render_text(email))
