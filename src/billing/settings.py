"""Configuración leída del entorno una vez, al importar el paquete.

Lee `.env` del directorio de trabajo (el mismo que usa docker compose); las variables
ya definidas en el entorno tienen prioridad.
"""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

env = os.environ.get
# Las variables vacías en .env (VAR=) cuentan como no definidas: `env("X") or "defecto"`.

# --- Archivos -----------------------------------------------------------------

DATA_DIR = Path(env("BILLING_DATA_DIR", Path.cwd() / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
# Adaptador de archivos (billing/bootstrap.py): "local" (disco). En AWS: "s3".
STORAGE_BACKEND = env("BILLING_STORAGE", "local")

# --- Base de datos ------------------------------------------------------------

# Adaptador de persistencia (billing/bootstrap.py). "sql" = SQLAlchemy con cualquier
# URL que soporte (hoy PostgreSQL). Otros motores se añaden como nuevos adaptadores.
PERSISTENCE_BACKEND = env("BILLING_PERSISTENCE", "sql")


def _database_url() -> str:
    if url := env("BILLING_DATABASE_URL"):
        return url
    # Fuera de Docker se conecta al Postgres del compose publicado en DB_PORT.
    user = env("POSTGRES_USER", "billing")
    password = env("POSTGRES_PASSWORD", "")
    host = env("POSTGRES_HOST", "localhost")
    port = env("POSTGRES_PORT") or env("DB_PORT", "5433")
    db = env("POSTGRES_DB", "billing")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


DATABASE_URL = _database_url()

# --- Identidad (Keycloak) -----------------------------------------------------

# URL pública (la que ve el navegador) e interna (desde el contenedor de la app).
KEYCLOAK_REALM = env("KEYCLOAK_REALM", "billing")
KEYCLOAK_PUBLIC_URL = env("KEYCLOAK_PUBLIC_URL", f"http://localhost:{env('KEYCLOAK_PORT', '8180')}")
KEYCLOAK_INTERNAL_URL = env("KEYCLOAK_INTERNAL_URL", KEYCLOAK_PUBLIC_URL)
KEYCLOAK_CLIENT_ID = env("KEYCLOAK_CLIENT_ID", "billing-app")
# Secreto del cliente OIDC: lo usa también la reautenticación de acciones sensibles.
KEYCLOAK_CLIENT_SECRET = env("KEYCLOAK_CLIENT_SECRET", "")
# Cuenta de servicio con la que la app gestiona la cuenta del propio usuario.
KEYCLOAK_ADMIN_API_CLIENT_ID = env("KEYCLOAK_ADMIN_API_CLIENT_ID", "billing-admin-api")
KEYCLOAK_ADMIN_API_SECRET = env("KEYCLOAK_ADMIN_API_SECRET", "")
# Raíz pública de la app: a ella vuelve Keycloak tras cambiar contraseña o activar 2FA.
APP_PUBLIC_URL = env("AUTH_REDIRECT_URI", "http://localhost:8501/oauth2callback").removesuffix("/oauth2callback")

# --- Correo saliente -----------------------------------------------------------

# Adaptador (billing/bootstrap.py): "smtp" o "console" (solo escribe en el log).
MAILER_BACKEND = env("BILLING_MAILER") or "smtp"
# Fuera de Docker se usa el SMTP de Mailpit publicado en el host (MAILPIT_SMTP_PORT).
SMTP_HOST = env("SMTP_HOST") or "localhost"
SMTP_PORT = int(env("SMTP_PORT") or env("MAILPIT_SMTP_PORT", "1025"))
SMTP_FROM = env("SMTP_FROM") or "no-reply@billing.example.com"
SMTP_USER = env("SMTP_USER", "")
SMTP_PASSWORD = env("SMTP_PASSWORD", "")
SMTP_STARTTLS = (env("SMTP_STARTTLS") or "false").lower() == "true"
SMTP_SSL = (env("SMTP_SSL") or "false").lower() == "true"

# --- Secretos guardados ---------------------------------------------------------

# Clave Fernet con la que se cifran las contraseñas de los buzones IMAP.
SECRET_KEY = env("BILLING_SECRET_KEY", "")

# --- Agentes LLM ----------------------------------------------------------------

# Proveedor y modelo por defecto de todos los agentes (el admin puede cambiarlos por
# agente desde la app). Proveedor vacío = el primero con credenciales; "local" = sin LLM.
LLM_PROVIDER = env("BILLING_LLM_PROVIDER", "")
LLM_MODEL = env("BILLING_LLM_MODEL", "")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = env("OPENAI_API_KEY", "")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", "")
GEMINI_API_KEY = env("GEMINI_API_KEY", "")
# Ollama expone una API compatible con OpenAI en /v1.
OLLAMA_BASE_URL = env("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
# Razonamiento de los modelos de Ollama: none | low | medium | high (vacío = el del modelo).
OLLAMA_REASONING_EFFORT = env("OLLAMA_REASONING_EFFORT", "none")
LLM_TIMEOUT_SECONDS = float(env("BILLING_LLM_TIMEOUT") or "120")

# --- Notificaciones bancarias -----------------------------------------------------

# Cada cuántos segundos sincroniza el worker los buzones IMAP.
MAIL_SYNC_INTERVAL = int(env("BILLING_MAIL_SYNC_INTERVAL") or "120")
# Correos que se leen como máximo por buzón en cada sincronización.
MAIL_SYNC_BATCH = int(env("BILLING_MAIL_SYNC_BATCH") or "50")

DEFAULT_CURRENCY = env("BILLING_CURRENCY", "USD")
