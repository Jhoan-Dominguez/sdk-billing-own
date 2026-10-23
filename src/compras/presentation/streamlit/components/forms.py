"""Formulario de compra (alta, edición y confirmación de borradores)."""

from datetime import date

import pandas as pd
import streamlit as st

from compras import bootstrap
from compras.application import categories as category_service
from compras.application import users as user_service
from compras.domain.auth import Viewer
from compras.domain.catalog import CURRENCIES, DEFAULT_CATEGORIES, FALLBACK_CATEGORY, PAYMENT_METHODS
from compras.presentation.streamlit.components.formatting import to_float
from compras.settings import DEFAULT_CURRENCY

ITEM_COLUMNS = ["description", "quantity", "unit_price", "line_total"]


def form_options(viewer: Viewer) -> dict:
    """Categorías disponibles y preferencias del usuario para `purchase_form`."""
    with bootstrap.unit_of_work() as uow:
        return {
            "categories": category_service.names(uow, owner_id=viewer.user_id),
            "defaults": user_service.form_defaults(user_service.get(uow, viewer.user_id)),
        }


def purchase_form(
    key: str,
    values: dict | None = None,
    items: list[dict] | None = None,
    submit_label: str = "Guardar compra",
    categories: list[str] | None = None,
    defaults: dict | None = None,
) -> tuple[dict, list[dict]] | None:
    """Pinta el formulario y devuelve (valores, líneas) al enviarlo, o None.

    `key` debe ser único por registro: Streamlit conserva el estado de los widgets
    por clave, así que cambiarla es la forma de reiniciar el formulario.
    `categories` y `defaults` (currency, payment_method, category) vienen de
    `form_options(viewer)`; los valores de `values` tienen prioridad sobre `defaults`.
    """
    v = values or {}
    d = defaults or {}
    category_options = list(categories or DEFAULT_CATEGORIES)
    current_category = v.get("category") or d.get("category")
    if current_category and current_category not in category_options:
        category_options.insert(0, current_category)  # p. ej. una categoría ya eliminada
    with st.form(key, enter_to_submit=False):
        c1, c2, c3 = st.columns(3)
        purchase_date = c1.date_input("Fecha *", value=v.get("purchase_date") or date.today(), format="DD/MM/YYYY")
        vendor = c2.text_input("Comercio *", value=v.get("vendor") or "")
        category = c3.selectbox(
            "Categoría",
            category_options,
            index=category_options.index(current_category)
            if current_category
            else (category_options.index(FALLBACK_CATEGORY) if FALLBACK_CATEGORY in category_options else 0),
        )

        c1, c2, c3 = st.columns(3)
        invoice_number = c1.text_input("N.º de factura", value=v.get("invoice_number") or "")
        vendor_tax_id = c2.text_input("ID fiscal del comercio", value=v.get("vendor_tax_id") or "")
        payment_method = c3.selectbox(
            "Método de pago",
            PAYMENT_METHODS,
            index=PAYMENT_METHODS.index(payment)
            if (payment := v.get("payment_method") or d.get("payment_method")) in PAYMENT_METHODS
            else None,
            placeholder="Sin especificar",
        )

        c1, c2, c3, c4 = st.columns(4)
        currency = v.get("currency") or d.get("currency") or DEFAULT_CURRENCY
        currency_options = CURRENCIES if currency in CURRENCIES else [currency, *CURRENCIES]
        currency = c1.selectbox(
            "Moneda", currency_options, index=currency_options.index(currency), accept_new_options=True
        )
        money_kw = dict(min_value=0.0, step=0.01, format="%.2f")
        subtotal = c2.number_input("Subtotal", value=to_float(v.get("subtotal")), **money_kw)
        tax = c3.number_input("Impuestos", value=to_float(v.get("tax")), **money_kw)
        total = c4.number_input(
            "Total", value=to_float(v.get("total")), placeholder="Se calcula si lo dejas vacío", **money_kw
        )

        st.markdown("**Detalle de la compra**")
        items_df = pd.DataFrame(
            [{c: to_float(i.get(c)) if c != "description" else i.get(c) for c in ITEM_COLUMNS} for i in items or []],
            columns=ITEM_COLUMNS,
        ).astype({"description": "object", "quantity": "float", "unit_price": "float", "line_total": "float"})
        edited = st.data_editor(
            items_df,
            num_rows="dynamic",
            hide_index=True,
            key=f"{key}-items",
            column_config={
                "description": st.column_config.TextColumn("Descripción", width="large"),
                "quantity": st.column_config.NumberColumn("Cantidad", min_value=0, default=1.0),
                "unit_price": st.column_config.NumberColumn("Precio unitario", min_value=0, format="%.2f"),
                "line_total": st.column_config.NumberColumn(
                    "Total línea", min_value=0, format="%.2f", help="Vacío = cantidad × precio"
                ),
            },
        )
        notes = st.text_area("Notas", value=v.get("notes") or "", height=80)

        if not st.form_submit_button(submit_label, type="primary", icon=":material/save:"):
            return None

    return (
        {
            "purchase_date": purchase_date,
            "vendor": vendor,
            "category": category,
            "invoice_number": invoice_number,
            "vendor_tax_id": vendor_tax_id,
            "payment_method": payment_method,
            "currency": currency,
            "subtotal": subtotal,
            "tax": tax,
            "total": total,
            "notes": notes,
        },
        edited.to_dict("records"),
    )
