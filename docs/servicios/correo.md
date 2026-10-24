# Correo: envío (SMTP) y lectura (IMAP)

Puertos en `domain/ports/mail.py`; adaptadores en `infrastructure/mail/`.

## Envío: `Mailer`

```python
@dataclass(frozen=True)
class EmailContent:
    to: str
    subject: str
    title: str
    paragraphs: list[str]
    action_label: str | None = None  # texto del botón
    action_url: str | None = None  # enlace del botón
    footer: str = "Si no fuiste tú, ignora este correo: no se hará ningún cambio."


class Mailer(Protocol):
    def send(self, email: EmailContent) -> None: ...  # MailError si falla
```

La aplicación describe el contenido; el adaptador lo maqueta en **texto plano y HTML** con el
diseño común (`rendering.py` + `templates/layout.html`): cabecera verde «Registro de compras»,
tarjeta blanca, botón de acción, enlace copiable y pie. El HTML usa estilos en línea para que se
vea igual en cualquier cliente de correo, y escapa todo el texto.

| `COMPRAS_MAILER` | Adaptador | Uso |
|---|---|---|
| `smtp` | `SmtpMailer(host, port, sender, user, password, starttls, use_ssl)` | Mailpit en desarrollo; SES u otro SMTP en producción. Añade `Message-ID`, autentica si hay usuario, soporta STARTTLS y SSL implícito |
| `console` | `ConsoleMailer` | Escribe el correo en el log (y lo guarda en `.sent`); útil sin servidor |

Quién envía:

- **La app**: correos de confirmación de acciones sensibles ([seguridad](seguridad.md)).
- **Keycloak**: activación de cuentas, recuperación de contraseña y avisos, con su propio SMTP
  (`smtpServer` del realm, mismas variables `SMTP_*`) y el tema de correo `compras`
  (`infra/docker/keycloak/themes/compras/email`), que reproduce el mismo diseño.

## Lectura: `MailboxGateway` / `Mailbox`

```python
class MailboxGateway(Protocol):
    def open(self, *, host, port, username, password, use_ssl, folder) -> Mailbox: ...


class Mailbox(Protocol):  # gestor de contexto
    def fetch_new(self, after_uid: int, *, senders: list[str], limit: int) -> FetchResult: ...
```

`FetchResult(uid_validity, messages=[FetchedMessage(uid, raw)], last_uid)`: `last_uid` incluye
los correos revisados y descartados por remitente, para continuar desde ahí la próxima vez.

`ImapGateway` / `ImapMailbox` (`imaplib`):

- Conexión con `IMAP4_SSL` (contexto TLS por defecto) o `IMAP4` sin cifrar (solo para
  GreenMail en local); tiempo de espera de 20 s.
- `select(readonly=True)` + `UID SEARCH UID n:*` + `BODY.PEEK[HEADER.FIELDS (FROM)]` y
  `BODY.PEEK[]`: solo lectura y sin marcar como leído.
- `sender_matches(address, senders)`: una regla con `@` y texto antes es una dirección exacta;
  `@dominio` o `dominio` aceptan el dominio y sus subdominios. Lista vacía = todos.
- Errores de login → `MailError("El servidor rechazó el usuario o la contraseña…")`; de red →
  `MailError("No se pudo conectar…")`.
