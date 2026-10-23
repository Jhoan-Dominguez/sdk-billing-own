"""Normaliza un archivo en `Part`s: emails en cabecera, cuerpo y adjuntos útiles."""

import email
import html
import io
import re
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from pathlib import Path

from pypdf import PdfReader

from compras.domain.files import EXT_TO_TYPE, IMAGE_TYPES, KIND_EMAIL


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
