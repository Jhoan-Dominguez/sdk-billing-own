"""Tipos neutrales para hablar con cualquier modelo de lenguaje (ver ports/llm.py).

Los agentes construyen el contenido con estos bloques; cada adaptador de
infrastructure/llm los traduce al formato de su proveedor.
"""

from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class ImageBlock:
    media_type: str  # image/jpeg, image/png, image/gif, image/webp
    data: bytes


@dataclass(frozen=True)
class DocumentBlock:
    """Un PDF completo (solo para modelos con `Capabilities.pdf`)."""

    media_type: str
    data: bytes
    name: str = "documento.pdf"


Block = TextBlock | ImageBlock | DocumentBlock


@dataclass(frozen=True)
class Capabilities:
    vision: bool = True  # acepta imágenes
    pdf: bool = False  # acepta PDFs como documento (si no, se envía su texto o páginas como imagen)


@dataclass
class LLMResult[T: BaseModel]:
    """Respuesta validada contra el esquema pedido, con datos de uso."""

    output: T
    provider: str
    model: str
    duration_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    extra: dict = field(default_factory=dict)

    def meta(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }
