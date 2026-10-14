"""Punto de entrada de la app: `streamlit run streamlit_app.py`."""

import streamlit as st

from app import config
from app.db import SessionLocal
from app.services import pending_drafts
from app.ui import ensure_db, show_flash

st.set_page_config(page_title="Registro de compras", page_icon=":material/receipt_long:", layout="wide")
ensure_db()

with SessionLocal() as session:
    pending = len(pending_drafts(session))

page = st.navigation(
    [
        st.Page("app_pages/resumen.py", title="Resumen mensual", icon=":material/dashboard:", default=True),
        st.Page("app_pages/nueva_compra.py", title="Nueva compra", icon=":material/add_shopping_cart:"),
        st.Page(
            "app_pages/importar.py",
            title=f"Importar facturas ({pending})" if pending else "Importar facturas",
            icon=":material/document_scanner:",
        ),
    ]
)

with st.sidebar:
    st.caption(
        f"Extractor de facturas: **{config.EXTRACTOR}**"
        + ("" if config.EXTRACTOR == "claude" else " · define `ANTHROPIC_API_KEY` para leer fotos")
    )

show_flash()
page.run()
