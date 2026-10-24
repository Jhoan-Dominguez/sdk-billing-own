"""Valores de referencia del negocio (no dependen del entorno)."""

from billing.domain.files import KIND_EMAIL, KIND_IMAGE, KIND_PDF

# Categorías generales iniciales (la migración 0002 las crea en la base).
DEFAULT_CATEGORIES = [
    "Supermercado",
    "Restaurantes",
    "Servicios",
    "Transporte",
    "Salud",
    "Hogar",
    "Tecnología",
    "Educación",
    "Entretenimiento",
    "Otros",
]
# General y protegida: recibe las compras de las categorías que se borran.
FALLBACK_CATEGORY = "Otros"

PAYMENT_METHODS = ["Efectivo", "Tarjeta de débito", "Tarjeta de crédito", "Transferencia", "Otro"]

CURRENCIES = ["USD", "EUR", "MXN", "COP", "PEN", "CLP", "ARS", "GTQ", "CRC", "DOP", "UYU", "BOB", "PYG"]

# Origen de una compra: a mano, el tipo de archivo del que se extrajo o una
# notificación bancaria (correo subido o leído de un buzón IMAP).
SOURCE_MANUAL = "manual"
SOURCE_BANK = "bank"

# Tipo de documento de un borrador importado (Attachment.extraction_meta["document_type"]).
DOCUMENT_INVOICE = "invoice"
DOCUMENT_BANK_NOTIFICATION = "bank_notification"

# Etiquetas para mostrar el origen de una compra (Purchase.source).
SOURCE_LABELS = {
    SOURCE_MANUAL: "Manual",
    KIND_IMAGE: "Imagen",
    KIND_PDF: "PDF",
    KIND_EMAIL: "Correo",
    SOURCE_BANK: "Banco",
}
