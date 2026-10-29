# Registro de compras

Aplicación web para registrar compras mensuales, a mano o importando facturas (fotos, PDFs y correos `.eml`) y alertas de compra de los bancos, que se leen automáticamente con un agente de IA o con reglas. Incluye inicio de sesión con Keycloak, verificación en dos pasos, confirmación por correo de las acciones sensibles, roles de administrador y cliente, y datos en PostgreSQL.

## Funcionalidades

- **Resumen general:** gasto del mes, compras registradas, categoría y comercio principales, y gráficos por mes, categoría, método de pago y comercio.
- **Tabla resumen:** compras del mes con filtro por categoría, detalle, edición, borrado, exportación a CSV y alta de compras nuevas.
- **Importar facturas:** subir archivos o tomar una foto. Un agente LLM (Claude, GPT, Gemini u Ollama) o las reglas locales extraen los datos, que quedan en borrador para revisarlos. Avisa de archivos repetidos, de incoherencias en los totales y de compras parecidas.
- **Predicción del gasto:** en el resumen del mes en curso, el cierre estimado del mes, lo previsto para el mes siguiente con un rango probable y un aviso si vas por encima de lo habitual. Un modelo general (LightGBM) aprende de todos los clientes y uno propio por cliente lo personaliza; el worker los reentrena solo cuando hay datos nuevos.
- **Notificaciones bancarias:** alertas de Bancolombia, Davivienda, BBVA, Banco de Bogotá y Nequi, subidas como `.eml` o leídas de tu buzón (Gmail, Outlook o IMAP) cada pocos minutos.
- **Administración** (solo administradores):
  - Usuarios: estado y cifras de uso de cada cuenta; bloquear, cambiar rol, cerrar sesiones, forzar cambio de contraseña, quitar 2FA, invitar, eliminar, y **exportar** todos sus datos a un ZIP con el que **restaurarlo** después.
  - Modelos de predicción: modelos entrenados, versiones, métricas (acierto, error, MAE, MASE, cobertura), entrenamientos y «Entrenar ahora».
  - Estado del sistema: servicios, buzones y worker, agentes IA, uso y retención de datos.
  - Auditoría de las acciones de los administradores y modelo de datos (diagrama, tablas y migraciones).
- **Configuración:**
  - Perfil (avatar y nombre).
  - Seguridad: contraseña, 2FA y sesiones.
  - Cuenta: información y eliminación de la cuenta.
  - Correo bancario: buzones conectados (clientes).
  - Preferencias (clientes) y categorías.
  - Agentes IA (solo administradores): proveedor y modelo de cada agente.

Un **cliente** lleva sus compras y ve solo sus datos. Un **administrador** no lleva compras ni ve las de los clientes (solo cifras de uso): administra las cuentas, gestiona las categorías generales y elige los agentes IA. Las cuentas nuevas, creadas con «Crear cuenta» o con Google, reciben el rol `customer`.

### Seguridad

- **Verificación en dos pasos (2FA):** la activa cada usuario en Configuración → Seguridad. Sin 2FA se entra con la contraseña; con 2FA, el login pide además el código.
- **Cuentas nuevas:** se activan desde un correo de confirmación. La contraseña se crea después de abrir el enlace.
- **Acciones sensibles:** se confirman por correo.

  | Acción | Correo | Código 2FA |
  |---|---|---|
  | Cambiar la contraseña | ✔ | — |
  | Cambiar de dispositivo 2FA | ✔ | ✔ |
  | Desactivar el 2FA | ✔ | ✔ |
  | Eliminar la cuenta | ✔ | ✔ (si el 2FA está activo) |

## Inicio rápido

Requisitos: Docker con Compose v2 y `make`.

```bash
make up            # crea .env si no existe, construye y levanta el stack
make seed          # carga 12 meses de compras de prueba
make bank-samples  # envía alertas bancarias de prueba y conecta el buzón de cliente@
make train         # entrena ya los modelos de predicción (el worker lo hace solo cada hora)
```

