"""Análisis y comparativa del gasto de todos los clientes (roles con `sees_all`)."""

from collections import Counter, defaultdict
from decimal import Decimal

import altair as alt
import pandas as pd
import streamlit as st

from billing import bootstrap
from billing.application import purchases as purchase_service
from billing.application import users as user_service
from billing.domain import auth
from billing.domain.periods import last_months, month_bounds, month_key
from billing.presentation.streamlit.components.formatting import money, month_label
from billing.presentation.streamlit.components.profile import current_user
from billing.presentation.streamlit.components.session import current_viewer

viewer = current_viewer()
if not viewer.sees_all:  # la navegación ya la oculta; esto cubre accesos directos
    st.error("No tienes permiso para ver esta página.", icon=":material/block:")
    st.stop()

st.title("Comparativa de clientes")

PERIODS = {3: "3 meses", 6: "6 meses", 12: "12 meses"}
period, currency_slot = st.columns([1, 1], vertical_alignment="bottom")
n_months = period.segmented_control(
    "Periodo", list(PERIODS), format_func=PERIODS.get, default=6, key="cmp_period", required=True
)
months = last_months(n_months)
start, end = month_bounds(months[0])[0], month_bounds(months[-1])[1]

with bootstrap.unit_of_work() as uow:
    users = user_service.list_users(uow, role=auth.CUSTOMER)
    # Los gráficos agrupan por nombre: si dos clientes se llaman igual se distinguen por usuario.
    repeated = {n for n, c in Counter(u.display_name for u in users).items() if c > 1}
    clients = {
        u.id: f"{u.display_name} ({u.username})" if u.display_name in repeated else u.display_name for u in users
    }
    purchases = [p for p in purchase_service.between(uow, start, end, owner_id=None) if p.owner_id in clients]

if not clients:
    st.info("Todavía no hay clientes registrados (aparecen al iniciar sesión por primera vez).")
    st.stop()

currencies = sorted({p.currency for p in purchases})
if not currencies:
    st.info(f"Ningún cliente tiene compras en los últimos {PERIODS[n_months]}.", icon=":material/info:")
    st.stop()

# Las monedas nunca se suman entre sí: se compara una a la vez.
currency = currency_slot.segmented_control(
    "Moneda",
    currencies,
    default=preferred if (preferred := user_service.currency(current_user(viewer))) in currencies else currencies[0],
    key=f"cmp_currency-{'-'.join(currencies)}",
    required=True,
)
rows = [p for p in purchases if p.currency == currency]

# --- Agregados por cliente ---------------------------------------------------

by_client_month: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
counts: Counter = Counter()
categories: dict[str, Counter] = defaultdict(Counter)
for p in rows:
    by_client_month[p.owner_id][month_key(p.purchase_date)] += p.total
    counts[p.owner_id] += 1
    categories[p.owner_id][p.category] += p.total

totals = {uid: sum(by_client_month[uid].values(), Decimal(0)) for uid in clients}
active = [uid for uid in clients if counts[uid]]
grand_total = sum(totals.values(), Decimal(0))
top = max(active, key=totals.get, default=None)

cols = st.columns(4)
cols[0].metric("Clientes con compras", f"{len(active)} de {len(clients)}", border=True)
cols[1].metric(f"Gasto total ({currency})", money(grand_total, currency), border=True)
cols[2].metric(
    "Promedio por cliente activo",
    money(grand_total / len(active), currency) if active else "—",
    border=True,
)
cols[3].metric("Mayor gasto", clients[top] if top else "—", border=True)

if not active:
    st.info(f"Ningún cliente tiene compras en {currency} en este periodo.", icon=":material/info:")
    st.stop()

# --- Gráficos ----------------------------------------------------------------

left, right = st.columns([2, 3], gap="large")
with left:
    st.subheader("Gasto por cliente")
    ranking = pd.DataFrame([{"Cliente": clients[uid], "Total": float(totals[uid])} for uid in active])
    st.bar_chart(ranking, x="Cliente", y="Total", horizontal=True, sort="-Total", height=max(160, 40 * len(active)))

with right:
    st.subheader("Gasto mensual")
    labels = [month_label(m) for m in months]
    heat = pd.DataFrame(
        [
            {
                "Cliente": clients[uid],
                "Mes": month_label(m),
                "Total": float(by_client_month[uid].get(m, 0)),
            }
            for uid in active
            for m in months
        ]
    )
    order = [clients[uid] for uid in sorted(active, key=lambda uid: -totals[uid])]
    chart = (
        alt.Chart(heat)
        .mark_rect(cornerRadius=3, stroke="transparent", strokeWidth=2)
        .encode(
            x=alt.X("Mes:O", sort=labels, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Cliente:N", sort=order, title=None),
            color=alt.Color("Total:Q", title=currency),
            tooltip=[
                alt.Tooltip("Cliente:N"),
                alt.Tooltip("Mes:O"),
                alt.Tooltip("Total:Q", format=",.2f", title=f"Total ({currency})"),
            ],
        )
        .properties(height=max(160, 36 * len(active)))
    )
    st.altair_chart(chart, width="stretch")

# --- Tabla comparativa -------------------------------------------------------

current_m, previous_m = months[-1], months[-2]
table = pd.DataFrame(
    [
        {
            "Cliente": name,
            "Compras": counts[uid],
            "Total": float(totals[uid]),
            "Ticket promedio": float(totals[uid] / counts[uid]) if counts[uid] else None,
            month_label(current_m): float(by_client_month[uid].get(current_m, 0)),
            month_label(previous_m): float(by_client_month[uid].get(previous_m, 0)),
            "Variación": (
                float(by_client_month[uid][current_m] / by_client_month[uid][previous_m] - 1)
                if by_client_month[uid].get(previous_m)
                else None
            ),
            "Categoría principal": categories[uid].most_common(1)[0][0] if categories[uid] else None,
        }
        for uid, name in clients.items()
    ]
).sort_values("Total", ascending=False)

st.subheader("Detalle por cliente")
money_col = st.column_config.NumberColumn(format="%.2f")
st.dataframe(
    table,
    hide_index=True,
    column_config={
        "Total": money_col,
        "Ticket promedio": money_col,
        month_label(current_m): money_col,
        month_label(previous_m): money_col,
        "Variación": st.column_config.NumberColumn(format="percent", help="Mes actual frente al anterior"),
    },
)
st.download_button(
    "Exportar CSV",
    table.to_csv(index=False).encode("utf-8"),
    file_name=f"comparativa-clientes-{currency}-{months[0]}-{months[-1]}.csv",
    mime="text/csv",
    icon=":material/download:",
)
