from datetime import date

import pandas as pd
import streamlit as st

from app import config
from app.db import SessionLocal
from app.models import Purchase
from app.services import (
    ValidationError,
    delete_purchase,
    last_months,
    month_bounds,
    month_key,
    purchase_values,
    purchases_between,
    totals_by,
    update_purchase,
)
from app.ui import flash, money, month_label, purchase_form, show_attachment, to_float

# --- Selección de mes --------------------------------------------------------

# Otras páginas piden mostrar un mes con "goto_month"; se aplica antes de crear el
# selector porque Streamlit no deja cambiar el valor de un widget ya creado.
if goto := st.session_state.pop("goto_month", None):
    st.session_state["month"] = goto

months = last_months(24)[::-1]
current = st.session_state.get("month")
if current and current not in months:  # p. ej. una compra antigua recién guardada
    months = sorted({*months, current}, reverse=True)

head, picker = st.columns([3, 1], vertical_alignment="bottom")
month = picker.selectbox("Mes", months, format_func=month_label, key="month", label_visibility="collapsed")
head.title(f"Resumen de {month_label(month).lower()}")

history_months = last_months(12, date.fromisoformat(f"{month}-01"))

with SessionLocal() as session:
    history = purchases_between(
        session, month_bounds(history_months[0])[0], month_bounds(history_months[-1])[1]
    )
    in_month = [p for p in history if month_key(p.purchase_date) == month]

    # --- Indicadores ---------------------------------------------------------

    by_month = totals_by(history, lambda p: month_key(p.purchase_date))
    month_totals = by_month.get(month, {})
    prev_totals = by_month.get(history_months[-2], {}) if len(history_months) > 1 else {}
    currencies = sorted({cur for totals in by_month.values() for cur in totals}) or [config.DEFAULT_CURRENCY]

    cols = st.columns(len(currencies) + 2)
    for col, cur in zip(cols, currencies):
        amount, prev = month_totals.get(cur), prev_totals.get(cur)
        col.metric(
            f"Gasto del mes ({cur})",
            money(amount, cur),
            delta=None if amount is None or prev is None else f"{(amount - prev):+,.2f} vs. mes anterior",
            delta_color="inverse",  # gastar más es "malo"
            chart_data=[to_float(by_month.get(m, {}).get(cur)) or 0 for m in history_months],
            chart_type="bar",
            border=True,
        )
    cols[-2].metric("Compras registradas", len(in_month), border=True)
    by_category = totals_by(in_month, lambda p: p.category)
    top = max(by_category.items(), key=lambda kv: sum(kv[1].values()), default=None)
    cols[-1].metric("Categoría principal", top[0] if top else "—", border=True)

    # --- Gráficos ------------------------------------------------------------

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Últimos 12 meses")
        chart = pd.DataFrame(
            [
                {"Mes": m, "Moneda": cur, "Total": to_float(by_month.get(m, {}).get(cur)) or 0.0}
                for m in history_months
                for cur in currencies
            ]
        )
        st.bar_chart(chart, x="Mes", y="Total", color="Moneda" if len(currencies) > 1 else None, height=280)
    with right:
        st.subheader("Por categoría")
        if by_category:
            cat_df = pd.DataFrame(
                [
                    {"Categoría": cat, "Moneda": cur, "Total": float(amount)}
                    for cat, totals in by_category.items()
                    for cur, amount in totals.items()
                ]
            )
            st.bar_chart(
                cat_df, x="Categoría", y="Total", color="Moneda" if len(currencies) > 1 else None,
                horizontal=True, sort="-Total", height=280,
            )
        else:
            st.caption("Sin compras este mes.")

    # --- Listado -------------------------------------------------------------

    st.subheader("Compras del mes")
    categories = st.pills(
        "Filtrar por categoría",
        sorted(by_category),
        selection_mode="multi",
        label_visibility="collapsed",
        key=f"filter-{month}",
    )
    shown = [p for p in in_month if not categories or p.category in categories]

    df = pd.DataFrame(
        [
            {
                "id": p.id,
                "Fecha": p.purchase_date,
                "Comercio": p.vendor,
                "Categoría": p.category,
                "Pago": p.payment_method,
                "Moneda": p.currency,
                "Total": float(p.total),
                "Origen": p.source,
                "Archivos": len(p.attachments),
            }
            for p in shown
        ],
        columns=["id", "Fecha", "Comercio", "Categoría", "Pago", "Moneda", "Total", "Origen", "Archivos"],
    )
    selection = st.dataframe(
        df,
        hide_index=True,
        column_order=[c for c in df.columns if c != "id"],
        column_config={
            "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Total": st.column_config.NumberColumn(format="%.2f"),
            "Archivos": st.column_config.NumberColumn(help="Imágenes, PDFs o emails adjuntos"),
        },
        on_select="rerun",
        selection_mode="single-row",
        key=f"table-{month}",
    )
    export, _ = st.columns([1, 3])
    export.download_button(
        "Exportar CSV",
        df.drop(columns="id").to_csv(index=False).encode("utf-8"),
        file_name=f"compras-{month}.csv",
        mime="text/csv",
        icon=":material/download:",
        disabled=df.empty,
    )

    if not shown:
        st.info("No hay compras registradas en este mes.", icon=":material/info:")
        st.stop()
    if not selection.selection.rows:
        st.caption("Selecciona una fila para ver el detalle, editarla o eliminarla.")
        st.stop()

    # --- Detalle de la compra seleccionada -----------------------------------

    p = session.get(Purchase, int(df.iloc[selection.selection.rows[0]]["id"]))

    # El diálogo queda abierto mientras "editing" apunte a la compra; así sobrevive a
    # los reruns completos (p. ej. al enviar el formulario) y no solo al del botón.
    def close_editor() -> None:
        st.session_state.pop("editing", None)

    @st.dialog("Editar compra", width="large", on_dismiss=close_editor)
    def edit_dialog(purchase_id: int) -> None:
        with SessionLocal() as s:
            purchase = s.get(Purchase, purchase_id)
            submitted = purchase_form(f"edit-{purchase_id}", *purchase_values(purchase))
            if submitted:
                try:
                    update_purchase(s, purchase, *submitted)
                except ValidationError as e:
                    st.error(str(e), icon=":material/error:")
                else:
                    close_editor()
                    st.session_state["goto_month"] = month_key(purchase.purchase_date)
                    flash("Compra actualizada")
                    st.rerun()

    st.divider()
    title, actions = st.columns([3, 1], vertical_alignment="center")
    title.subheader(f"{p.vendor} · {money(p.total, p.currency)}")
    with actions:
        b1, b2 = st.columns(2)
        if b1.button("Editar", icon=":material/edit:", width="stretch"):
            st.session_state["editing"] = p.id
        if st.session_state.get("editing") == p.id:
            edit_dialog(p.id)
        with b2.popover("Eliminar", icon=":material/delete:", width="stretch"):
            st.write("¿Eliminar esta compra y sus archivos?")
            if st.button("Sí, eliminar", type="primary"):
                vendor = p.vendor
                delete_purchase(session, p)
                flash(f"Compra en {vendor} eliminada")
                st.rerun()

    info, files = st.columns([3, 2], gap="large")
    with info:
        st.markdown(
            "\n".join(
                f"- **{label}:** {value}"
                for label, value in [
                    ("Fecha", p.purchase_date.strftime("%d/%m/%Y")),
                    ("Categoría", p.category),
                    ("N.º de factura", p.invoice_number),
                    ("ID fiscal", p.vendor_tax_id),
                    ("Método de pago", p.payment_method),
                    ("Subtotal", money(p.subtotal, p.currency) if p.subtotal is not None else None),
                    ("Impuestos", money(p.tax, p.currency) if p.tax is not None else None),
                    ("Origen", p.source),
                ]
                if value
            )
        )
        if p.items:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Descripción": i.description,
                            "Cantidad": float(i.quantity),
                            "Precio unitario": to_float(i.unit_price),
                            "Total": to_float(i.line_total),
                        }
                        for i in p.items
                    ]
                ),
                hide_index=True,
                column_config={
                    "Precio unitario": st.column_config.NumberColumn(format="%.2f"),
                    "Total": st.column_config.NumberColumn(format="%.2f"),
                },
            )
        if p.notes:
            st.caption(p.notes)
    with files:
        for att in p.attachments:
            with st.expander(f"{att.original_name} ({att.kind})", expanded=len(p.attachments) == 1):
                show_attachment(att, height=450)
        if not p.attachments:
            st.caption("Compra registrada a mano, sin archivos.")
