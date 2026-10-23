"""Lectura de facturas con la API de Anthropic (structured outputs -> InvoiceData)."""

import base64

from compras.domain.files import IMAGE_TYPES
from compras.domain.invoice import InvoiceData
from compras.infrastructure.extraction.documents import Part

PROMPT = """Eres un asistente que registra compras personales.
Extrae los datos de la factura, recibo o email de compra adjunto.
- Usa null para cualquier dato que no aparezca; no inventes valores.
- purchase_date en formato YYYY-MM-DD.
- Montos como números sin símbolo de moneda ni separador de miles.
- category debe ser una de: {categories}.
- Si el documento no es una compra, deja todos los campos en null."""


def read_with_claude(parts: list[Part], *, model: str, categories: list[str]) -> InvoiceData:
    import anthropic

    content: list[dict] = []
    for part in parts:
        if part.text:
            content.append({"type": "text", "text": part.text})
        elif part.content_type in IMAGE_TYPES:
            content.append({"type": "image", "source": _b64_source(part)})
        elif part.content_type == "application/pdf":
            content.append({"type": "document", "source": _b64_source(part)})
    content.append({"type": "text", "text": PROMPT.format(categories=", ".join(categories))})

    client = anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=model,
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