| Servicio | URL | Acceso |
|---|---|---|
| App | http://localhost:8502 | usuarios de desarrollo (abajo) |
| Mailpit (correos enviados) | http://localhost:8025 | sin contraseña |
| Keycloak (consola) | http://localhost:8180/admin | `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` de `.env` |
| pgAdmin | http://localhost:5050 | `PGADMIN_EMAIL` / `PGADMIN_PASSWORD` (el servidor ya está registrado; pide `POSTGRES_PASSWORD`) |
| PostgreSQL | `localhost:5433` | `POSTGRES_USER` / `POSTGRES_PASSWORD` |
| GreenMail (bandeja IMAP de pruebas) | IMAP `localhost:3143`, SMTP `localhost:3025` | buzones abajo |

### Usuarios de desarrollo

Se inicia sesión con el correo. Estas contraseñas vienen de `.env.example` y **solo existen en desarrollo**:

| Nombre | Correo | Rol | Contraseña |
|---|---|---|---|
| Administrador Compras | `admin@billing.example.com` | `admin` | `Admin-Compras-2026` |
| Carlos Mendoza | `cliente@billing.example.com` | `customer` | `Cliente-Compras-2026` |
| María López | `maria.lopez@billing.example.com` | `customer` | `Cliente-Compras-2026` |
| Juan Pérez | `juan.perez@billing.example.com` | `customer` | `Cliente-Compras-2026` |
| Sofía Ramírez | `sofia.ramirez@billing.example.com` | `customer` | `Cliente-Compras-2026` |

`make seed` genera perfiles de gasto distintos para comparar: familia, gasto alto, estudiante con gasto creciente y un viaje pagado en EUR. `make seed-reset` los regenera.

### Correo en desarrollo

Ningún correo sale a Internet:

