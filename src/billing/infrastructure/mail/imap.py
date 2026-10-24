"""Lectura de buzones por IMAP (Gmail, Outlook, GreenMail en desarrollo...).

Solo lee: abre la carpeta en modo lectura (EXAMINE) y usa BODY.PEEK, así no marca
los correos como leídos ni los mueve.
"""

import contextlib
import imaplib
import re
import ssl
from email.parser import BytesHeaderParser
from email.utils import parseaddr

from billing.domain.ports.mail import FetchedMessage, FetchResult, MailError

UIDVALIDITY = re.compile(rb"UIDVALIDITY (\d+)")


def sender_matches(address: str, senders: list[str]) -> bool:
    """`senders` admite direcciones completas o dominios (`@banco.com` o `banco.com`)."""
    if not senders:
        return True
    address = address.lower()
    domain = address.rpartition("@")[2]
    for rule in senders:
        rule = rule.lower().strip()
        if "@" in rule and not rule.startswith("@"):
            if address == rule:
                return True
        elif domain == rule.lstrip("@") or domain.endswith("." + rule.lstrip("@")):
            return True
    return False


class ImapMailbox:
    def __init__(self, connection: imaplib.IMAP4, folder: str) -> None:
        self._imap = connection
        self.folder = folder

    def __enter__(self) -> "ImapMailbox":
        return self

    def __exit__(self, *exc) -> None:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            self._imap.logout()

    def _uid_validity(self) -> int:
        status, data = self._imap.status(self._quote(self.folder), "(UIDVALIDITY)")
        match = UIDVALIDITY.search(data[0] or b"") if status == "OK" else None
        return int(match.group(1)) if match else 0

    @staticmethod
    def _quote(folder: str) -> str:
        return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def fetch_new(self, after_uid: int, *, senders: list[str], limit: int) -> FetchResult:
        try:
            result = FetchResult(uid_validity=self._uid_validity(), last_uid=after_uid)
            status, _ = self._imap.select(self._quote(self.folder), readonly=True)
            if status != "OK":
                raise MailError(f"No existe la carpeta {self.folder!r}")
            status, data = self._imap.uid("SEARCH", None, f"UID {after_uid + 1}:*")
            uids = sorted(int(u) for u in (data[0] or b"").split() if int(u) > after_uid)
            for uid in uids:
                if len(result.messages) >= limit:
                    break
                result.last_uid = uid
                status, data = self._imap.uid("FETCH", str(uid), "(BODY.PEEK[HEADER.FIELDS (FROM)])")
                header = next((part[1] for part in data if isinstance(part, tuple)), b"")
                sender = parseaddr(BytesHeaderParser().parsebytes(header).get("From", ""))[1]
                if not sender_matches(sender, senders):
                    continue
                status, data = self._imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
                raw = next((part[1] for part in data if isinstance(part, tuple)), None)
                if raw:
                    result.messages.append(FetchedMessage(uid=uid, raw=raw))
            return result
        except (imaplib.IMAP4.error, OSError) as e:
            raise MailError(f"Error leyendo el buzón: {e}") from e


class ImapGateway:
    def __init__(self, timeout: float = 20) -> None:
        self.timeout = timeout

    def open(self, *, host: str, port: int, username: str, password: str, use_ssl: bool, folder: str) -> ImapMailbox:
        try:
            if use_ssl:
                connection = imaplib.IMAP4_SSL(
                    host, port, ssl_context=ssl.create_default_context(), timeout=self.timeout
                )
            else:
                connection = imaplib.IMAP4(host, port, timeout=self.timeout)
            connection.login(username, password)
        except imaplib.IMAP4.error as e:
            raise MailError(f"El servidor rechazó el usuario o la contraseña: {e}") from e
        except OSError as e:
            raise MailError(f"No se pudo conectar con {host}:{port}: {e}") from e
        return ImapMailbox(connection, folder)
