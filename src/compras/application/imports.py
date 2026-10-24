"""Importación: archivo o correo -> borrador (adjunto sin compra) -> compra.

Un borrador puede ser una factura (agente `invoice`) o una notificación bancaria
(reglas por banco o agente `bank_notification`); `extraction_meta["document_type"]`
dice cuál es.
"""

import hashlib
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from compras.application import categories as category_service
from compras.application.purchases import apply_values
from compras.domain.catalog import DEFAULT_CATEGORIES, DOCUMENT_BANK_NOTIFICATION, PAYMENT_METHODS, SOURCE_BANK
from compras.domain.files import KIND_EMAIL, classify
from compras.domain.invoice import ExtractionResult
from compras.domain.models import Attachment, Purchase
from compras.domain.ports.extraction import BankNotificationParser, InvoiceExtractor
from compras.domain.ports.repositories import UnitOfWork
from compras.domain.ports.storage import FileStorage

# Margen de días para avisar de compras parecidas (la factura y la alerta del banco
# del mismo pago pueden tener fechas distintas).
SIMILAR_DAYS = 2


def store_upload(
    uow: UnitOfWork,
    storage: FileStorage,
    extractor: InvoiceExtractor,
    filename: str,
    content_type: str | None,
    raw: bytes,
    *,
    owner_id: str,
    bank_parser: BankNotificationParser | None = None,
) -> Attachment:
    """Guarda el archivo, extrae sus datos y crea un adjunto en borrador.

    Los correos se prueban primero como notificación bancaria (`bank_parser`) y, si
    no lo son, como factura.
    """
    kind, ctype = classify(filename, content_type)
    result = None
    if kind == KIND_EMAIL and bank_parser is not None:
        result = bank_parser.parse(raw)
    if result is None:
        categories = category_service.names(uow, owner_id=owner_id)
        result = extractor.extract(raw, kind, ctype, categories=categories)
    return _store(uow, storage, raw, result, owner_id=owner_id, filename=filename, kind=kind, ctype=ctype)


def store_bank_email(
    uow: UnitOfWork,
    storage: FileStorage,
    raw: bytes,
    result: ExtractionResult,
    *,
    owner_id: str,
    message_id: str | None,
    mailbox_id: int | None,
    subject: str | None = None,
) -> Attachment:
    """Guarda una notificación bancaria leída de un buzón como borrador."""
    name = f"{(subject or 'notificacion').strip()[:80]}.eml"
    return _store(
        uow,
        storage,
        raw,
        result,
        owner_id=owner_id,
        filename=name,
        kind=KIND_EMAIL,
        ctype="message/rfc822",
        message_id=message_id,
        mailbox_id=mailbox_id,
    )


def _store(
    uow: UnitOfWork,
    storage: FileStorage,
    raw: bytes,
    result: ExtractionResult,
    *,
    owner_id: str,
    filename: str,
    kind: str,
    ctype: str,
    message_id: str | None = None,
    mailbox_id: int | None = None,
) -> Attachment:
    stored_name = f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    storage.save(stored_name, raw)
    att = Attachment(
        owner_id=owner_id,
        original_name=Path(filename).name[:255],
        stored_name=stored_name,
        content_type=ctype,
        kind=kind,
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        extracted_text=result.text or None,
        extracted=result.data.model_dump(),
        extraction_error=result.error,
        extraction_meta=result.meta or None,
        message_id=message_id,
        mailbox_id=mailbox_id,
    )
    uow.attachments.add(att)
    try:
        uow.commit()
    except Exception:
        storage.delete(stored_name)  # sin fila no debe quedar el archivo huérfano
        raise
    return att


def confirm_draft(uow: UnitOfWork, att: Attachment, values: dict, items: list[dict]) -> Purchase:
    source = SOURCE_BANK if att.document_type == DOCUMENT_BANK_NOTIFICATION else att.kind
    purchase = apply_values(Purchase(source=source, owner_id=att.owner_id), values, items)
    purchase.attachments.append(att)
    uow.purchases.add(purchase)
    uow.commit()
    return purchase


def discard_draft(uow: UnitOfWork, storage: FileStorage, att: Attachment) -> None:
    if att.is_draft:
        key = att.stored_name
        uow.attachments.delete(att)
        uow.commit()
        storage.delete(key)


def drafts(uow: UnitOfWork, *, owner_id: str | None) -> list[Attachment]:
    return uow.attachments.drafts(owner_id=owner_id)


def get_draft(uow: UnitOfWork, attachment_id: int, *, owner_id: str | None) -> Attachment | None:
    """El borrador pendiente si existe y es visible con ese filtro de dueño."""
    att = uow.attachments.get(attachment_id)
    if att is None or not att.is_draft or (owner_id is not None and att.owner_id != owner_id):
        return None
    return att


def draft_values(att: Attachment, categories: list[str] | None = None) -> tuple[dict, list[dict]]:
    """Valores extraídos de un borrador para precargar el formulario.

    `categories` son las que puede usar el dueño (por defecto, las iniciales).
    """
    data = dict(att.extracted or {})
    items = data.pop("items", None) or []
    try:
        data["purchase_date"] = date.fromisoformat(data.get("purchase_date") or "")
    except ValueError:
        data["purchase_date"] = None
    if data.get("category") not in (categories or DEFAULT_CATEGORIES):
        data["category"] = None
    if data.get("payment_method") not in PAYMENT_METHODS:
        data["payment_method"] = None
    return data, items


def find_duplicates(uow: UnitOfWork, att: Attachment) -> list[Attachment]:
    """Otros adjuntos del mismo usuario con el mismo contenido (factura subida dos veces).

    Se limita al dueño: avisar de duplicados ajenos revelaría archivos de otros usuarios.
    """
    return uow.attachments.same_content(att.sha256, owner_id=att.owner_id, exclude_id=att.id)


def similar_purchases(uow: UnitOfWork, att: Attachment) -> list[Purchase]:
    """Compras del mismo usuario con el mismo total y fecha cercana a la del borrador.

    Detecta, por ejemplo, la factura y la notificación del banco del mismo pago.
    """
    data = att.extracted or {}
    total, raw_date = data.get("total"), data.get("purchase_date")
    if total is None or not raw_date:
        return []
    try:
        when = date.fromisoformat(raw_date)
    except ValueError:
        return []
    window = timedelta(days=SIMILAR_DAYS)
    candidates = uow.purchases.between(when - window, when + window + timedelta(days=1), owner_id=att.owner_id)
    amount = Decimal(str(total)).quantize(Decimal("0.01"))
    return [p for p in candidates if p.total == amount]


def read_file(storage: FileStorage, att: Attachment) -> bytes:
    return storage.read(att.stored_name)
