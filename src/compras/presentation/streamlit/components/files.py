"""Vista previa de archivos adjuntos y avisos de los borradores."""

import streamlit as st

from compras import bootstrap
from compras.application import imports
from compras.domain.files import KIND_IMAGE, KIND_PDF
from compras.domain.models import Attachment
from compras.domain.ports.repositories import UnitOfWork


def show_attachment(att: Attachment, height: int = 600) -> None:
    """Vista previa del archivo original más botón de descarga."""
    try:
        raw = imports.read_file(bootstrap.file_storage(), att)
    except FileNotFoundError:
        st.error(f"No se encontró el archivo {att.original_name}.")
        return

    if att.kind == KIND_IMAGE:
        st.image(raw, width="stretch")
    elif att.kind == KIND_PDF:
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


def draft_warnings(uow: UnitOfWork, att: Attachment) -> None:
    if att.extraction_error:
        st.warning(att.extraction_error, icon=":material/warning:")
    if duplicates := imports.find_duplicates(uow, att):
        refs = ", ".join(f"compra #{d.purchase_id}" if d.purchase_id else f"borrador #{d.id}" for d in duplicates)
        st.warning(f"Este archivo ya se subió antes ({refs}).", icon=":material/content_copy:")
