"""Sincronización de buzones: lee los correos nuevos de los remitentes configurados y
crea un borrador por cada notificación de un movimiento.

Lo usan el worker (python -m compras.worker, todos los buzones activos) y el botón
"Sincronizar ahora" de la app (un buzón).
"""

import email
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email import policy

from compras.application import imports
from compras.domain.models import MailboxConnection
from compras.domain.ports.crypto import CipherError, SecretCipher
from compras.domain.ports.extraction import BankNotificationParser
from compras.domain.ports.mail import MailboxGateway, MailError
from compras.domain.ports.repositories import UnitOfWork
from compras.domain.ports.storage import FileStorage

log = logging.getLogger("compras.bank_emails")


@dataclass
class SyncReport:
    mailbox_id: int
    read: int = 0  # correos de los remitentes configurados
    imported: int = 0  # borradores creados
    skipped: int = 0  # ya importados o que no son movimientos
    error: str | None = None
    draft_ids: list[int] = field(default_factory=list)

    def summary(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        return f"{self.read} correos revisados, {self.imported} movimientos importados, {self.skipped} omitidos."


def _headers(raw: bytes) -> tuple[str | None, str | None]:
    msg = email.message_from_bytes(raw, policy=policy.default)
    message_id = str(msg.get("Message-ID", "")).strip()[:255] or None
    return message_id, str(msg.get("Subject", "")).strip() or None


def sync_mailbox(
    uow: UnitOfWork,
    mailbox: MailboxConnection,
    *,
    gateway: MailboxGateway,
    cipher: SecretCipher,
    parser: BankNotificationParser,
    storage: FileStorage,
    batch: int = 50,
    now: datetime | None = None,
) -> SyncReport:
    """Sincroniza un buzón. Nunca lanza: el error queda en el informe y en el buzón."""
    report = SyncReport(mailbox_id=mailbox.id)
    try:
        password = cipher.decrypt(mailbox.password_encrypted)
        with gateway.open(
            host=mailbox.host,
            port=mailbox.port,
            username=mailbox.username,
            password=password,
            use_ssl=mailbox.use_ssl,
            folder=mailbox.folder,
        ) as box:
            after = mailbox.last_uid
            result = box.fetch_new(after, senders=mailbox.senders, limit=batch)
            if mailbox.uid_validity is not None and result.uid_validity not in (0, mailbox.uid_validity):
                # El servidor renumeró la carpeta: se relee de cero (los Message-ID evitan duplicados).
                after = 0
                result = box.fetch_new(after, senders=mailbox.senders, limit=batch)
        for message in result.messages:
            report.read += 1
            message_id, subject = _headers(message.raw)
            if message_id and uow.attachments.by_message_id(message_id, owner_id=mailbox.owner_id):
                report.skipped += 1
                continue
            parsed = parser.parse(message.raw)
            if parsed is None or not (parsed.meta.get("bank") or {}).get("is_transaction", True):
                report.skipped += 1
                continue
            att = imports.store_bank_email(
                uow,
                storage,
                message.raw,
                parsed,
                owner_id=mailbox.owner_id,
                message_id=message_id,
                mailbox_id=mailbox.id,
                subject=subject,
            )
            report.imported += 1
            report.draft_ids.append(att.id)
        mailbox.uid_validity = result.uid_validity or mailbox.uid_validity
        mailbox.last_uid = max(result.last_uid, after)  # last_uid nunca retrocede salvo al releer
        mailbox.last_error = None
        mailbox.imported_count += report.imported
    except (MailError, CipherError) as e:
        report.error = str(e)
        mailbox.last_error = str(e)[:1000]
        log.warning("Buzón %s: %s", mailbox.id, e)
    mailbox.last_sync_at = now or datetime.now()
    uow.commit()
    return report


def sync_all(uow_factory, **deps) -> list[SyncReport]:
    """Sincroniza todos los buzones activos, cada uno en su propia transacción."""
    with uow_factory() as uow:
        ids = [m.id for m in uow.mailboxes.enabled()]
    reports = []
    for mailbox_id in ids:
        with uow_factory() as uow:
            mailbox = uow.mailboxes.get(mailbox_id)
            if mailbox is not None and mailbox.enabled:
                reports.append(sync_mailbox(uow, mailbox, **deps))
    return reports
