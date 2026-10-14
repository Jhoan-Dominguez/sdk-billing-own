import hashlib
import math
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.extraction import classify, extract
from app.models import Attachment, Purchase, PurchaseItem

CENT = Decimal("0.01")


# --- Alta / edición de compras -----------------------------------------------


class ValidationError(ValueError):
    pass


def to_decimal(value, field_name: str = "valor") -> Decimal | None:
    """Acepta None, NaN (celdas vacías de pandas), números o textos con coma decimal."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
        if not value:
            return None
    try:
        return Decimal(str(value)).quantize(CENT)
    except InvalidOperation:
        raise ValidationError(f"{field_name}: '{value}' no es un número válido")


def _clean_str(value) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return str(value).strip() or None


def apply_values(purchase: Purchase, values: dict, items: list[dict]) -> Purchase:
    """Valida los valores del formulario y los copia a `purchase`.

    `items` son filas con description/quantity/unit_price/line_total; las filas sin
    descripción se ignoran. Si no se indica total se calcula desde las líneas o
    desde subtotal + impuestos.
    """
    errors = []

    purchase_date = values.get("purchase_date")
    if isinstance(purchase_date, str):
        try:
            purchase_date = date.fromisoformat(purchase_date)
        except ValueError:
            purchase_date = None
    if not isinstance(purchase_date, date):
        errors.append("Fecha: obligatoria")
    vendor = _clean_str(values.get("vendor"))
    if not vendor:
        errors.append("Comercio: obligatorio")

    subtotal = tax = total = None
    try:
        subtotal = to_decimal(values.get("subtotal"), "Subtotal")
        tax = to_decimal(values.get("tax"), "Impuestos")
        total = to_decimal(values.get("total"), "Total")
    except ValidationError as e:
        errors.append(str(e))

    new_items = []
    for row in items:
        description = _clean_str(row.get("description"))
        if not description:
            continue
        try:
            quantity = to_decimal(row.get("quantity"), "Cantidad") or Decimal(1)
            unit_price = to_decimal(row.get("unit_price"), "Precio unitario")
            line_total = to_decimal(row.get("line_total"), "Total de línea")
        except ValidationError as e:
            errors.append(f"{description}: {e}")
            continue
        if line_total is None and unit_price is not None:
            line_total = (quantity * unit_price).quantize(CENT)
        new_items.append(
            PurchaseItem(
                description=description[:300],
                quantity=quantity,
                unit_price=unit_price,
                line_total=line_total,
            )
        )

    if total is None and not errors:
        line_sum = sum((i.line_total for i in new_items if i.line_total is not None), Decimal(0))
        total = line_sum or ((subtotal or 0) + (tax or 0)) or None
    if total is None and not errors:
        errors.append("Total: obligatorio (o agrega líneas de detalle con precio)")
    if errors:
        raise ValidationError("\n".join(errors))

    purchase.purchase_date = purchase_date
    purchase.vendor = vendor[:200]
    purchase.vendor_tax_id = _clean_str(values.get("vendor_tax_id"))
    purchase.invoice_number = _clean_str(values.get("invoice_number"))
    purchase.category = _clean_str(values.get("category")) or "Otros"
    purchase.payment_method = _clean_str(values.get("payment_method"))
    purchase.currency = (_clean_str(values.get("currency")) or config.DEFAULT_CURRENCY).upper()[:3]
    purchase.notes = _clean_str(values.get("notes"))
    purchase.subtotal = subtotal
    purchase.tax = tax
    purchase.total = total
    purchase.items = new_items
    return purchase


def create_purchase(session: Session, values: dict, items: list[dict], source: str = "manual") -> Purchase:
    purchase = apply_values(Purchase(source=source), values, items)
    session.add(purchase)
    session.commit()
    return purchase


def update_purchase(session: Session, purchase: Purchase, values: dict, items: list[dict]) -> Purchase:
    try:
        apply_values(purchase, values, items)
    except ValidationError:
        session.rollback()
        raise
    session.commit()
    return purchase


def delete_purchase(session: Session, purchase: Purchase) -> None:
    # El CASCADE de la base no borra los archivos del disco.
    for att in purchase.attachments:
        delete_attachment_file(att)
    session.delete(purchase)
    session.commit()


def purchase_values(p: Purchase) -> tuple[dict, list[dict]]:
    """Valores de una compra existente para precargar el formulario."""
    values = {
        "purchase_date": p.purchase_date,
        "vendor": p.vendor,
        "vendor_tax_id": p.vendor_tax_id,
        "invoice_number": p.invoice_number,
        "category": p.category,
        "payment_method": p.payment_method,
        "currency": p.currency,
        "subtotal": p.subtotal,
        "tax": p.tax,
        "total": p.total,
        "notes": p.notes,
    }
    items = [
        {
            "description": i.description,
            "quantity": i.quantity,
            "unit_price": i.unit_price,
            "line_total": i.line_total,
        }
        for i in p.items
    ]
    return values, items


def draft_values(att: Attachment) -> tuple[dict, list[dict]]:
    """Valores extraídos de un borrador para precargar el formulario."""
    data = dict(att.extracted or {})
    items = data.pop("items", None) or []
    try:
        data["purchase_date"] = date.fromisoformat(data.get("purchase_date") or "")
    except ValueError:
        data["purchase_date"] = None
    if data.get("category") not in config.CATEGORIES:
        data["category"] = None
    if data.get("payment_method") not in config.PAYMENT_METHODS:
        data["payment_method"] = None
    return data, items


# --- Adjuntos ----------------------------------------------------------------


def store_upload(session: Session, filename: str, content_type: str | None, raw: bytes) -> Attachment:
    """Guarda el archivo en disco, lo procesa y crea un adjunto en borrador."""
    kind, ctype = classify(filename, content_type)
    suffix = Path(filename).suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / stored_name).write_bytes(raw)

    result = extract(raw, kind, ctype)
    att = Attachment(
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
    session.add(att)
    session.commit()
    return att


def confirm_draft(session: Session, att: Attachment, values: dict, items: list[dict]) -> Purchase:
    purchase = apply_values(Purchase(source=att.kind), values, items)
    purchase.attachments.append(att)
    session.add(purchase)
    session.commit()
    return purchase


def discard_draft(session: Session, att: Attachment) -> None:
    if att.purchase_id is None:
        delete_attachment_file(att)
        session.delete(att)
        session.commit()


def pending_drafts(session: Session) -> list[Attachment]:
    return list(
        session.scalars(
            select(Attachment).where(Attachment.purchase_id.is_(None)).order_by(Attachment.id.desc())
        )
    )


def attachment_path(att: Attachment) -> Path:
    return config.UPLOAD_DIR / att.stored_name


def read_attachment(att: Attachment) -> bytes:
    return attachment_path(att).read_bytes()


def delete_attachment_file(att: Attachment) -> None:
    attachment_path(att).unlink(missing_ok=True)


def find_duplicates(session: Session, att: Attachment) -> list[Attachment]:
    """Otros adjuntos con el mismo contenido (misma factura subida dos veces)."""
    return list(
        session.scalars(
            select(Attachment).where(Attachment.sha256 == att.sha256, Attachment.id != att.id)
        )
    )


# --- Resumen mensual ---------------------------------------------------------


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def month_bounds(month: str) -> tuple[date, date]:
    """'2026-10' -> (2026-10-01, 2026-11-01)."""
    start = date.fromisoformat(f"{month}-01")
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return start, end


def last_months(n: int, today: date | None = None) -> list[str]:
    """Las claves 'AAAA-MM' de los últimos `n` meses, de la más antigua a la actual."""
    today = today or date.today()
    keys, y, m = [], today.year, today.month
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return keys[::-1]


def purchases_between(session: Session, start: date, end: date) -> list[Purchase]:
    return list(
        session.scalars(
            select(Purchase)
            .where(Purchase.purchase_date >= start, Purchase.purchase_date < end)
            .order_by(Purchase.purchase_date.desc(), Purchase.id.desc())
        )
    )


def purchases_in_month(session: Session, month: str) -> list[Purchase]:
    return purchases_between(session, *month_bounds(month))


def totals_by(purchases: list[Purchase], key) -> dict:
    """{clave: {moneda: total}} — las monedas no se suman entre sí."""
    out: dict = defaultdict(lambda: defaultdict(Decimal))
    for p in purchases:
        out[key(p)][p.currency] += p.total
    return {k: dict(v) for k, v in out.items()}
