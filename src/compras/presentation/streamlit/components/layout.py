"""Estilos, avisos entre reruns y el encabezado con filtros de mes/usuario."""

from pathlib import Path

import streamlit as st

from compras import bootstrap
from compras.application import users as user_service
from compras.domain.auth import Viewer
from compras.domain.periods import last_months
from compras.presentation.streamlit.components.formatting import month_label

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


def page_header(viewer: Viewer, title: str) -> tuple[str, str | None, dict[str, str]]:
    """Título + selector de mes (+ de usuario para quien ve todo). Devuelve (mes, owner, usuarios).

    `owner` ya pasó por `viewer.owner_filter`: un cliente siempre recibe su propio id.
    La selección se guarda en claves propias (`_month`, `_summary_user`) porque Streamlit
    borra el estado de un widget al cambiar a una página donde no se dibuja.
    """
    # Otras páginas piden mostrar un mes con "goto_month".
    if goto := st.session_state.pop("goto_month", None):
        st.session_state["_month"] = goto

    months = last_months(24)[::-1]
    remembered = st.session_state.get("_month")
    if remembered and remembered not in months:  # p. ej. una compra antigua recién guardada
        months = sorted({*months, remembered}, reverse=True)
    st.session_state["month"] = remembered or months[0]

    users: dict[str, str] = {}
    if viewer.sees_all:
        with bootstrap.unit_of_work() as uow:
            users = {u.id: u.display_name for u in user_service.list_users(uow)}
        if st.session_state.get("_summary_user") not in users:
            st.session_state["_summary_user"] = None
        st.session_state["summary_user"] = st.session_state["_summary_user"]
        head, user_picker, picker = st.columns([3, 1.2, 1], vertical_alignment="bottom")
    else:
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
    selected = None
    if users:
        selected = user_picker.selectbox(
            "Usuario",
            [None, *users],
            format_func=lambda uid: "Todos los usuarios" if uid is None else users.get(uid, uid),
            key="summary_user",
            label_visibility="collapsed",
            on_change=_remember,
            args=("summary_user",),
        )
    owner = viewer.owner_filter(selected)
    head.title(f"{title} · {month_label(month).lower()}")
    if viewer.sees_all:
        head.caption(f"Compras de {users.get(owner, owner)}" if owner else "Compras de todos los usuarios")
    return month, owner, users
