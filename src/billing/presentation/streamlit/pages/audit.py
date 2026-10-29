"""Auditoría (administradores): quién hizo qué sobre qué cuenta y cuándo."""

import json

import pandas as pd
import streamlit as st

from billing import bootstrap
from billing.application.admin import audit
from billing.domain.admin import ACTION_LABELS
from billing.presentation.streamlit.components.admin import require_manager

viewer = require_manager()
st.title("Auditoría")
st.caption("Acciones de los administradores sobre las cuentas y los datos. Las entradas no se pueden editar ni borrar.")

action_col, search_col = st.columns([1, 2], vertical_alignment="bottom")
action = action_col.selectbox(
    "Acción",
    [None, *ACTION_LABELS],
    format_func=lambda a: "Todas las acciones" if a is None else ACTION_LABELS[a],
    label_visibility="collapsed",
)
query = search_col.text_input("Buscar", placeholder="Administrador o cuenta afectada", label_visibility="collapsed")

with bootstrap.unit_of_work() as uow:
    entries = audit.entries(uow, action=action, limit=1000)

needle = query.strip().lower()
entries = [
    e for e in entries if not needle or needle in e.actor_label.lower() or needle in (e.target_label or "").lower()
]
if not entries:
    st.info("No hay acciones registradas con esos filtros.", icon=":material/info:")
    st.stop()

df = pd.DataFrame(
    [
        {
            "Fecha": e.created_at,
            "Administrador": e.actor_label,
            "Acción": ACTION_LABELS.get(e.action, e.action),
            "Cuenta": e.target_label or "—",
            "Detalle": json.dumps(e.details, ensure_ascii=False) if e.details else "",
        }
        for e in entries
    ]
)
st.dataframe(
    df,
    hide_index=True,
    column_config={"Fecha": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm:ss")},
)
st.download_button(
    "Exportar CSV",
    df.to_csv(index=False).encode("utf-8"),
    file_name="auditoria.csv",
    mime="text/csv",
    icon=":material/download:",
)
