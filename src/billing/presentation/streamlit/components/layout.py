"""Estilos, avisos entre reruns y el encabezado con el filtro de mes."""

from pathlib import Path

import streamlit as st

from billing.domain.auth import Viewer
from billing.domain.periods import last_months
from billing.presentation.streamlit.components.formatting import month_label

STYLES = Path(__file__).resolve().parent.parent / "assets" / "styles.css"


def apply_styles() -> None:
    st.html(f"<style>{STYLES.read_text()}</style>")


def flash(message: str) -> None:
    """Muestra `message` como toast tras el próximo st.rerun()."""
    st.session_state["_flash"] = message


def show_flash() -> None:
    if message := st.session_state.pop("_flash", None):
        st.toast(message, icon=":material/check_circle:")


def _remember(widget_key: str) -> None:
    st.session_state[f"_{widget_key}"] = st.session_state[widget_key]


def page_header(viewer: Viewer, title: str) -> tuple[str, str]:
    """Título + selector de mes. Devuelve (mes, owner): las compras siempre son las del viewer.

    La selección se guarda en una clave propia (`_month`) porque Streamlit borra el estado
    de un widget al cambiar a una página donde no se dibuja.
    """
    # Otras páginas piden mostrar un mes con "goto_month".
    if goto := st.session_state.pop("goto_month", None):
        st.session_state["_month"] = goto

    months = last_months(24)[::-1]
    remembered = st.session_state.get("_month")
    if remembered and remembered not in months:  # p. ej. una compra antigua recién guardada
        months = sorted({*months, remembered}, reverse=True)
    st.session_state["month"] = remembered or months[0]

    head, picker = st.columns([3, 1], vertical_alignment="bottom")
    month = picker.selectbox(
        "Mes",
        months,
        format_func=month_label,
        key="month",
        label_visibility="collapsed",
        on_change=_remember,
        args=("month",),
    )
    st.session_state["_month"] = month
    head.title(f"{title} · {month_label(month).lower()}")
    return month, viewer.user_id