- **Mailpit** (http://localhost:8025) muestra los correos que envían la app y Keycloak: activación de cuentas, recuperación de contraseña y confirmaciones.
- **GreenMail** es la bandeja de entrada IMAP de la que la app lee las notificaciones bancarias. Buzones disponibles, ambos con la contraseña `Bandeja-Compras-2026`:
  - `cliente@billing.example.com`
  - `maria.lopez@billing.example.com`

## Agentes IA

Se configuran en `.env` y se eligen por agente en Configuración → Agentes IA:

| Proveedor | Variable |
|---|---|
| Anthropic (Claude) | `ANTHROPIC_API_KEY` |
| OpenAI o una API compatible | `OPENAI_API_KEY` (y `OPENAI_BASE_URL` para una compatible) |
| Google Gemini | `GEMINI_API_KEY` |
| Ollama local | `OLLAMA_BASE_URL` (por defecto el del host) |

Sin ninguno, la app usa solo reglas: lee PDFs digitales, correos y las alertas de los bancos con plantilla, pero no fotos ni PDFs escaneados.

## Comandos (`make help`)

| Comando | Qué hace |
|---|---|
| `make build` / `make up` / `make down` | Construir, levantar y bajar el stack (`down` conserva los datos) |
| `make restart`, `make logs`, `make ps` | Reiniciar, ver logs y estado (`SERVICE=app` para uno solo) |
| `make seed`, `make seed-reset` | Datos de prueba |
| `make bank-samples`, `make sync-once` | Alertas bancarias de prueba y una sincronización de buzones |
| `make train` | Entrena ya los modelos de predicción (el worker lo hace solo cada hora) |
| `make keycloak-reimport` | Reimporta el realm desde el JSON (borra los usuarios de Keycloak, no las compras) |
| `make install` | Crea `.venv` con dependencias de desarrollo y hooks de pre-commit |
| `make dev` / `make worker` | App en local (http://localhost:8501) y worker de buzones en local |
| `make migrate` | Aplica las migraciones de base de datos |
| `make test` | Pruebas automáticas (sin Docker) |
| `make lint`, `make format` | Hooks de pre-commit y formato con ruff |
| `make tf-validate` | Valida la configuración de Terraform |

## Arquitectura

Arquitectura hexagonal (puertos y adaptadores). Las dependencias apuntan hacia dentro: el dominio no conoce la base de datos, Streamlit, los proveedores LLM ni los servidores de correo.

```
src/billing/
├── domain/            Entidades, reglas (roles, seguridad) y puertos (interfaces)
├── application/       Casos de uso: compras, importación, usuarios, categorías, reportes,
│                      security/ (confirmaciones), agents/ (agentes LLM), bank_emails/ (buzones),
│                      admin/ (panel del administrador), forecasting/ (predicción del gasto)
├── infrastructure/    Adaptadores, un paquete por servicio:
│   ├── persistence/   registry + sqlalchemy/ (PostgreSQL, SQLite, MySQL) + memory/
│   ├── llm/           Anthropic, OpenAI y compatibles, Gemini, Ollama, falso, cadena
│   ├── extraction/    Facturas (LLM y reglas) y notificaciones bancarias (plantillas y LLM)
│   ├── mail/          SMTP, IMAP y plantillas de correo
│   ├── identity/      Keycloak
│   ├── ml/            Modelos de predicción: LightGBM (general), ETS (por cliente), referencia
│   ├── crypto/        Cifrado de secretos
│   └── storage/       Archivos (disco local)
├── presentation/streamlit/   Interfaz web
├── worker/            Sincronización periódica de buzones IMAP y entrenamiento de modelos
├── bootstrap.py       Elige y conecta los adaptadores según la configuración
└── settings.py        Variables de entorno
infra/                 Docker (app, Keycloak con tema y realm, Postgres, pgAdmin) y Terraform (AWS)
scripts/               Secretos de login, datos de prueba y alertas bancarias de prueba
tests/                 Pruebas automáticas (pytest, sin Docker)
docs/                  Documentación técnica detallada
```

Cada servicio se cambia desde la configuración:

- **Base de datos:** `BILLING_PERSISTENCE` y `BILLING_DATABASE_URL`.
- **Agente LLM:** desde la app o con `BILLING_LLM_PROVIDER`.
- **Correo:** `BILLING_MAILER` y `SMTP_*`.

Cuando hace falta una implementación nueva, se crea su adaptador y se registra en la carpeta de su servicio.

**Documentación completa en [docs/](docs/README.md):**
- La arquitectura, la configuración y el modelo de datos.
- Cada servicio: seguridad, agentes, persistencia, facturas, correos bancarios y correo.
- La interfaz y la infraestructura.

## Configuración

Todo se lee de `.env` (plantilla en `.env.example`; `make env` la crea):
- Puertos y credenciales de PostgreSQL, pgAdmin y Keycloak.
- Secretos OIDC y la clave de cifrado `BILLING_SECRET_KEY`.
- SMTP y proveedores LLM.

Referencia completa en [docs/configuracion.md](docs/configuracion.md).

### Inicio de sesión con Google

El botón aparece deshabilitado hasta configurar el proveedor:

1. Crea un ID de cliente OAuth en Google Cloud con el URI de redirección `http://localhost:8180/realms/billing/broker/google/endpoint`.
2. Pon `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` en `.env`.
3. Ejecuta `./infra/docker/keycloak/configure-google.sh` (`--remove` para quitarlo).

### Pantalla de login

Es un tema propio de Keycloak (`infra/docker/keycloak/themes/billing`), con el formulario a la izquierda y este README a la derecha. Los correos de Keycloak usan el mismo diseño que los de la app. Tras cambiar el tema o este archivo: `make up SERVICE=keycloak`.

El realm (`infra/docker/keycloak/realm-billing.json`) se importa solo la primera vez que arranca Keycloak con una base vacía. Si cambias el JSON o las contraseñas de `.env`: `make keycloak-reimport`.

## Desarrollo local

```bash
make install   # .venv con el paquete en modo editable, dependencias de desarrollo y hooks
make dev       # Postgres, Keycloak, Mailpit y GreenMail en Docker; la app en http://localhost:8501
```

La app aplica las migraciones pendientes al arrancar. Para crear una nueva: `.venv/bin/alembic revision -m "descripcion"`. Más detalle en [docs/desarrollo.md](docs/desarrollo.md).
