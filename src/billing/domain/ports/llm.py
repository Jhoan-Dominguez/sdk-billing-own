from typing import Protocol, TypeVar

from pydantic import BaseModel

from billing.domain.llm import Block, Capabilities, LLMResult

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """El proveedor falló (red, credenciales, cuota) o la respuesta no cumple el esquema."""


class LLMRefusal(LLMError):
    """El modelo se negó a procesar el contenido."""


class LLMClient(Protocol):
    """Un modelo de lenguaje concreto (proveedor + modelo) con salida estructurada.

    Implementaciones en infrastructure/llm (anthropic, openai, gemini, ollama, fake);
    los agentes (application/agents) solo conocen esta interfaz.
    """

    provider: str
    model: str
    capabilities: Capabilities

    def generate(self, *, system: str, content: list[Block], schema: type[T], max_tokens: int) -> LLMResult[T]:
        """Envía `content` con las instrucciones `system` y devuelve la salida validada
        contra `schema`. Lanza LLMError (o LLMRefusal) si no lo consigue."""
        ...
