"""Tipos de archivo que acepta la importación de facturas."""

from pathlib import Path

from billing.domain.errors import UnsupportedFile

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

KIND_IMAGE, KIND_PDF, KIND_EMAIL = "image", "pdf", "email"


def classify(filename: str, content_type: str | None) -> tuple[str, str]:
    """Devuelve (kind, content_type) normalizados o lanza UnsupportedFile."""
    ctype = EXT_TO_TYPE.get(Path(filename).suffix.lower()) or (content_type or "")
    if ctype in IMAGE_TYPES:
        return KIND_IMAGE, ctype
    if ctype == "application/pdf":
        return KIND_PDF, ctype
    if ctype == "message/rfc822":
        return KIND_EMAIL, ctype
    raise UnsupportedFile(f"Formato no soportado: {filename}. Usa JPG, PNG, GIF, WEBP, PDF o EML.")
