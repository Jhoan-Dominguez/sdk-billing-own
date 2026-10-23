"""Extractor local: datos de factura a partir de texto con expresiones regulares.

No puede leer imágenes ni PDFs escaneados (no hay OCR).
"""

import re

from compras.domain.invoice import InvoiceData

_AMOUNT = r"([0-9]{1,3}(?:[.,\s][0-9]{3})*(?:[.,][0-9]{1,2})?|[0-9]+(?:[.,][0-9]{1,2})?)"
_TOTAL_RE = re.compile(
    r"(?im)^.*?\b(?:importe\s+)?total(?:\s+a\s+pagar|\s+factura|\s+general)?\b\s*[:=]?\s*(?:[A-Z]{3}|[$€])?\s*"
    + _AMOUNT
)
_SUBTOTAL_RE = re.compile(r"(?i)\bsub\s?-?total\b\s*[:=]?\s*(?:[A-Z]{3}|[$€])?\s*" + _AMOUNT)
_TAX_RE = re.compile(r"(?i)\b(?:iva|igv|impuestos?|tax)\b[^\n0-9]{0,20}?\s*" + _AMOUNT)
_INVOICE_RE = re.compile(
    r"(?i)\b(?:factura|invoice|recibo|ticket|comprobante)\s*(?:n[º°o.]*|no\.?|#|número)?\s*[:#]?\s*([A-Z0-9][\w-]{2,})"
)
_DATE_ISO = re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_DATE_DMY = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})\b")
_CURRENCY_RE = re.compile(r"\b(USD|EUR|MXN|COP|PEN|CLP|ARS|GTQ|CRC|DOP|UYU|BOB|PYG)\b")


def parse_amount(value: str) -> float | None:
    """Interpreta '1.234,56', '1,234.56', '1234.5' o '1 234,56'."""
    value = value.replace(" ", "").strip()
    if not value:
        return None
    last_dot, last_comma = value.rfind("."), value.rfind(",")
    decimal_sep = "." if last_dot > last_comma else ","
    head, sep, tail = value.rpartition(decimal_sep)
    if sep and len(tail) in (1, 2):  # noqa: SIM108  (más legible que un ternario largo)
        value = re.sub(r"[.,]", "", head) + "." + tail
    else:
        value = re.sub(r"[.,]", "", value)
    try:
        return float(value)
    except ValueError:
        return None


def invoice_from_text(text: str) -> InvoiceData:
    data = InvoiceData()
    if not text:
        return data

    totals = [m for m in _TOTAL_RE.finditer(text) if not re.search(r"(?i)sub\s?-?total", m.group(0))]
    if totals:  # la última aparición suele ser el total final
        data.total = parse_amount(totals[-1].group(1))
    if m := _SUBTOTAL_RE.search(text):
        data.subtotal = parse_amount(m.group(1))
    if m := _TAX_RE.search(text):
        data.tax = parse_amount(m.group(1))
    if m := _INVOICE_RE.search(text):
        data.invoice_number = m.group(1)
    if m := _CURRENCY_RE.search(text):
        data.currency = m.group(1)
    elif "€" in text:
        data.currency = "EUR"

    if m := _DATE_ISO.search(text):
        y, mo, d = (int(g) for g in m.groups())
        data.purchase_date = _iso(y, mo, d)
    elif m := _DATE_DMY.search(text):
        d, mo, y = (int(g) for g in m.groups())
        data.purchase_date = _iso(y, mo, d)

    if m := re.search(r"(?im)^From:\s*\"?([^\"<\n]+?)\"?\s*<", text):
        data.vendor = m.group(1).strip()
    else:
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), None)
        data.vendor = first_line[:200] if first_line else None
    return data


def _iso(y: int, m: int, d: int) -> str | None:
    if 1 <= m <= 12 and 1 <= d <= 31:
        return f"{y:04d}-{m:02d}-{d:02d}"
    return None
