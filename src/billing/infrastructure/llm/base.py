"""Utilidades comunes de los adaptadores LLM."""

import base64
import copy
import json
import re
import time
from contextlib import contextmanager

from pydantic import BaseModel, ValidationError

from billing.domain.ports.llm import LLMError


def b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode()


def data_url(media_type: str, data: bytes) -> str:
    return f"data:{media_type};base64,{b64(data)}"


def inline_schema(model: type[BaseModel]) -> dict:
    """JSON Schema del modelo sin $ref/$defs (algunos proveedores no los resuelven)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(copy.deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]]))
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def parse_json(text: str | None, schema: type[BaseModel]):
    """Valida la respuesta contra el esquema. Tolera texto alrededor del JSON
    (p. ej. bloques ```json o razonamiento de modelos locales)."""
    if not text:
        raise LLMError("el modelo devolvió una respuesta vacía")
    try:
        return schema.model_validate_json(text)
    except ValidationError:
        match = JSON_BLOCK.search(text)
        try:
            return schema.model_validate(json.loads(match.group(0))) if match else None
        except (ValueError, ValidationError) as e:
            raise LLMError(f"la respuesta no cumple el formato esperado: {e}") from e


@contextmanager
def timer():
    """`with timer() as elapsed: ...; elapsed()` -> milisegundos."""
    start = time.monotonic()
    yield lambda: int((time.monotonic() - start) * 1000)
