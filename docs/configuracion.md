# Configuración

Toda la configuración sale de variables de entorno. `src/compras/settings.py` las lee **una
vez al importar el paquete**, cargando antes `.env` del directorio de trabajo (el mismo
archivo que lee Docker Compose). Las variables ya definidas en el entorno tienen prioridad, y
una variable vacía en `.env` (`VAR=`) cuenta como no definida para las que tienen valor por
defecto.

- Plantilla: `.env.example` (`make env` la copia a `.env` si no existe).
- Docker Compose pasa a `app` y `worker` el bloque común `x-app-env` de `docker-compose.yml`;
  algunos valores cambian dentro de Docker (hosts `db`, `keycloak`, `mailpit`).
- `scripts/write_secrets.py` genera `.streamlit/secrets.toml` (Streamlit solo lee la
  configuración OIDC de ahí). El contenedor de la app lo ejecuta al arrancar
  (`infra/docker/app/entrypoint.sh`); el worker lo omite (`COMPRAS_SKIP_SECRETS=1`).

## Puertos publicados en el host

| Variable | Por defecto | Servicio |
|---|---|---|
| `APP_PORT` | `8502` | App web (Docker) |
| `DB_PORT` | `5433` | PostgreSQL |
| `KEYCLOAK_PORT` | `8180` | Keycloak |
| `PGADMIN_PORT` | `5050` | pgAdmin |
| `MAILPIT_PORT` | `8025` | Interfaz web de Mailpit |
| `MAILPIT_SMTP_PORT` | `1025` | SMTP de Mailpit (para la app en local) |
| `GREENMAIL_SMTP_PORT` | `3025` | SMTP de GreenMail |
| `GREENMAIL_IMAP_PORT` | `3143` | IMAP de GreenMail |

La app en local (`make dev`) usa el puerto 8501.

## Base de datos

| Variable | Por defecto | Uso |
|---|---|---|
| `COMPRAS_PERSISTENCE` | `sql` | Motor: `sql` (SQLAlchemy) o `memory` ([persistencia](servicios/persistencia.md)) |
| `COMPRAS_DATABASE_URL` | — | URL completa de SQLAlchemy. Si existe, ignora las `POSTGRES_*` (p. ej. `sqlite:///data/compras.sqlite`) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `compras` / — / `compras` | Credenciales de PostgreSQL (también las usa el contenedor `db`) |
| `POSTGRES_HOST` | `localhost` | `db` dentro de Docker |
| `POSTGRES_PORT` | `DB_PORT` | `5432` dentro de Docker |

## Archivos

| Variable | Por defecto | Uso |
|---|---|---|
| `COMPRAS_DATA_DIR` | `./data` | Raíz de datos; los archivos van en `uploads/` (`/app/data` en Docker, volumen `uploads`) |
| `COMPRAS_STORAGE` | `local` | Adaptador de archivos |

## Identidad (Keycloak y login)

| Variable | Por defecto | Uso |
|---|---|---|
| `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` | `kcadmin` / — | Administrador de la consola (realm `master`) |
| `KEYCLOAK_REALM` | `compras` | Realm de la app |
| `KEYCLOAK_CLIENT_ID` | `compras-app` | Cliente OIDC |
| `KEYCLOAK_CLIENT_SECRET` | — | Secreto del cliente: login de Streamlit y reautenticación con 2FA |
| `KEYCLOAK_ADMIN_API_CLIENT_ID` | `compras-admin-api` | Cuenta de servicio de gestión de cuentas |
| `KEYCLOAK_ADMIN_API_SECRET` | — | Su secreto. Sin él, Configuración no puede gestionar la cuenta |
| `KEYCLOAK_PUBLIC_URL` | `http://localhost:KEYCLOAK_PORT` | URL que ve el navegador |
| `KEYCLOAK_INTERNAL_URL` | = pública | URL desde la app (`http://keycloak:8080` en Docker) |
| `COMPRAS_ADMIN_PASSWORD` / `COMPRAS_CLIENTE_PASSWORD` | `Admin-Compras-2026` / `Cliente-Compras-2026` | Contraseñas de los usuarios de desarrollo (solo al importar el realm) |
| `AUTH_COOKIE_SECRET` | — | Firma la cookie de sesión de Streamlit |
| `AUTH_REDIRECT_URI` | `http://localhost:8501/oauth2callback` | Callback OIDC. Su raíz es `APP_PUBLIC_URL`, base de los enlaces de los correos |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | — | IdP de Google (`configure-google.sh`) |

