"""LLM falso: devuelve respuestas fijas sin red (desarrollo y pruebas)."""

from compras.domain.llm import Capabilities, LLMResult


class FakeLLMClient:
    provider = "fake"
    capabilities = Capabilities(vision=True, pdf=True)

    def __init__(self, model: str = "fake", responses: dict[str, dict] | None = None) -> None:
        """`responses`: por nombre de esquema, el dict con el que construir la salida.
        Si no hay respuesta para un esquema, se construye con sus valores por defecto."""
        self.model = model
        self.responses = responses or {}
        self.calls: list[dict] = []

    def generate(self, *, system, content, schema, max_tokens) -> LLMResult:
        self.calls.append({"system": system, "content": content, "schema": schema.__name__})
        data = self.responses.get(schema.__name__, {})
        if "is_transaction" in schema.model_fields:
            data = {"is_transaction": False, **data}
        return LLMResult(output=schema.model_validate(data), provider=self.provider, model=self.model)
