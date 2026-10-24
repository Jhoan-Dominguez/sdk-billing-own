"""Proveedor y modelo de cada agente: lo elegido por un administrador (tabla
agent_settings) o, si no hay nada guardado, el valor por defecto del entorno."""

from billing.application.agents.registry import AGENTS
from billing.domain.errors import ValidationError
from billing.domain.models import AgentSetting
from billing.domain.ports.repositories import UnitOfWork


def resolve(uow: UnitOfWork, agent: str, default: tuple[str, str | None]) -> tuple[str, str | None, bool]:
    """(proveedor, modelo, personalizado) del agente. `default` = (proveedor, modelo) del entorno."""
    setting = uow.agent_settings.get(agent)
    if setting is None:
        return default[0], default[1], False
    return setting.provider, setting.model, True


def save(uow: UnitOfWork, agent: str, provider: str, model: str | None, *, by: str) -> AgentSetting:
    if agent not in AGENTS:
        raise ValidationError(f"Agente desconocido: {agent}")
    model = (model or "").strip() or None
    setting = uow.agent_settings.get(agent)
    if setting is None:
        setting = AgentSetting(agent=agent, provider=provider, model=model, updated_by=by)
        uow.agent_settings.add(setting)
    else:
        setting.provider, setting.model, setting.updated_by = provider, model, by
    uow.commit()
    return setting


def reset(uow: UnitOfWork, agent: str) -> None:
    """Vuelve al valor por defecto del entorno."""
    if setting := uow.agent_settings.get(agent):
        uow.agent_settings.delete(setting)
        uow.commit()
