import streamlit as st

from app.db import SessionLocal
from app.services import ValidationError, create_purchase, month_key
from app.ui import flash, purchase_form

st.title("Nueva compra")
st.caption("Registra una compra a mano. Para fotos, PDFs o emails usa **Importar facturas**.")

# Cambiar la clave del formulario lo deja en blanco tras guardar.
form_no = st.session_state.setdefault("new_purchase_form", 0)
submitted = purchase_form(f"new-purchase-{form_no}")

if submitted:
    values, items = submitted
    try:
        with SessionLocal() as session:
            purchase = create_purchase(session, values, items)
    except ValidationError as e:
        st.error(str(e), icon=":material/error:")
    else:
        st.session_state["new_purchase_form"] += 1
        st.session_state["goto_month"] = month_key(purchase.purchase_date)
        flash(f"Compra en {purchase.vendor} guardada ({purchase.currency} {purchase.total:,.2f})")
        st.rerun()
