"""OpenAI y cualquier API compatible (Ollama, OpenRouter, Groq, Azure, vLLM...).

Usa Chat Completions con `response_format` json_schema, que también implementa
Ollama en /v1. Si la API no soporta PDFs (`pdf=False`), el agente le envía el texto
del documento o sus páginas como imagen.
"""

from compras.domain.llm import Block, Capabilities, DocumentBlock, ImageBlock, LLMResult, TextBlock
from compras.domain.ports.llm import LLMError
from compras.infrastructure.llm.base import data_url, inline_schema, parse_json, timer

FULL = Capabilities(vision=True, pdf=True)


class OpenAICompatibleClient:
    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        base_url: str | None = None,
        provider: str = "openai",
        capabilities: Capabilities = FULL,
        timeout: float = 120,
        extra_body: dict | None = None,
    ) -> None:
        import openai

        self.model = model
        self.provider = provider
        self.capabilities = capabilities
        self._extra_body = extra_body or None  # parámetros propios de cada API (p. ej. Ollama)
        self._openai = openai
        self._client = openai.OpenAI(api_key=api_key or "no-key", base_url=base_url or None, timeout=timeout)

    def _content(self, content: list[Block]) -> list[dict]:
        parts = []
        for block in content:
            if isinstance(block, TextBlock):
                parts.append({"type": "text", "text": block.text})
            elif isinstance(block, ImageBlock):
                parts.append({"type": "image_url", "image_url": {"url": data_url(block.media_type, block.data)}})
            elif isinstance(block, DocumentBlock):
                parts.append(
                    {
                        "type": "file",
                        "file": {"filename": block.name, "file_data": data_url(block.media_type, block.data)},
                    }
                )
        return parts

    def generate(self, *, system, content, schema, max_tokens) -> LLMResult:
        try:
            with timer() as elapsed:
                response = self._client.chat.completions.create(
                    model=self.model,
                    max_completion_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": self._content(content)},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": schema.__name__, "schema": inline_schema(schema), "strict": False},
                    },
                    extra_body=self._extra_body,
                )
        except self._openai.OpenAIError as e:
            raise LLMError(f"{self.provider}: {e}") from e
        choice = response.choices[0]
        if getattr(choice.message, "refusal", None):
            raise LLMError(f"el modelo rechazó procesar el documento: {choice.message.refusal}")
        usage = response.usage
        return LLMResult(
            output=parse_json(choice.message.content, schema),
            provider=self.provider,
            model=response.model or self.model,
            duration_ms=elapsed(),
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )

    def list_models(self) -> list[str]:
        """Modelos que ofrece la API (Ollama: los descargados). Vacío si no se puede listar."""
        try:
            return sorted(m.id for m in self._client.models.list())
        except self._openai.OpenAIError:
            return []
