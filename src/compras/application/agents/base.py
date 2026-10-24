from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pydantic import BaseModel

from compras.domain.llm import Block, LLMResult
from compras.domain.ports.llm import LLMClient

PROMPTS_DIR = Path(__file__).with_name("prompts")


@dataclass(frozen=True)
class AgentSpec:
    name: str
    label: str
    description: str
    output: type[BaseModel]
    prompt_file: str  # en prompts/, con marcadores {nombre} para str.format
    max_tokens: int = 16000

    @property
    def prompt(self) -> str:
        return _read_prompt(self.prompt_file)


@cache
def _read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


class Agent:
    """Un AgentSpec conectado a un LLMClient concreto."""

    def __init__(self, spec: AgentSpec, llm: LLMClient) -> None:
        self.spec = spec
        self.llm = llm

    @property
    def name(self) -> str:
        return self.spec.name

    def instructions(self, **variables) -> str:
        return self.spec.prompt.format(**variables)

    def run(self, content: list[Block], **variables) -> LLMResult:
        """Ejecuta el agente. Lanza LLMError si el proveedor falla."""
        result = self.llm.generate(
            system=self.instructions(**variables),
            content=content,
            schema=self.spec.output,
            max_tokens=self.spec.max_tokens,
        )
        result.extra["agent"] = self.spec.name
        return result
