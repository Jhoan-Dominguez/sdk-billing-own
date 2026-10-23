# Registro de compras

Aplicación web para registrar compras mensuales, a mano o importando facturas (fotos, PDFs y emails `.eml`) que se leen automáticamente. Incluye inicio de sesión con Keycloak, roles de administrador y cliente, y datos en PostgreSQL.

## Funcionalidades

- **Resumen general:** gasto del mes, compras registradas, categoría y comercio principales, y gráficos por mes, categoría, método de pago y comercio.
- **Tabla resumen:** compras del mes con filtro por categoría, detalle, edición, borrado, exportación a CSV y alta de compras nuevas.
- **Importar facturas:** subir archivos o tomar una foto. Los datos se extraen (con Claude si hay `ANTHROPIC_API_KEY`, o con reglas locales) y quedan en borrador para revisar antes de guardar.
- **Comparativa de clientes** (solo administradores): gasto por cliente, mapa de calor mensual y variación respecto al mes anterior.
- **Configuración:** avatar, datos personales, contraseña, verificación en dos pasos (2FA), sesiones abiertas, eliminación de la cuenta, preferencias (moneda, método de pago y categoría por defecto) y categorías propias.

Un **cliente** ve solo sus datos. Un **administrador** ve los de todos (en solo lectura los ajenos) y gestiona las categorías generales. Las cuentas nuevas, creadas con «Crear cuenta» o con Google, reciben el rol `cliente`.

## Inicio rápido

Requisitos: Docker con Compose v2 y `make`.

```bash
make up      # crea .env si no existe, construye y levanta el stack
make seed    # carga 12 meses de compras de prueba
```

| Servicio | URL | Acceso |
|---|---|---|
| App | http://localhost:8502 | usuarios de desarrollo (abajo) |
| Keycloak (consola) | http://localhost:8180/admin | `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` de `.env` |
| pgAdmin | http://localhost:5050 | `PGADMIN_EMAIL` / `PGADMIN_PASSWORD` (el servidor ya está registrado; pide `POSTGRES_PASSWORD`) |
| PostgreSQL | `localhost:5433` | `POSTGRES_USER` / `POSTGRES_PASSWORD` |

### Usuarios de desarrollo

Se inicia sesión con el correo. Estas contraseñas vienen de `.env.example` y **solo existen en desarrollo**:

| Nombre | Correo | Rol | Contraseña |
|---|---|---|---|
| Administrador Compras | `admin@compras.example.com` | `admin` | `Admin-Compras-2026` |
| Carlos Mendoza | `cliente@compras.example.com` | `cliente` | `Cliente-Compras-2026` |
| María López | `maria.lopez@compras.example.com` | `cliente` | `Cliente-Compras-2026` |
| Juan Pérez | `juan.perez@compras.example.com` | `cliente` | `Cliente-Compras-2026` |
| Sofía Ramírez | `sofia.ramirez@compras.example.com` | `cliente` | `Cliente-Compras-2026` |

`make seed` genera perfiles de gasto distintos para comparar: familia, gasto alto, estudiante con gasto creciente y un viaje pagado en EUR. `make seed-reset` los regenera.

## Comandos (`make help`)

| Comando | Qué hace |
|---|---|
| `make build` / `make up` / `make down` | Construir, levantar y bajar el stack (`down` conserva los datos) |
| `make restart`, `make logs`, `make ps` | Reiniciar, ver logs y estado (`SERVICE=app` para uno solo) |
| `make seed`, `make seed-reset` | Datos de prueba |
| `make keycloak-reimport` | Reimporta el realm desde el JSON (borra los usuarios de Keycloak, no las compras) |
| `make install` | Crea `.venv` con dependencias de desarrollo y hooks de pre-commit |
| `make dev` | Postgres y Keycloak en Docker y la app en local (http://localhost:8501) |
| `make migrate` | Aplica las migraciones de base de datos |
| `make lint`, `make format` | Hooks de pre-commit y formato con ruff |
| `make tf-validate` | Valida la configuración de Terraform |

## Arquitectura

Arquitectura hexagonal (puertos y adaptadores). Las dependencias apuntan hacia dentro: el dominio no conoce la base de datos, Streamlit ni las APIs externas.

```
src/compras/
├── domain/            Entidades, reglas (roles, permisos) y puertos (interfaces)
├── application/       Casos de uso: compras, importación, usuarios, categorías, reportes
├── infrastructure/    Adaptadores
│   ├── persistence/sqlalchemy/   PostgreSQL: tablas, mapeo, repositorios, migraciones
│   ├── storage/                  Archivos (disco local)
│   ├── identity/                 Keycloak
│   └── extraction/               Lectura de facturas (Claude y reglas locales)
├── presentation/streamlit/       Interfaz web: app.py, pages/, components/, assets/
├── bootstrap.py       Elige y conecta los adaptadores según la configuración
└── settings.py        Variables de entorno
infra/
├── docker/            Imágenes de la app y Keycloak (con tema de login y realm), Postgres, pgAdmin
└── terraform/         Infraestructura en AWS (esqueleto; ver infra/terraform/README.md)
scripts/               Generación de secretos de login y datos de prueba
```

Para cambiar de base de datos o de almacenamiento de archivos se implementa el puerto en `infrastructure/` y se registra en `bootstrap.py` (`COMPRAS_PERSISTENCE`, `COMPRAS_STORAGE`). El dominio, los casos de uso y la interfaz no cambian.

## Configuración

Todo se lee de `.env` (plantilla en `.env.example`): puertos, credenciales de PostgreSQL, pgAdmin y Keycloak, secretos de los clientes OIDC, `ANTHROPIC_API_KEY` (opcional) y la moneda por defecto. `make env` lo crea si no existe.

### Inicio de sesión con Google

El botón aparece deshabilitado hasta configurar el proveedor:

1. Crea un ID de cliente OAuth en Google Cloud con el URI de redirección `http://localhost:8180/realms/compras/broker/google/endpoint`.
2. Pon `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` en `.env`.
3. Ejecuta `./infra/docker/keycloak/configure-google.sh` (`--remove` para quitarlo).

### Pantalla de login

Es un tema propio de Keycloak (`infra/docker/keycloak/themes/compras`), con el formulario a la izquierda y este README a la derecha. Tras cambiar el tema o este archivo: `make up SERVICE=keycloak`.

El realm (`infra/docker/keycloak/realm-compras.json`) se importa solo la primera vez que arranca Keycloak con una base vacía. Si cambias el JSON o las contraseñas de `.env`: `make keycloak-reimport`.

## Desarrollo local

```bash
make install   # .venv con el paquete en modo editable, dependencias de desarrollo y hooks
make dev       # Postgres y Keycloak en Docker; la app en http://localhost:8501
```

La app aplica las migraciones pendientes al arrancar. Para crear una nueva: `.venv/bin/alembic revision -m "descripcion"`.
