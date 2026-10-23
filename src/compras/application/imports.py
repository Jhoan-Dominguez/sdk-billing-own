"""Importación de facturas: archivo -> borrador (adjunto sin compra) -> compra."""

import hashlib
import uuid
from datetime import date
from pathlib import Path

from compras.application.purchases import apply_values
from compras.domain.catalog import DEFAULT_CATEGORIES, PAYMENT_METHODS
from compras.domain.files import classify
from compras.domain.models import Attachment, Purchase
from compras.domain.ports.extraction import InvoiceExtractor
from compras.domain.ports.repositories import UnitOfWork
from compras.domain.ports.storage import FileStorage


def store_upload(
    uow: UnitOfWork,
    storage: FileStorage,
    extractor: InvoiceExtractor,
    filename: str,
    content_type: str | None,
    raw: bytes,
    *,
    owner_id: str,
) -> Attachment:
    """Guarda el archivo, extrae sus datos y crea un adjunto en borrador."""
    kind, ctype = classify(filename, content_type)
    stored_name = f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    storage.save(stored_name, raw)

    result = extractor.extract(raw, kind, ctype)
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
    )
    uow.attachments.add(att)
    uow.commit()
    return att


def confirm_draft(uow: UnitOfWork, att: Attachment, values: dict, items: list[dict]) -> Purchase:
    purchase = apply_values(Purchase(source=att.kind, owner_id=att.owner_id), values, items)
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


def read_file(storage: FileStorage, att: Attachment) -> bytes:
    return storage.read(att.stored_name)
