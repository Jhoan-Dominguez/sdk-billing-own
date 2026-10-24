"""Claude (API de Anthropic) con structured outputs (`messages.parse`)."""

from compras.domain.llm import Block, Capabilities, DocumentBlock, ImageBlock, LLMResult, TextBlock
from compras.domain.ports.llm import LLMError, LLMRefusal
from compras.infrastructure.llm.base import b64, timer


class AnthropicClient:
    provider = "anthropic"
    capabilities = Capabilities(vision=True, pdf=True)

    def __init__(self, model: str, api_key: str, timeout: float = 120) -> None:
        import anthropic

        self.model = model
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key or None, timeout=timeout)

    @staticmethod
    def _content(content: list[Block]) -> list[dict]:
        blocks = []
        for block in content:
            if isinstance(block, TextBlock):
                blocks.append({"type": "text", "text": block.text})
            elif isinstance(block, ImageBlock):
                source = {"type": "base64", "media_type": block.media_type, "data": b64(block.data)}
                blocks.append({"type": "image", "source": source})
            elif isinstance(block, DocumentBlock):
                source = {"type": "base64", "media_type": block.media_type, "data": b64(block.data)}
                blocks.append({"type": "document", "source": source})
        return blocks

    def generate(self, *, system, content, schema, max_tokens) -> LLMResult:
        try:
            with timer() as elapsed:
                response = self._client.beta.messages.parse(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    output_config={"effort": "low"},
                    # Si un clasificador de seguridad rechaza la petición, la API la
                    # reintenta en otro modelo dentro de la misma llamada.
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                    messages=[{"role": "user", "content": self._content(content)}],
                    output_format=schema,
                )
        except self._anthropic.APIError as e:
            raise LLMError(f"Anthropic: {e}") from e
        if response.stop_reason == "refusal":
            raise LLMRefusal("el modelo rechazó procesar el documento")
        if response.parsed_output is None:
            raise LLMError(f"respuesta sin datos (stop_reason={response.stop_reason})")
        return LLMResult(
            output=response.parsed_output,
            provider=self.provider,
            model=response.model or self.model,
            duration_ms=elapsed(),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
