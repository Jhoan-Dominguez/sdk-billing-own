"""Normaliza un archivo en `Part`s (emails en cabecera, cuerpo y adjuntos útiles) y
los convierte en bloques para un LLM según lo que acepte el modelo."""

import email
import html
import io
import re
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader

from compras.domain.files import EXT_TO_TYPE, IMAGE_TYPES, KIND_EMAIL
from compras.domain.llm import Block, Capabilities, DocumentBlock, ImageBlock, TextBlock

# Lado mayor de las imágenes enviadas al LLM: más resolución no mejora la lectura y
# encarece la llamada (y algunos proveedores la reducen igualmente).
MAX_IMAGE_SIDE = 1568
# Páginas de un PDF que se envían como imagen cuando el modelo no acepta PDFs.
MAX_PDF_PAGES = 5
# Por debajo de esto, el texto de un PDF se considera vacío (PDF escaneado).
MIN_PDF_TEXT = 40


@dataclass
class Part:
    """Un fragmento del documento listo para enviar a un extractor."""

    content_type: str
    data: bytes | None = None
    text: str | None = None


def to_parts(raw: bytes, kind: str, content_type: str) -> list[Part]:
    return split_email(raw) if kind == KIND_EMAIL else [Part(content_type, data=raw)]


def parts_text(parts: list[Part]) -> str:
    return "\n\n".join(t for t in (_part_text(p) for p in parts) if t).strip()


def split_email(raw: bytes) -> list[Part]:
    msg: EmailMessage = email.message_from_bytes(raw, policy=policy.default)  # type: ignore[assignment]
    header = "\n".join(f"{name}: {msg[name]}" for name in ("From", "To", "Date", "Subject") if msg[name])
    parts = [Part("text/plain", text=header)]

    body = msg.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            content = html_to_text(content)
        parts.append(Part("text/plain", text=content))

    for att in msg.iter_attachments():
        ctype = att.get_content_type()
        name = att.get_filename() or ""
        ctype = EXT_TO_TYPE.get(Path(name).suffix.lower(), ctype)
        if ctype in IMAGE_TYPES or ctype == "application/pdf":
            parts.append(Part(ctype, data=att.get_content()))
    return parts


def html_to_text(content: str) -> str:
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


def to_blocks(parts: list[Part], capabilities: Capabilities) -> tuple[list[Block], list[str]]:
    """Bloques para el LLM y notas sobre lo que no se pudo enviar.

    - Textos: tal cual.
    - Imágenes: orientadas según EXIF y reducidas a MAX_IMAGE_SIDE.
    - PDFs: como documento si el modelo lo acepta; si no, su texto y, si es un PDF
      escaneado y el modelo ve imágenes, sus primeras páginas como imagen.
    """
    blocks: list[Block] = []
    notes: list[str] = []
    for part in parts:
        if part.text is not None:
            if part.text.strip():
                blocks.append(TextBlock(part.text))
        elif part.content_type in IMAGE_TYPES and part.data:
            if not capabilities.vision:
                notes.append("El modelo elegido no lee imágenes.")
                continue
            blocks.append(normalize_image(part.data, part.content_type))
        elif part.content_type == "application/pdf" and part.data:
            if capabilities.pdf:
                blocks.append(DocumentBlock("application/pdf", part.data))
                continue
            text = _part_text(part)
            if len(text) >= MIN_PDF_TEXT:
                blocks.append(TextBlock(f"Texto extraído del PDF:\n{text}"))
            elif capabilities.vision:
                pages = render_pdf_pages(part.data, MAX_PDF_PAGES)
                blocks.extend(pages)
                if not pages:
                    notes.append("No se pudieron leer las páginas del PDF.")
            else:
                notes.append("El PDF no tiene texto y el modelo elegido no lee imágenes.")
    return blocks, notes


def normalize_image(data: bytes, content_type: str) -> ImageBlock:
    try:
        with Image.open(io.BytesIO(data)) as img:
            rotated = ImageOps.exif_transpose(img)
            if max(rotated.size) <= MAX_IMAGE_SIDE and rotated is img:
                return ImageBlock(content_type, data)
            rotated.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            rotated.convert("RGB").save(out, format="JPEG", quality=88)
            return ImageBlock("image/jpeg", out.getvalue())
    except (UnidentifiedImageError, OSError):
        return ImageBlock(content_type, data)  # que el proveedor decida


def render_pdf_pages(data: bytes, max_pages: int) -> list[ImageBlock]:
    """Primeras páginas de un PDF como JPEG (para modelos sin soporte de PDF)."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError:
        return []
    blocks = []
    try:
        for index in range(min(len(pdf), max_pages)):
            image = pdf[index].render(scale=2).to_pil()
            image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            image.convert("RGB").save(out, format="JPEG", quality=85)
            blocks.append(ImageBlock("image/jpeg", out.getvalue()))
    finally:
        pdf.close()
    return blocks


def email_sender(raw: bytes) -> str:
    """Dirección del remitente de un correo (minúsculas), o ''."""
    from email.utils import parseaddr

    msg = email.message_from_bytes(raw, policy=policy.default)
    return parseaddr(str(msg.get("From", "")))[1].lower()


def email_message_id(raw: bytes) -> str | None:
    msg = email.message_from_bytes(raw, policy=policy.default)
    value = str(msg.get("Message-ID", "")).strip()
    return value[:255] or None
