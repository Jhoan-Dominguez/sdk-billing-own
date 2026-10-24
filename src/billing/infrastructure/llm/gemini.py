"""Google Gemini (SDK google-genai) con salida JSON según esquema."""

from billing.domain.llm import Block, Capabilities, DocumentBlock, ImageBlock, LLMResult, TextBlock
from billing.domain.ports.llm import LLMError
from billing.infrastructure.llm.base import inline_schema, parse_json, timer


class GeminiClient:
    provider = "gemini"
    capabilities = Capabilities(vision=True, pdf=True)

    def __init__(self, model: str, api_key: str, timeout: float = 120) -> None:
        from google import genai
        from google.genai import types

        self.model = model
        self._types = types
        self._errors = genai.errors
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))

    def _parts(self, content: list[Block]) -> list:
        types = self._types
        parts = []
        for block in content:
            if isinstance(block, TextBlock):
                parts.append(types.Part.from_text(text=block.text))
            elif isinstance(block, ImageBlock | DocumentBlock):
                parts.append(types.Part.from_bytes(data=block.data, mime_type=block.media_type))
        return parts

    def generate(self, *, system, content, schema, max_tokens) -> LLMResult:
        types = self._types
        try:
            with timer() as elapsed:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=self._parts(content),
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=max_tokens,
                        response_mime_type="application/json",
                        response_json_schema=inline_schema(schema),
                    ),
                )
        except self._errors.APIError as e:
            raise LLMError(f"Gemini: {e}") from e
        usage = response.usage_metadata
        return LLMResult(
            output=parse_json(response.text, schema),
            provider=self.provider,
            model=self.model,
            duration_ms=elapsed(),
            input_tokens=usage.prompt_token_count if usage else None,
            output_tokens=usage.candidates_token_count if usage else None,
        )