## Correo saliente

Lo usan la app (confirmaciones de seguridad) y Keycloak (verificación de cuentas,
recuperación de contraseña); ambos leen las mismas variables.

| Variable | Por defecto | Uso |
|---|---|---|
| `COMPRAS_MAILER` | `smtp` | `smtp` o `console` (escribe el correo en el log) |
| `SMTP_HOST` | `localhost` (local) / `mailpit` (Docker) | Servidor SMTP |
| `SMTP_PORT` | `MAILPIT_SMTP_PORT` (local) / `1025` (Docker) | Puerto |
| `SMTP_FROM` | `no-reply@compras.example.com` | Remitente |
| `SMTP_AUTH` | `false` | Solo Keycloak: si el servidor pide usuario |
| `SMTP_USER` / `SMTP_PASSWORD` | — | Credenciales SMTP (la app autentica si `SMTP_USER` no está vacío) |
| `SMTP_STARTTLS` / `SMTP_SSL` | `false` | Cifrado de la conexión |

## Secretos guardados

| Variable | Uso |
|---|---|
| `COMPRAS_SECRET_KEY` | Clave Fernet (32 bytes en base64) con la que se cifran las contraseñas IMAP. Obligatoria en Docker. Generar: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Cambiarla deja ilegibles las contraseñas guardadas |

## Agentes LLM

| Variable | Por defecto | Uso |
|---|---|---|
| `COMPRAS_LLM_PROVIDER` | vacío | Proveedor por defecto: `anthropic`, `openai`, `gemini`, `ollama` o `local` (sin LLM). Vacío = el primero con credenciales entre anthropic, openai y gemini; si no hay ninguno, `local` |
| `COMPRAS_LLM_MODEL` | vacío | Modelo por defecto del proveedor por defecto (vacío = el del registro) |
| `ANTHROPIC_API_KEY` | — | Activa Anthropic |
| `OPENAI_API_KEY` | — | Activa OpenAI |
| `OPENAI_BASE_URL` | — | API compatible con OpenAI (OpenRouter, Groq, Azure, vLLM...). Con ella se asume que no acepta PDFs |
| `GEMINI_API_KEY` | — | Activa Gemini |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` (local) / `http://host.docker.internal:11434/v1` (Docker) | Ollama |
| `OLLAMA_REASONING_EFFORT` | `none` | Razonamiento de los modelos de Ollama; `none` acelera mucho los modelos con razonamiento |
| `COMPRAS_LLM_TIMEOUT` | `120` | Segundos máximos por llamada |

El administrador puede cambiar proveedor y modelo **por agente** en Configuración → Agentes IA;
esa elección (tabla `agent_settings`) tiene prioridad sobre estas variables.

## Notificaciones bancarias

| Variable | Por defecto | Uso |
|---|---|---|
| `COMPRAS_MAIL_SYNC_INTERVAL` | `120` | Segundos entre sincronizaciones del worker |
| `COMPRAS_MAIL_SYNC_BATCH` | `50` | Correos importados como máximo por buzón y pasada |
| `GREENMAIL_USERS` | `cliente:…@compras.example.com,maria.lopez:…` | Buzones de la bandeja de pruebas (`usuario:contraseña@dominio`) |

## Otros

| Variable | Por defecto | Uso |
|---|---|---|
| `COMPRAS_MONEDA` | `USD` | Moneda por defecto (si el usuario no eligió otra en Preferencias) |
| `PGADMIN_EMAIL` / `PGADMIN_PASSWORD` | `admin@compras.example.com` / — | Acceso a pgAdmin |
| `COMPRAS_SKIP_SECRETS` | `0` | `1` = el entrypoint no genera `secrets.toml` (worker) |
