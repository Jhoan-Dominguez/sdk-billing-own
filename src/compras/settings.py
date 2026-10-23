"""Configuración leída del entorno una vez, al importar el paquete.

Lee `.env` del directorio de trabajo (el mismo que usa docker compose); las variables
ya definidas en el entorno tienen prioridad.
"""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

env = os.environ.get

# --- Archivos -----------------------------------------------------------------

DATA_DIR = Path(env("COMPRAS_DATA_DIR", Path.cwd() / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
# Adaptador de archivos (compras/bootstrap.py): "local" (disco). En AWS: "s3".
STORAGE_BACKEND = env("COMPRAS_STORAGE", "local")

# --- Base de datos ------------------------------------------------------------

# Adaptador de persistencia (compras/bootstrap.py). "sql" = SQLAlchemy con cualquier
# URL que soporte (hoy PostgreSQL). Otros motores se añaden como nuevos adaptadores.
PERSISTENCE_BACKEND = env("COMPRAS_PERSISTENCE", "sql")


def _database_url() -> str:
    if url := env("COMPRAS_DATABASE_URL"):
        return url
    # Fuera de Docker se conecta al Postgres del compose publicado en DB_PORT.
    user = env("POSTGRES_USER", "compras")
    password = env("POSTGRES_PASSWORD", "")
    host = env("POSTGRES_HOST", "localhost")
    port = env("POSTGRES_PORT") or env("DB_PORT", "5433")
    db = env("POSTGRES_DB", "compras")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


DATABASE_URL = _database_url()

# --- Identidad (Keycloak) -----------------------------------------------------

# URL pública (la que ve el navegador) e interna (desde el contenedor de la app).
KEYCLOAK_REALM = env("KEYCLOAK_REALM", "compras")
KEYCLOAK_PUBLIC_URL = env("KEYCLOAK_PUBLIC_URL", f"http://localhost:{env('KEYCLOAK_PORT', '8180')}")
KEYCLOAK_INTERNAL_URL = env("KEYCLOAK_INTERNAL_URL", KEYCLOAK_PUBLIC_URL)
KEYCLOAK_CLIENT_ID = env("KEYCLOAK_CLIENT_ID", "compras-app")
# Cuenta de servicio con la que la app gestiona la cuenta del propio usuario.
KEYCLOAK_ADMIN_API_CLIENT_ID = env("KEYCLOAK_ADMIN_API_CLIENT_ID", "compras-admin-api")
KEYCLOAK_ADMIN_API_SECRET = env("KEYCLOAK_ADMIN_API_SECRET", "")
# Raíz pública de la app: a ella vuelve Keycloak tras cambiar contraseña o activar 2FA.
APP_PUBLIC_URL = env("AUTH_REDIRECT_URI", "http://localhost:8501/oauth2callback").removesuffix("/oauth2callback")

# --- Extracción de facturas ---------------------------------------------------

# "claude" usa la API de Anthropic para leer imágenes/PDFs/emails; "local" solo
# extrae texto de PDFs/emails y aplica expresiones regulares (sin red, menos preciso).
EXTRACTOR = env("COMPRAS_EXTRACTOR") or ("claude" if env("ANTHROPIC_API_KEY") else "local")
CLAUDE_MODEL = env("COMPRAS_CLAUDE_MODEL", "claude-opus-5-5")

DEFAULT_CURRENCY = env("COMPRAS_MONEDA", "USD")
