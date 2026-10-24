"""Vista previa de archivos adjuntos y avisos de los borradores."""

import streamlit as st

from billing import bootstrap
from billing.application import imports
from billing.domain.bank import transaction_label
from billing.domain.catalog import DOCUMENT_BANK_NOTIFICATION
from billing.domain.files import KIND_IMAGE, KIND_PDF
from billing.domain.models import Attachment
from billing.domain.ports.repositories import UnitOfWork
from billing.presentation.streamlit.components.formatting import money


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
    if similar := imports.similar_purchases(uow, att):
        refs = ", ".join(f"#{p.id} {p.vendor} {money(p.total, p.currency)} ({p.purchase_date:%d/%m})" for p in similar)
        st.warning(
            f"Ya tienes una compra con el mismo total en fechas cercanas: {refs}. "
            "Puede ser el mismo pago (factura y alerta del banco).",
            icon=":material/difference:",
        )


def draft_label(att: Attachment) -> str:
    vendor = (att.extracted or {}).get("vendor") or "sin comercio detectado"
    icon = ":material/account_balance:" if att.document_type == DOCUMENT_BANK_NOTIFICATION else ":material/receipt:"
    origin = " · buzón" if att.mailbox_id else ""
    return f"{icon} #{att.id} · {att.original_name} · {vendor}{origin}"


def extraction_info(att: Attachment) -> None:
    """Qué se importó y cómo: tipo de documento, banco, método y modelo."""
    meta = att.extraction_meta or {}
    if att.document_type == DOCUMENT_BANK_NOTIFICATION:
        bank = meta.get("bank") or {}
        parts = [bank.get("bank") or "Banco", transaction_label(bank.get("transaction_type"))]
        if bank.get("card_last4"):
            parts.append(f"tarjeta/cuenta *{bank['card_last4']}")
        if bank.get("occurred_at_time"):
            parts.append(f"a las {bank['occurred_at_time']}")
        st.markdown(f":blue-badge[:material/account_balance: Notificación bancaria] {' · '.join(parts)}")
    else:
        st.markdown(":gray-badge[:material/receipt: Factura]")
    if meta.get("method") == "llm":
        seconds = (meta.get("duration_ms") or 0) / 1000
        st.caption(f"Leído con {meta.get('provider')} / `{meta.get('model')}` en {seconds:.1f} s.")
    elif meta:
        st.caption("Leído con reglas locales (sin LLM).")
    for warning in meta.get("warnings") or []:
        st.warning(warning, icon=":material/rule:")
