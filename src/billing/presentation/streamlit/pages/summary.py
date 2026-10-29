"""Resumen general del mes: indicadores y gráficos. El detalle está en "Tabla resumen"."""

from collections import Counter
from datetime import date

import pandas as pd
import streamlit as st

from billing import bootstrap
from billing.application import purchases as purchase_service
from billing.application import users as user_service
from billing.application.reports import totals_by
from billing.domain.periods import last_months, month_bounds, month_key
from billing.presentation.streamlit.components import forecast
from billing.presentation.streamlit.components.formatting import money, month_label, to_float
from billing.presentation.streamlit.components.layout import page_header
from billing.presentation.streamlit.components.profile import current_user
from billing.presentation.streamlit.components.session import current_viewer

CARD_HEIGHT = 380  # todas las tarjetas de gráfico miden lo mismo
CHART_HEIGHT = 290

viewer = current_viewer()
month, owner = page_header(viewer, "Resumen general")
history_months = last_months(12, date.fromisoformat(f"{month}-01"))
previous_month = history_months[-2]

with bootstrap.unit_of_work() as uow:
    history = purchase_service.between(
        uow, month_bounds(history_months[0])[0], month_bounds(history_months[-1])[1], owner_id=owner
    )
    month_rows = [
        {
            "category": p.category,
            "payment": p.payment_method or "Sin especificar",
            "vendor": p.vendor,
            "currency": p.currency,
            "total": float(p.total),
        }
        for p in history
        if month_key(p.purchase_date) == month
    ]
    previous_count = sum(1 for p in history if month_key(p.purchase_date) == previous_month)
    by_month = totals_by(history, lambda p: month_key(p.purchase_date))

# La moneda preferida del usuario va primero; sin datos, se muestra solo esa.
preferred = user_service.currency(current_user(viewer))
currencies = sorted({cur for totals in by_month.values() for cur in totals}, key=lambda c: (c != preferred, c)) or [
    preferred
]
multi_currency = len(currencies) > 1

# --- Indicadores (todas las tarjetas con la misma altura) ---------------------

month_totals, prev_totals = by_month.get(month, {}), by_month.get(previous_month, {})
categories = Counter(r["category"] for r in month_rows)
vendors = Counter(r["vendor"] for r in month_rows)

cards = st.columns(len(currencies) + 3)
for card, cur in zip(cards, currencies, strict=False):
    amount, prev = month_totals.get(cur), prev_totals.get(cur)
    card.metric(
        f"Gasto del mes ({cur})",
        money(amount, cur),
        delta=None if amount is None or prev is None else f"{(amount - prev):+,.2f} vs. mes anterior",
        delta_color="inverse",  # gastar más es "malo"
        icon=":material/payments:",
        border=True,
        height="stretch",
    )
cards[-3].metric(
    "Compras registradas",
    len(month_rows),
    delta=f"{len(month_rows) - previous_count:+d} vs. mes anterior" if previous_count else None,
    delta_color="off",
    icon=":material/receipt_long:",
    border=True,
    height="stretch",
)
cards[-2].metric(
    "Categoría principal",
    categories.most_common(1)[0][0] if categories else "—",
    help="La categoría con más compras en el mes",
    icon=":material/category:",
    border=True,
    height="stretch",
)
cards[-1].metric(
    "Comercio más frecuente",
    vendors.most_common(1)[0][0] if vendors else "—",
    icon=":material/storefront:",
    border=True,
    height="stretch",
)

# --- Proyección (solo en el mes en curso) ---------------------------------------

if month == month_key(date.today()):
    forecast.render(owner, {m: {c: float(v) for c, v in t.items()} for m, t in by_month.items()}, preferred)

# --- Gráficos: cuadrícula 2 × 2 de barras del mismo tamaño -------------------


def grouped(key: str, label: str, top: int | None = None) -> pd.DataFrame:
    """Total del mes por `key` y moneda (las monedas nunca se suman entre sí)."""
    df = pd.DataFrame(month_rows, columns=["category", "payment", "vendor", "currency", "total"])
    out = df.groupby([key, "currency"], as_index=False)["total"].sum()
    if top:
        keep = out.groupby(key)["total"].sum().nlargest(top).index
        out = out[out[key].isin(keep)]
    return out.rename(columns={key: label, "currency": "Moneda", "total": "Total"})


def bar_card(container, title: str, df: pd.DataFrame, x: str, horizontal: bool = True) -> None:
    with container.container(border=True, height=CARD_HEIGHT):
        st.subheader(title)
        if df.empty or not df["Total"].any():
            st.caption("Sin compras en este periodo.")
            return
        st.bar_chart(
            df,
            x=x,
            y="Total",
            color="Moneda" if multi_currency else None,
            stack=False if multi_currency else None,  # barras agrupadas: no suma monedas
            horizontal=horizontal,
            sort="-Total" if horizontal else False,  # los meses van en orden cronológico
            x_label="",
            y_label="",
            height=CHART_HEIGHT,
        )


monthly = pd.DataFrame(
    [
        {"Mes": month_label(m), "Moneda": cur, "Total": to_float(by_month.get(m, {}).get(cur)) or 0.0}
        for m in history_months
        for cur in currencies
    ]
)

top_left, top_right = st.columns(2, gap="medium")
bar_card(top_left, "Gasto por mes", monthly, "Mes", horizontal=False)
bar_card(top_right, "Gasto por categoría", grouped("category", "Categoría"), "Categoría")

bottom_left, bottom_right = st.columns(2, gap="medium")
bar_card(bottom_left, "Gasto por método de pago", grouped("payment", "Método"), "Método")
bar_card(bottom_right, "Comercios con más gasto", grouped("vendor", "Comercio", top=8), "Comercio")

st.caption(":material/table_view: El detalle de cada compra está en **Tabla resumen**.")
