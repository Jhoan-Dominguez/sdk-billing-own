"""Casos de uso de compras: alta, edición, borrado y consultas."""

from datetime import date
from decimal import Decimal

from compras.domain.catalog import FALLBACK_CATEGORY, SOURCE_MANUAL
from compras.domain.errors import ValidationError
from compras.domain.models import Purchase, PurchaseItem
from compras.domain.periods import month_bounds
from compras.domain.ports.repositories import UnitOfWork
from compras.domain.ports.storage import FileStorage
from compras.domain.values import CENT, clean_str, to_decimal, truncate
from compras.settings import DEFAULT_CURRENCY


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
    vendor = clean_str(values.get("vendor"))
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
        description = clean_str(row.get("description"))
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
            PurchaseItem(description=description[:300], quantity=quantity, unit_price=unit_price, line_total=line_total)
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
    # Los textos se recortan al tamaño que admite el almacenamiento.
    purchase.vendor_tax_id = truncate(values.get("vendor_tax_id"), 50)
    purchase.invoice_number = truncate(values.get("invoice_number"), 100)
    purchase.category = truncate(values.get("category"), 50) or FALLBACK_CATEGORY
    purchase.payment_method = truncate(values.get("payment_method"), 50)
    purchase.currency = (clean_str(values.get("currency")) or DEFAULT_CURRENCY).upper()[:3]
    purchase.notes = clean_str(values.get("notes"))
    purchase.subtotal = subtotal
    purchase.tax = tax
    purchase.total = total
    purchase.items = new_items
    return purchase


def create(uow: UnitOfWork, values: dict, items: list[dict], *, owner_id: str, source: str = SOURCE_MANUAL) -> Purchase:
    purchase = apply_values(Purchase(source=source, owner_id=owner_id), values, items)
    uow.purchases.add(purchase)
    uow.commit()
    return purchase


def update(uow: UnitOfWork, purchase: Purchase, values: dict, items: list[dict]) -> Purchase:
    try:
        apply_values(purchase, values, items)
    except ValidationError:
        uow.rollback()
        raise
    uow.commit()
    return purchase


def delete(uow: UnitOfWork, storage: FileStorage, purchase: Purchase) -> None:
    """Borra la compra y sus archivos (la base no borra archivos al borrar filas)."""
    keys = [att.stored_name for att in purchase.attachments]
    uow.purchases.delete(purchase)
    uow.commit()
    for key in keys:
        storage.delete(key)


def get(uow: UnitOfWork, purchase_id: int, *, owner_id: str | None) -> Purchase | None:
    """La compra si existe y es visible con ese filtro de dueño."""
    purchase = uow.purchases.get(purchase_id)
    if purchase is None or (owner_id is not None and purchase.owner_id != owner_id):
        return None
    return purchase


def between(uow: UnitOfWork, start: date, end: date, *, owner_id: str | None) -> list[Purchase]:
    return uow.purchases.between(start, end, owner_id=owner_id)


def in_month(uow: UnitOfWork, month: str, *, owner_id: str | None) -> list[Purchase]:
    return uow.purchases.between(*month_bounds(month), owner_id=owner_id)


def form_values(p: Purchase) -> tuple[dict, list[dict]]:
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
        {"description": i.description, "quantity": i.quantity, "unit_price": i.unit_price, "line_total": i.line_total}
        for i in p.items
    ]
    return values, items
