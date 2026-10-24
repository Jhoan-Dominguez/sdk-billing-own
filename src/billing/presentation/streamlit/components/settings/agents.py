"""Pestaña Agentes IA (solo administradores): proveedor y modelo LLM de cada agente."""

import pandas as pd
import streamlit as st

from billing import bootstrap
from billing.application.agents import settings as agent_settings
from billing.application.agents.registry import AGENTS, BANK_NOTIFICATION, INVOICE
from billing.domain.catalog import DEFAULT_CATEGORIES, PAYMENT_METHODS
from billing.domain.llm import TextBlock
from billing.domain.ports.llm import LLMError
from billing.presentation.streamlit.components.layout import flash
from billing.presentation.streamlit.components.settings.context import SettingsContext

# Entrada fija del botón "Probar" de cada agente.
SAMPLES = {
    INVOICE: (
        "SUPERMERCADO LA 14 S.A. NIT 890.300.346-1\nFactura electrónica FE-88231  Fecha: 2026-03-10\n"
        "2 Arroz Diana 1kg  $ 4.200  $ 8.400\n1 Aceite 1L  $ 12.900  $ 12.900\n"
        "Subtotal $ 21.300\nIVA $ 2.130\nTOTAL $ 23.430\nPago con tarjeta débito"
    ),
    BANK_NOTIFICATION: (
        "From: Nequi <notificaciones@nequi.com.co>\nSubject: Pagaste en TIENDA D1\n\n"
        "Nequi: Pagaste $23.450 en TIENDA D1 SUBA el 5 de abril de 2026 a las 7:42 p. m. desde tu Nequi."
    ),
}
LOCAL_LABEL = "Sin LLM (solo reglas locales)"
registry = bootstrap.llm_catalog()


@st.cache_data(ttl=60, show_spinner=False)
def _provider_status() -> dict[str, bool]:
    return {name: spec.configured() for name, spec in registry.PROVIDERS.items()}


@st.cache_data(ttl=60, show_spinner=False)
def _models(provider: str) -> list[str]:
    return registry.list_models(provider)


def _label(provider: str, status: dict[str, bool]) -> str:
    if provider == registry.LOCAL:
        return LOCAL_LABEL
    spec = registry.PROVIDERS[provider]
    return spec.label + ("" if status.get(provider) else " · sin configurar")


def render(ctx: SettingsContext) -> None:
    if not ctx.viewer.manages_agents:
        st.error("Solo los administradores configuran los agentes.", icon=":material/block:")
        return
    status = _provider_status()
    default = registry.default_provider()

    with st.container(border=True):
        st.subheader("Proveedores")
        st.caption(
            "Las credenciales se configuran en `.env` (no se guardan en la base). "
            f"Proveedor por defecto: **{_label(default, status)}** (`BILLING_LLM_PROVIDER`)."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Proveedor": spec.label,
                        "Estado": "Disponible" if status[name] else "Sin configurar",
                        "Se activa con": spec.needs,
                        "Modelo por defecto": spec.default_model,
                    }
                    for name, spec in registry.PROVIDERS.items()
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        if st.button("Volver a comprobar", icon=":material/refresh:"):
            _provider_status.clear()
            _models.clear()
            st.rerun()

    options = [registry.LOCAL, *registry.PROVIDERS]
    with bootstrap.unit_of_work() as uow:
        for name, spec in AGENTS.items():
            provider, model, custom = agent_settings.resolve(uow, name, (default, registry.default_model(default)))
            with st.container(border=True):
                st.subheader(spec.label)
                st.caption(spec.description)
                st.markdown(
                    f"Ahora usa **{_label(provider, status)}**"
                    + (f" · modelo `{model}`" if model else "")
                    + (" (elegido por un administrador)" if custom else " (valor por defecto)")
                )
                c1, c2 = st.columns(2)
                chosen = c1.selectbox(
                    "Proveedor",
                    options,
                    index=options.index(provider) if provider in options else 0,
                    format_func=lambda p: _label(p, status),
                    key=f"agent-provider-{name}",
                )
                chosen_model = None
                if chosen != registry.LOCAL:
                    pspec = registry.PROVIDERS[chosen]
                    models = list(dict.fromkeys([*_models(chosen), *pspec.suggested_models]))
                    current = model if chosen == provider and model else pspec.default_model
                    if current not in models:
                        models.insert(0, current)
                    chosen_model = c2.selectbox(
                        "Modelo",
                        models,
                        index=models.index(current),
                        accept_new_options=True,
                        key=f"agent-model-{name}-{chosen}",
                        help="Elige uno de la lista o escribe el nombre exacto de otro modelo del proveedor.",
                    )
                b1, b2, b3 = st.columns(3)
                if b1.button(
                    "Guardar", type="primary", icon=":material/save:", key=f"agent-save-{name}", width="stretch"
                ):
                    agent_settings.save(uow, name, chosen, chosen_model, by=ctx.viewer.user_id)
                    flash(f"{spec.label}: {_label(chosen, status)}")
                    st.rerun()
                if b2.button(
                    "Usar el valor por defecto",
                    icon=":material/restart_alt:",
                    key=f"agent-reset-{name}",
                    disabled=not custom,
                    width="stretch",
                ):
                    agent_settings.reset(uow, name)
                    flash(f"{spec.label}: vuelve al valor por defecto")
                    st.rerun()
                if b3.button(
                    "Probar",
                    icon=":material/science:",
                    key=f"agent-test-{name}",
                    disabled=chosen == registry.LOCAL,
                    width="stretch",
                ):
                    _test(name, chosen, chosen_model)


def _test(name: str, provider: str, model: str | None) -> None:
    try:
        agent = bootstrap.agent_for(name, provider, model)
        with st.spinner(f"Probando {provider} / {model}…"):
            result = agent.run(
                [TextBlock(SAMPLES[name])],
                categories=", ".join(DEFAULT_CATEGORIES),
                payment_methods=", ".join(PAYMENT_METHODS),
            )
    except (LLMError, ImportError, ValueError) as e:
        st.error(f"La prueba falló: {e}", icon=":material/error:")
        return
    st.success(
        f"Respondió {result.provider} / {result.model} en {result.duration_ms / 1000:.1f} s.",
        icon=":material/check_circle:",
    )
    st.json(result.output.model_dump(exclude_none=True), expanded=False)
