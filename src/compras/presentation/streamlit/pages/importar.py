from datetime import datetime

import streamlit as st

from compras import bootstrap, settings
from compras.application import imports
from compras.domain.errors import UnsupportedFile, ValidationError
from compras.domain.periods import month_key
from compras.presentation.streamlit.components.files import draft_warnings, show_attachment
from compras.presentation.streamlit.components.forms import form_options, purchase_form
from compras.presentation.streamlit.components.layout import flash
from compras.presentation.streamlit.components.session import current_viewer

# Los borradores son trabajo en curso de cada usuario: aquí nadie ve los de otros.
viewer = current_viewer()

st.title("Importar facturas")


def process(files: list[tuple[str, str | None, bytes]]) -> None:
    """Guarda y extrae cada archivo; deja seleccionado el primero para revisarlo."""
    created, errors = [], []
    storage, extractor = bootstrap.file_storage(), bootstrap.invoice_extractor()
    with bootstrap.unit_of_work() as uow:
        for name, content_type, raw in files:
            with st.spinner(f"Extrayendo datos de {name}…"):
                try:
                    att = imports.store_upload(
                        uow, storage, extractor, name, content_type, raw, owner_id=viewer.user_id
                    )
                    created.append(att.id)
                except UnsupportedFile as e:
                    errors.append(str(e))
    st.session_state["upload_no"] = st.session_state.get("upload_no", 0) + 1  # vacía el uploader
    st.session_state["upload_errors"] = errors
    if created:
        st.session_state["draft_id"] = created[0]
        flash(f"{len(created)} archivo(s) listo(s) para revisar")
    st.rerun()


upload_tab, camera_tab = st.tabs([":material/upload_file: Subir archivos", ":material/photo_camera: Tomar foto"])

with upload_tab:
    uploads = st.file_uploader(
        "Fotos de recibos, facturas en PDF o emails guardados (.eml)",
        type=["jpg", "jpeg", "png", "gif", "webp", "pdf", "eml"],
        accept_multiple_files=True,
        key=f"uploader-{st.session_state.get('upload_no', 0)}",
    )
    if st.button("Procesar archivos", type="primary", disabled=not uploads, icon=":material/auto_awesome:"):
        process([(f.name, f.type, f.getvalue()) for f in uploads])

with camera_tab:
    photo = st.camera_input("Fotografía el recibo", key=f"camera-{st.session_state.get('upload_no', 0)}")
    if st.button("Procesar foto", type="primary", disabled=photo is None, icon=":material/auto_awesome:"):
        process([(f"foto-{datetime.now():%Y%m%d-%H%M%S}.jpg", "image/jpeg", photo.getvalue())])

for error in st.session_state.pop("upload_errors", []):
    st.error(error, icon=":material/error:")

if settings.EXTRACTOR == "local":
    st.info(
        "Extractor **local**: solo lee el texto de PDFs digitales y emails. "
        "Configura `ANTHROPIC_API_KEY` para leer fotos y PDFs escaneados con Claude.",
        icon=":material/info:",
    )

st.divider()
st.subheader("Pendientes de revisar")

with bootstrap.unit_of_work() as uow:
    drafts = imports.drafts(uow, owner_id=viewer.user_id)
    if not drafts:
        st.caption("No hay archivos pendientes.")
        st.stop()

    ids = [d.id for d in drafts]
    labels = {
        d.id: f"#{d.id} · {d.original_name} · {(d.extracted or {}).get('vendor') or 'sin comercio detectado'}"
        for d in drafts
    }
    if st.session_state.get("draft_id") not in ids:
        st.session_state["draft_id"] = ids[0]
    draft_id = st.selectbox("Archivo", ids, format_func=labels.get, key="draft_id")
    att = imports.get_draft(uow, draft_id, owner_id=viewer.user_id)
    if att is None:  # descartado o confirmado en otra pestaña
        st.rerun()

    preview, form = st.columns([2, 3], gap="large")
    with preview:
        draft_warnings(uow, att)
        show_attachment(att)
        if st.button("Descartar archivo", icon=":material/delete:"):
            imports.discard_draft(uow, bootstrap.file_storage(), att)
            flash(f"{att.original_name} descartado")
            st.rerun()

    with form:
        st.caption("Revisa y corrige los datos extraídos antes de guardar.")
        options = form_options(viewer)
        values, items = imports.draft_values(att, options["categories"])
        submitted = purchase_form(f"draft-{att.id}", values, items, submit_label="Confirmar compra", **options)
        if submitted:
            try:
                purchase = imports.confirm_draft(uow, att, *submitted)
            except ValidationError as e:
                st.error(str(e), icon=":material/error:")
            else:
                st.session_state["goto_month"] = month_key(purchase.purchase_date)
                flash(f"Compra en {purchase.vendor} registrada")
                st.rerun()
