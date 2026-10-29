import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from billing.domain.ports.mail import EmailContent, MailError
from billing.infrastructure.mail.rendering import render_html, render_text


class SmtpMailer:
    """Mailer por SMTP: Mailpit en desarrollo, cualquier servidor (p. ej. Amazon SES) en producción."""

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        *,
        user: str = "",
        password: str = "",
        starttls: bool = False,
        use_ssl: bool = False,
        sender_name: str = "Registro de compras",
        timeout: float = 15,
    ) -> None:
        self.host, self.port = host, port
        self.sender = formataddr((sender_name, sender))
        self.domain = sender.rpartition("@")[2] or None
        self.user, self.password = user, password
        self.starttls, self.use_ssl = starttls, use_ssl
        self.timeout = timeout

    def build(self, email: EmailContent) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = email.to
        msg["Subject"] = email.subject
        msg["Message-ID"] = make_msgid(domain=self.domain)
        msg.set_content(render_text(email))
        msg.add_alternative(render_html(email), subtype="html")
        return msg

    def _connect(self) -> smtplib.SMTP:
        if self.use_ssl:
            server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        if self.starttls:
            server.starttls(context=ssl.create_default_context())
        if self.user:
            server.login(self.user, self.password)
        return server

    def send(self, email: EmailContent) -> None:
        msg = self.build(email)
        try:
            with self._connect() as server:
                server.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            raise MailError(f"No se pudo enviar el correo ({self.host}:{self.port}): {e}") from e

    def check(self) -> None:
        """Conecta (y se autentica) sin enviar nada; lanza MailError si falla."""
        try:
            with self._connect() as server:
                server.noop()
        except (OSError, smtplib.SMTPException) as e:
            raise MailError(f"Sin conexión con {self.host}:{self.port}: {e}") from e
