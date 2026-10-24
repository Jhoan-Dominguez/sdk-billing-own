"""Catálogo de proveedores LLM: cómo saber si están configurados y cómo construirlos.

Para añadir un proveedor: escribir su adaptador (implementa LLMClient) y añadir aquí
un ProviderSpec. La interfaz de administración (Configuración → Agentes IA) y el
composition root (bootstrap.py) leen este registro; nada más cambia.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from billing import settings
from billing.domain.llm import Capabilities
from billing.domain.ports.llm import LLMClient

# Sin LLM: los agentes no se ejecutan y la extracción usa solo reglas locales.
LOCAL = "local"


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    default_model: str
    suggested_models: tuple[str, ...]
    configured: Callable[[], bool]
    build: Callable[[str], LLMClient]
    needs: str  # qué variable(s) de entorno lo activan, para la interfaz
    can_list_models: bool = False
    extras: dict = field(default_factory=dict)


def _anthropic(model: str) -> LLMClient:
    from billing.infrastructure.llm.anthropic import AnthropicClient

    return AnthropicClient(model, settings.ANTHROPIC_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS)


def _openai(model: str) -> LLMClient:
    from billing.infrastructure.llm.openai import OpenAICompatibleClient

    # Con OPENAI_BASE_URL apunta a una API compatible, que puede no aceptar PDFs.
    pdf = not settings.OPENAI_BASE_URL
    return OpenAICompatibleClient(
        model,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL or None,
        capabilities=Capabilities(vision=True, pdf=pdf),
        timeout=settings.LLM_TIMEOUT_SECONDS,
    )


def _ollama(model: str) -> LLMClient:
    from billing.infrastructure.llm.openai import OpenAICompatibleClient

    return OpenAICompatibleClient(
        model,
        api_key="ollama",
        base_url=settings.OLLAMA_BASE_URL,
        provider="ollama",
        capabilities=Capabilities(vision=True, pdf=False),
        timeout=settings.LLM_TIMEOUT_SECONDS,
        # Los modelos con razonamiento (qwen3, deepseek-r1...) son mucho más lentos
        # pensando y no lo necesitan para extraer datos; vacío = lo que decida el modelo.
        extra_body={"reasoning_effort": settings.OLLAMA_REASONING_EFFORT} if settings.OLLAMA_REASONING_EFFORT else None,
    )


def _gemini(model: str) -> LLMClient:
    from billing.infrastructure.llm.gemini import GeminiClient

    return GeminiClient(model, settings.GEMINI_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS)


def _ollama_available() -> bool:
    import httpx

    try:
        return httpx.get(settings.OLLAMA_BASE_URL.rstrip("/") + "/models", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


PROVIDERS: dict[str, ProviderSpec] = {
    spec.name: spec
    for spec in (
        ProviderSpec(
            "anthropic",
            "Anthropic (Claude)",
            "claude-opus-5-5",
            ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
            lambda: bool(settings.ANTHROPIC_API_KEY),
            _anthropic,
            needs="ANTHROPIC_API_KEY",
        ),
        ProviderSpec(
            "openai",
            "OpenAI (o API compatible)",
            "gpt-5-mini",
            ("gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4.1-mini"),
            lambda: bool(settings.OPENAI_API_KEY),
            _openai,
            needs="OPENAI_API_KEY (y OPENAI_BASE_URL para APIs compatibles)",
            can_list_models=True,
        ),
        ProviderSpec(
            "gemini",
            "Google Gemini",
            "gemini-2.5-flash",
            ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"),
            lambda: bool(settings.GEMINI_API_KEY),
            _gemini,
            needs="GEMINI_API_KEY",
        ),
        ProviderSpec(
            "ollama",
            "Ollama (modelos locales)",
            "qwen3.5:9b",
            ("qwen3.5:9b", "llama3.2-vision", "gemma3"),
            _ollama_available,
            _ollama,
            needs="Ollama corriendo en OLLAMA_BASE_URL",
            can_list_models=True,
        ),
    )
}


def default_provider() -> str:
    """COMPRAS_LLM_PROVIDER, o el primero con credenciales en la nube, o `local`.

    Ollama no se elige solo (no tiene credenciales): hay que pedirlo explícitamente.
    """
    if settings.LLM_PROVIDER:
        return settings.LLM_PROVIDER
    for name in ("anthropic", "openai", "gemini"):
        if PROVIDERS[name].configured():
            return name
    return LOCAL


def default_model(provider: str) -> str | None:
    if provider == LOCAL or provider not in PROVIDERS:
        return None
    if settings.LLM_MODEL and provider == default_provider():
        return settings.LLM_MODEL
    return PROVIDERS[provider].default_model


def build(provider: str, model: str | None) -> LLMClient | None:
    """El cliente para (proveedor, modelo); None si es `local` o el proveedor no existe."""
    spec = PROVIDERS.get(provider)
    if spec is None:
        return None
    return spec.build(model or spec.default_model)


def list_models(provider: str) -> list[str]:
    spec = PROVIDERS.get(provider)
    if spec is None or not spec.can_list_models or not spec.configured():
        return []
    client = spec.build(spec.default_model)
    return client.list_models() if hasattr(client, "list_models") else []
