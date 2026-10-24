"""Tabla resumen: compras del mes, su detalle y el alta de nuevas compras."""

import pandas as pd
import streamlit as st

from billing import bootstrap
from billing.application import purchases as purchase_service
from billing.domain.errors import ValidationError
from billing.domain.periods import month_key
from billing.presentation.streamlit.components.files import show_attachment
from billing.presentation.streamlit.components.formatting import money, to_float
from billing.presentation.streamlit.components.forms import form_options, purchase_form
from billing.presentation.streamlit.components.layout import flash, page_header
from billing.presentation.streamlit.components.session import current_viewer

viewer = current_viewer()
month, owner, _ = page_header(viewer, "Tabla resumen")
show_owner = viewer.sees_all and owner is None

# --- Diálogos -----------------------------------------------------------------
# Quedan abiertos mientras su clave en session_state esté puesta; así sobreviven a los
# reruns completos (p. ej. al enviar el formulario) y no solo al del botón.


def close_dialogs() -> None:
    st.session_state.pop("editing", None)
    st.session_state.pop("adding", None)


@st.dialog("Nueva compra", width="large", on_dismiss=close_dialogs)
def add_dialog() -> None:
    st.caption("Registra una compra a mano. Para fotos, PDFs o emails usa **Importar facturas**.")
    # Cambiar la clave del formulario lo deja en blanco tras guardar.
    form_no = st.session_state.setdefault("new_purchase_form", 0)
    submitted = purchase_form(f"new-purchase-{form_no}", **form_options(viewer))
    if submitted:
        try:
            with bootstrap.unit_of_work() as uow:
                purchase = purchase_service.create(uow, *submitted, owner_id=viewer.user_id)
        except ValidationError as e:
            st.error(str(e), icon=":material/error:")
        else:
            close_dialogs()
            st.session_state["new_purchase_form"] += 1
            st.session_state["goto_month"] = month_key(purchase.purchase_date)
            flash(f"Compra en {purchase.vendor} guardada ({purchase.currency} {purchase.total:,.2f})")
            st.rerun()


@st.dialog("Editar compra", width="large", on_dismiss=close_dialogs)
def edit_dialog(purchase_id: int) -> None:
    with bootstrap.unit_of_work() as uow:
        purchase = purchase_service.get(uow, purchase_id, owner_id=viewer.user_id)  # solo las propias
        if purchase is None:
            close_dialogs()
            st.rerun()
        submitted = purchase_form(
            f"edit-{purchase_id}",
            *purchase_service.form_values(purchase),
            categories=form_options(viewer)["categories"],
        )
        if submitted:
            try:
                purchase_service.update(uow, purchase, *submitted)
            except ValidationError as e:
                st.error(str(e), icon=":material/error:")
            else:
                close_dialogs()
                st.session_state["goto_month"] = month_key(purchase.purchase_date)
                flash("Compra actualizada")
                st.rerun()


if st.session_state.get("adding"):
    add_dialog()

with bootstrap.unit_of_work() as uow:
    in_month = purchase_service.in_month(uow, month, owner_id=owner)

    # --- Tabla ------------------------------------------------------------------

    categories = st.pills(
        "Filtrar por categoría",
        sorted({p.category for p in in_month}),
        selection_mode="multi",
        label_visibility="collapsed",
        key=f"filter-{month}-{owner}",
    )
    shown = [p for p in in_month if not categories or p.category in categories]

    df = pd.DataFrame(
        [
            {
                "id": p.id,
                "Cliente": p.owner.display_name,
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
        columns=[
            "id",
            "Cliente",
            "Fecha",
            "Comercio",
            "Categoría",
            "Pago",
            "Moneda",
            "Total",
            "Origen",
            "Archivos",
        ],
    )
    if not show_owner:
        df = df.drop(columns="Cliente")
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
        key=f"table-{month}-{owner}",  # la selección es por índice: no reusarla entre filtros
    )

    # --- Acciones bajo la tabla -------------------------------------------------

    add, export, _ = st.columns([1, 1, 3])
    if add.button("Agregar compra", type="primary", icon=":material/add:", width="stretch"):
        st.session_state.pop("editing", None)
        st.session_state["adding"] = True
        st.rerun()
    export.download_button(
        "Exportar CSV",
        df.drop(columns="id").to_csv(index=False).encode("utf-8"),
        file_name=f"compras-{month}.csv",
        mime="text/csv",
        icon=":material/download:",
        disabled=df.empty,
        width="stretch",
    )

    if not shown:
        st.info("No hay compras registradas en este mes.", icon=":material/info:")
        st.stop()
    if not selection.selection.rows:
        st.caption("Selecciona una fila para ver el detalle, editarla o eliminarla.")
        st.stop()

    # --- Detalle de la compra seleccionada --------------------------------------

    p = purchase_service.get(uow, int(df.iloc[selection.selection.rows[0]]["id"]), owner_id=owner)
    if p is None:
        st.stop()

    st.divider()
    title, actions = st.columns([3, 1], vertical_alignment="center")
    title.subheader(f"{p.vendor} · {money(p.total, p.currency)}")
    if not viewer.can_modify(p.owner_id):
        actions.caption(f":material/visibility: Solo lectura · compra de {p.owner.display_name}")
    else:
        b1, b2 = actions.columns(2)
        if b1.button("Editar", icon=":material/edit:", width="stretch"):
            st.session_state.pop("adding", None)
            st.session_state["editing"] = p.id
        if st.session_state.get("editing") == p.id:
            edit_dialog(p.id)
        with b2.popover("Eliminar", icon=":material/delete:", width="stretch"):
            st.write("¿Eliminar esta compra y sus archivos?")
            if st.button("Sí, eliminar", key="confirm-delete"):
                vendor = p.vendor
                purchase_service.delete(uow, bootstrap.file_storage(), p)
                flash(f"Compra en {vendor} eliminada")
                st.rerun()

    info, files = st.columns([3, 2], gap="large")
    with info:
        st.markdown(
            "\n".join(
                f"- **{label}:** {value}"
                for label, value in [
                    ("Cliente", p.owner.display_name if viewer.sees_all else None),
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
