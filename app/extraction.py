"""Convierte un archivo (imagen, PDF o email .eml) en un borrador de compra.

Dos estrategias:
- "claude": envía el archivo a la API de Anthropic, que lee imágenes y PDFs
  (incluidos escaneados) y devuelve `InvoiceData` validado con structured outputs.
- "local": sin red. Extrae texto de PDFs digitales y emails y aplica regex.
  No puede leer imágenes ni PDFs escaneados (no hay OCR instalado).
"""

import base64
import email
import html
import io
import re
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from pathlib import Path

from pypdf import PdfReader

from app import config
from app.schemas import InvoiceData

# Tipos de imagen que acepta la API de Claude.
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
EXT_TO_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".eml": "message/rfc822",
}


class UnsupportedFile(ValueError):
    pass


def classify(filename: str, content_type: str | None) -> tuple[str, str]:
    """Devuelve (kind, content_type) normalizados o lanza UnsupportedFile."""
    ctype = EXT_TO_TYPE.get(Path(filename).suffix.lower()) or (content_type or "")
    if ctype in IMAGE_TYPES:
        return "imagen", ctype
    if ctype == "application/pdf":
        return "pdf", ctype
    if ctype == "message/rfc822":
        return "email", ctype
    raise UnsupportedFile(
        f"Formato no soportado: {filename}. Usa JPG, PNG, GIF, WEBP, PDF o EML."
    )


@dataclass
class Part:
    """Un fragmento del documento listo para enviar a un extractor."""

    content_type: str
    data: bytes | None = None
    text: str | None = None


@dataclass
class ExtractionResult:
    text: str = ""
    data: InvoiceData = field(default_factory=InvoiceData)
    error: str | None = None


def extract(raw: bytes, kind: str, content_type: str, extractor: str | None = None) -> ExtractionResult:
    parts = _split_email(raw) if kind == "email" else [Part(content_type, data=raw)]
    text = "\n\n".join(t for t in (_part_text(p) for p in parts) if t).strip()
    result = ExtractionResult(text=text)

    try:
        if (extractor or config.EXTRACTOR) == "claude":
            result.data = extract_with_claude(parts)
        else:
            result.data = extract_from_text(text)
            if not text:
                result.error = (
                    "El extractor local no puede leer imágenes ni PDFs escaneados. "
                    "Completa los datos a mano o configura ANTHROPIC_API_KEY."
                )
    except Exception as exc:  # el borrador sigue siendo útil aunque falle la extracción
        result.error = f"No se pudo extraer automáticamente: {exc}"
        result.data = extract_from_text(text)
    return result


# --- Emails -----------------------------------------------------------------


def _split_email(raw: bytes) -> list[Part]:
    msg: EmailMessage = email.message_from_bytes(raw, policy=policy.default)  # type: ignore[assignment]
    header = "\n".join(
        f"{name}: {msg[name]}" for name in ("From", "To", "Date", "Subject") if msg[name]
    )
    parts = [Part("text/plain", text=header)]

    body = msg.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            content = _html_to_text(content)
        parts.append(Part("text/plain", text=content))

    for att in msg.iter_attachments():
        ctype = att.get_content_type()
        name = att.get_filename() or ""
        ctype = EXT_TO_TYPE.get(Path(name).suffix.lower(), ctype)
        if ctype in IMAGE_TYPES or ctype == "application/pdf":
            parts.append(Part(ctype, data=att.get_content()))
    return parts


def _html_to_text(content: str) -> str:
    content = re.sub(r"(?is)<(script|style).*?</\1>", " ", content)
    content = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", content)
    content = re.sub(r"<[^>]+>", " ", content)
    content = html.unescape(content)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", content)).strip()


def _part_text(part: Part) -> str:
    if part.text is not None:
        return part.text
    if part.content_type == "application/pdf" and part.data:
        try:
            reader = PdfReader(io.BytesIO(part.data))
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except Exception:
            return ""
    return ""


# --- Extractor con Claude ----------------------------------------------------

PROMPT = """Eres un asistente que registra compras personales.
Extrae los datos de la factura, recibo o email de compra adjunto.
- Usa null para cualquier dato que no aparezca; no inventes valores.
- purchase_date en formato YYYY-MM-DD.
- Montos como números sin símbolo de moneda ni separador de miles.
- category debe ser una de: {categories}.
- Si el documento no es una compra, deja todos los campos en null."""


def extract_with_claude(parts: list[Part]) -> InvoiceData:
    import anthropic

    content: list[dict] = []
    for part in parts:
        if part.text:
            content.append({"type": "text", "text": part.text})
        elif part.content_type in IMAGE_TYPES:
            content.append({"type": "image", "source": _b64_source(part)})
        elif part.content_type == "application/pdf":
            content.append({"type": "document", "source": _b64_source(part)})
    content.append(
        {"type": "text", "text": PROMPT.format(categories=", ".join(config.CATEGORIES))}
    )

    client = anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        output_config={"effort": "low"},
        # Si un clasificador de seguridad rechaza la petición, la API la reintenta
        # en otro modelo dentro de la misma llamada.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
        output_format=InvoiceData,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("el modelo rechazó procesar el documento")
    if response.parsed_output is None:
        raise RuntimeError(f"respuesta sin datos (stop_reason={response.stop_reason})")
    return response.parsed_output


def _b64_source(part: Part) -> dict:
    return {
        "type": "base64",
        "media_type": part.content_type,
        "data": base64.standard_b64encode(part.data or b"").decode(),
    }


# --- Extractor local (regex) -------------------------------------------------

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
    if sep and len(tail) in (1, 2):
        value = re.sub(r"[.,]", "", head) + "." + tail
    else:
        value = re.sub(r"[.,]", "", value)
    try:
        return float(value)
    except ValueError:
        return None


def extract_from_text(text: str) -> InvoiceData:
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
