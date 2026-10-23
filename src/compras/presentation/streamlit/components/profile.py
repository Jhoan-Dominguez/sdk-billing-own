"""Usuario actual y su avatar."""

import base64
import html

import streamlit as st

from compras import bootstrap
from compras.application import users as user_service
from compras.domain.auth import Viewer
from compras.domain.models import User


def current_user(viewer: Viewer) -> User | None:
    with bootstrap.unit_of_work() as uow:
        return user_service.get(uow, viewer.user_id)


def initials(name: str) -> str:
    parts = [p for p in name.split() if p[:1].isalpha()]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def avatar(user: User | None, name: str, size: int = 48) -> None:
    """Avatar del usuario; sin imagen, un círculo con sus iniciales."""
    raw = user_service.read_avatar(bootstrap.file_storage(), user)
    if raw:
        st.html(
            f'<img src="data:image/png;base64,{base64.b64encode(raw).decode()}" alt="Avatar" '
            f'style="width:{size}px;height:{size}px;border-radius:50%;object-fit:cover;display:block">'
        )
        return
    st.html(
        f'<div aria-hidden="true" style="width:{size}px;height:{size}px;border-radius:50%;'
        f"display:grid;place-items:center;background:#3d6fd9;color:#fff;font-weight:600;"
        f'font-size:{size // 2.6:.0f}px">{html.escape(initials(name))}</div>'
    )
