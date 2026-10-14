"""Componentes de Streamlit compartidos entre páginas."""

import math
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

from app import config
from app.db import init_db
from app.models import Attachment
from app.services import find_duplicates, read_attachment

CURRENCIES = ["USD", "EUR", "MXN", "COP", "PEN", "CLP", "ARS", "GTQ", "CRC", "DOP", "UYU", "BOB", "PYG"]
MONTH_NAMES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
               "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
ITEM_COLUMNS = ["description", "quantity", "unit_price", "line_total"]


@st.cache_resource
def ensure_db() -> bool:
    init_db()
    return True


def month_label(month: str) -> str:
    y, m = month.split("-")
    return f"{MONTH_NAMES[int(m) - 1].capitalize()} {y}"


def money(amount, currency: str = "") -> str:
    if amount is None:
        return "—"
    return f"{currency} {amount:,.2f}".strip()


def _num(value) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


# --- Mensajes entre reruns ---------------------------------------------------


def flash(message: str) -> None:
    """Muestra `message` como toast tras el próximo st.rerun()."""
    st.session_state["_flash"] = message


def show_flash() -> None:
    if message := st.session_state.pop("_flash", None):
        st.toast(message, icon=":material/check_circle:")


# --- Formulario de compra ----------------------------------------------------


def purchase_form(
    key: str, values: dict | None = None, items: list[dict] | None = None, submit_label: str = "Guardar compra"
) -> tuple[dict, list[dict]] | None:
    """Pinta el formulario y devuelve (valores, líneas) al enviarlo, o None.

    `key` debe ser único por registro: Streamlit conserva el estado de los widgets
    por clave, así que cambiarla es la forma de reiniciar el formulario.
    """
    v = values or {}
    with st.form(key, enter_to_submit=False):
        c1, c2, c3 = st.columns(3)
        purchase_date = c1.date_input(
            "Fecha *", value=v.get("purchase_date") or date.today(), format="DD/MM/YYYY"
        )
        vendor = c2.text_input("Comercio *", value=v.get("vendor") or "")
        category = c3.selectbox(
            "Categoría",
            config.CATEGORIES,
            index=config.CATEGORIES.index(v["category"]) if v.get("category") in config.CATEGORIES
            else config.CATEGORIES.index("Otros"),
        )

        c1, c2, c3 = st.columns(3)
        invoice_number = c1.text_input("N.º de factura", value=v.get("invoice_number") or "")
        vendor_tax_id = c2.text_input("ID fiscal del comercio", value=v.get("vendor_tax_id") or "")
        payment_method = c3.selectbox(
            "Método de pago",
            config.PAYMENT_METHODS,
            index=config.PAYMENT_METHODS.index(v["payment_method"])
            if v.get("payment_method") in config.PAYMENT_METHODS else None,
            placeholder="Sin especificar",
        )

        c1, c2, c3, c4 = st.columns(4)
        currency = v.get("currency") or config.DEFAULT_CURRENCY
        currency_options = CURRENCIES if currency in CURRENCIES else [currency, *CURRENCIES]
        currency = c1.selectbox(
            "Moneda", currency_options, index=currency_options.index(currency), accept_new_options=True
        )
        money_kw = dict(min_value=0.0, step=0.01, format="%.2f")
        subtotal = c2.number_input("Subtotal", value=_num(v.get("subtotal")), **money_kw)
        tax = c3.number_input("Impuestos", value=_num(v.get("tax")), **money_kw)
        total = c4.number_input(
            "Total", value=_num(v.get("total")), placeholder="Se calcula si lo dejas vacío", **money_kw
        )

        st.markdown("**Detalle de la compra**")
        items_df = pd.DataFrame(
            [{c: _num(i.get(c)) if c != "description" else i.get(c) for c in ITEM_COLUMNS} for i in items or []],
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


# --- Archivos ----------------------------------------------------------------


def show_attachment(att: Attachment, height: int = 600) -> None:
    """Vista previa del archivo original más botón de descarga."""
    try:
        raw = read_attachment(att)
    except FileNotFoundError:
        st.error(f"No se encontró el archivo {att.original_name} en disco.")
        return

    if att.kind == "imagen":
        st.image(raw, width="stretch")
    elif att.kind == "pdf":
        st.pdf(raw, height=height)
    elif att.extracted_text:
        with st.container(height=height):
            st.text(att.extracted_text)

    st.download_button(
        f"Descargar {att.original_name}",
        raw,
        file_name=att.original_name,
        mime=att.content_type,
        icon=":material/download:",
        key=f"dl-{att.id}",
    )


def draft_warnings(session, att: Attachment) -> None:
    if att.extraction_error:
        st.warning(att.extraction_error, icon=":material/warning:")
    duplicates = find_duplicates(session, att)
    if duplicates:
        refs = ", ".join(
            f"compra #{d.purchase_id}" if d.purchase_id else f"borrador #{d.id}" for d in duplicates
        )
        st.warning(f"Este archivo ya se subió antes ({refs}).", icon=":material/content_copy:")


def to_float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)
