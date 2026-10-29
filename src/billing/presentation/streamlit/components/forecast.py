"""Proyección del gasto del cliente (Resumen, mes en curso): cierre estimado del mes, los
próximos meses con su rango y si va por encima de lo habitual."""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from billing import bootstrap
from billing.application.forecasting import outlook as outlook_service
from billing.domain.periods import last_months, month_key
from billing.presentation.streamlit.components.formatting import money, month_label

HISTORY_MONTHS = 6


def _chart(item: outlook_service.Outlook, history: dict[str, dict[str, float]], current: str) -> alt.Chart:
    rows = [
        {"Mes": month_label(m), "orden": m, "Tipo": "Real", "Total": history.get(m, {}).get(item.currency, 0.0)}
        for m in last_months(HISTORY_MONTHS + 1)[:-1]
    ]
    bands = []
    if item.projection:
        p = item.projection
        rows.append({"Mes": month_label(current), "orden": current, "Tipo": "Gastado", "Total": p.spent})
        bands.append(
            {"Mes": month_label(current), "orden": current, "Previsto": p.expected, "Bajo": p.low, "Alto": p.high}
        )
    for f in item.upcoming:
        m = month_key(f.period)
        bands.append(
            {"Mes": month_label(m), "orden": m, "Previsto": float(f.p50), "Bajo": float(f.p10), "Alto": float(f.p90)}
        )
    order = [r["Mes"] for r in sorted([*rows, *bands], key=lambda r: r["orden"])]
    x = alt.X("Mes:N", sort=list(dict.fromkeys(order)), title=None)
    bars = (
        alt.Chart(pd.DataFrame(rows))
        .mark_bar(opacity=0.85)
        .encode(
            x=x,
            y=alt.Y("Total:Q", title=item.currency),
            color=alt.Color("Tipo:N", legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["Mes", "Tipo", alt.Tooltip("Total:Q", format=",.2f")],
        )
    )
    if not bands:
        return bars.properties(height=260)
    band_df = pd.DataFrame(bands)
    rule = alt.Chart(band_df).mark_rule(strokeWidth=2, opacity=0.6).encode(x=x, y="Bajo:Q", y2="Alto:Q")
    point = (
        alt.Chart(band_df)
        .mark_point(filled=True, size=70, shape="diamond")
        .encode(
            x=x,
            y="Previsto:Q",
            tooltip=[
                "Mes",
                alt.Tooltip("Previsto:Q", format=",.2f"),
                alt.Tooltip("Bajo:Q", title="P10", format=",.2f"),
                alt.Tooltip("Alto:Q", title="P90", format=",.2f"),
            ],
        )
    )
    return (bars + rule + point).properties(height=260)


def render(owner_id: str, history: dict[str, dict[str, float]], preferred: str) -> None:
    """`history` = {mes: {moneda: total}} de los últimos meses (lo que ya calculó el Resumen)."""
    with bootstrap.unit_of_work() as uow:
        items = outlook_service.outlook(uow, owner_id=owner_id)
    items = sorted(
        (i for i in items if i.projection or i.upcoming), key=lambda i: (i.currency != preferred, i.currency)
    )
    if not items:
        return
    current = month_key(date.today())
    for item in items:
        with st.container(border=True):
            st.subheader(f"Proyección ({item.currency})")
            cols = st.columns(3)
            p = item.projection
            if p:
                cols[0].metric(
                    "Cierre estimado del mes",
                    money(p.expected, item.currency),
                    help=f"Rango probable: {money(p.low, item.currency)} – {money(p.high, item.currency)}",
                    icon=":material/trending_up:",
                )
                cols[1].metric("Llevas gastado", money(p.spent, item.currency), icon=":material/payments:")
            if item.upcoming:
                nxt = item.upcoming[0]
                cols[2].metric(
                    f"Previsto para {month_label(month_key(nxt.period)).lower()}",
                    money(nxt.p50, item.currency),
                    help=f"Rango probable (80 %): {money(nxt.p10, item.currency)} – {money(nxt.p90, item.currency)}",
                    icon=":material/event_upcoming:",
                )
            if item.above_usual:
                st.warning(
                    f"Vas camino de gastar más de lo habitual este mes: el cierre estimado supera "
                    f"{money(item.current.p90, item.currency)}, el máximo previsto.",
                    icon=":material/warning:",
                )
            st.altair_chart(_chart(item, history, current), width="stretch")
            note = "Barras: gasto real. Rombos: previsión con su rango probable (80 %)."
            if (accuracy := item.accuracy) is not None:
                note += f" En tus meses ya cerrados, las previsiones acertaron un {accuracy:.0f} % en promedio."
            st.caption(note)
