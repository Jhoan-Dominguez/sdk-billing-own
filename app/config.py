import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("COMPRAS_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DATABASE_URL = os.environ.get("COMPRAS_DATABASE_URL", f"sqlite:///{DATA_DIR / 'compras.db'}")

# "claude" usa la API de Anthropic para leer imágenes/PDFs/emails; "local" solo
# extrae texto de PDFs/emails y aplica expresiones regulares (sin red, menos preciso).
EXTRACTOR = os.environ.get(
    "COMPRAS_EXTRACTOR", "claude" if os.environ.get("ANTHROPIC_API_KEY") else "local"
)
CLAUDE_MODEL = os.environ.get("COMPRAS_CLAUDE_MODEL", "claude-opus-5-5")

DEFAULT_CURRENCY = os.environ.get("COMPRAS_MONEDA", "USD")

CATEGORIES = [
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
PAYMENT_METHODS = ["Efectivo", "Tarjeta de débito", "Tarjeta de crédito", "Transferencia", "Otro"]
