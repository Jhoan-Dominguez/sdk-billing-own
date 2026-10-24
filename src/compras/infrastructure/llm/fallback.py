"""Cadena de proveedores: si uno falla, se prueba el siguiente."""

from compras.domain.llm import Capabilities, LLMResult
from compras.domain.ports.llm import LLMClient, LLMError


class FallbackLLMClient:
    def __init__(self, clients: list[LLMClient]) -> None:
        if not clients:
            raise ValueError("FallbackLLMClient necesita al menos un cliente")
        self.clients = clients
        self.provider = clients[0].provider
        self.model = clients[0].model
        # Se anuncia lo que soportan todos: el contenido debe servir a cualquiera.
        self.capabilities = Capabilities(
            vision=all(c.capabilities.vision for c in clients), pdf=all(c.capabilities.pdf for c in clients)
        )

    def generate(self, **kwargs) -> LLMResult:
        errors = []
        for client in self.clients:
            try:
                result = client.generate(**kwargs)
            except LLMError as e:
                errors.append(f"{client.provider}/{client.model}: {e}")
                continue
            if errors:
                result.extra["fallback_errors"] = errors
            return result
        raise LLMError("; ".join(errors))
