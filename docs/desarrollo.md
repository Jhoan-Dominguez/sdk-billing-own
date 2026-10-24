# Desarrollo

## Requisitos

Docker con Compose v2, `make`, Python 3.13 (para trabajar en local) y, opcionalmente,
[Ollama](https://ollama.com) para probar agentes sin claves de API.

## Puesta en marcha

### Todo en Docker

```bash
make up            # crea .env desde .env.example si no existe, construye y levanta
make seed          # 12 meses de compras para los 5 usuarios de desarrollo
make bank-samples  # alertas bancarias de prueba en GreenMail + buzón de cliente@ conectado
```

App en http://localhost:8502, correos en http://localhost:8025.

### App en local (recarga al guardar)

```bash
make install       # .venv con el paquete editable, SDKs LLM, herramientas y hooks
make dev           # db, keycloak, mailpit y greenmail en Docker; app en http://localhost:8501
make worker        # (otra terminal) worker de buzones en local
```

En local la app lee `.env`: Postgres en `localhost:5433`, SMTP de Mailpit en
`localhost:1025`, Ollama en `localhost:11434`. Los archivos van a `./data/uploads` (no al
volumen de Docker: los borradores creados por el worker de Docker no tienen su archivo en local).

## Comandos (`make help`)

| Comando | Qué hace |
|---|---|
| `make env` | Crea `.env` si no existe |
| `make build` / `up` / `down` | Construir, levantar (`SERVICE=` opcional) y bajar el stack |
| `make restart`, `logs`, `ps` | Reiniciar, ver logs y estado (`SERVICE=app`) |
| `make seed`, `seed-reset` | Datos de prueba (en el contenedor `app`) |
| `make keycloak-reimport` | Reimporta el realm desde el JSON |
| `make bank-samples [TO=correo]` | Envía alertas de prueba a GreenMail y conecta el buzón |
| `make mail` | Abre Mailpit |
| `make install`, `secrets`, `dev`, `worker` | Desarrollo local |
| `make sync-once` | Una sincronización de buzones en el contenedor `worker` |
| `make migrate` | `alembic upgrade head` |
| `make lint`, `format` | pre-commit (ruff y comprobaciones) / formateo |
| `make tf-validate` | Valida Terraform |

## Scripts (`scripts/`)

| Script | Uso |
|---|---|
| `write_secrets.py` | Genera `.streamlit/secrets.toml` (login OIDC) desde el entorno |
| `seed_dev_data.py [--reset]` | Compras deterministas para los usuarios del realm |
| `send_bank_samples.py [--to correo] [--host h] [--connect]` | Alertas bancarias de prueba a GreenMail; `--connect` conecta el buzón del usuario |

## Probar cada servicio

| Servicio | Cómo |
|---|---|
| Registro con correo | Crear cuenta en el login → Mailpit → «Activar mi cuenta» → crear contraseña |
| 2FA | Configuración → Seguridad → Activar 2FA; cerrar sesión: el login pide el código |
| Acciones sensibles | Seguridad o Cuenta → solicitar → abrir el correo en Mailpit **en el mismo navegador** → (si hay 2FA) «Verificar con mi código 2FA» → acción |
| Agentes | Configuración → Agentes IA (admin) → elegir proveedor/modelo → Probar |
| Facturas | Importar facturas → subir una foto, PDF o `.eml` |
| Notificaciones bancarias | `make bank-samples` → `make sync-once` → Importar facturas |
| Otra base de datos | `COMPRAS_DATABASE_URL=sqlite:///data/compras.sqlite make dev` o `COMPRAS_PERSISTENCE=memory` |

Comprobaciones rápidas:

```bash
# Plantillas de bancos contra sus ejemplos
.venv/bin/python -c "from compras.infrastructure.extraction import bank_rules as b; \
print(all(b.match(p.example, 'x@' + t.senders[0]) for t in b.TEMPLATES for p in t.patterns))"
# Esquema de la base frente a tables.py
.venv/bin/alembic check
```

## Convenciones

- Textos de interfaz, comentarios y docstrings en español; identificadores en inglés.
- Ruff (lint, isort y formato) con líneas de 120 caracteres; `make lint` antes de commitear.
  pre-commit solo ve archivos que git conoce (`git add -N` para los nuevos).
- Nada de lógica de negocio ni SQL en las páginas: casos de uso en `application/`.
- Toda consulta de datos de usuario recibe `owner_id` desde `viewer.owner_filter()`.
- Los importes son `Decimal` (`Numeric(12,2)`) y nunca se suman monedas distintas.
- Cambios de esquema = migración nueva + `alembic check` sin diferencias.
- Botones destructivos con clave `confirm-delete*` (se pintan en rojo).

## Pruebas

Las pruebas automáticas (`tests/`) son de la estructura anterior al refactor y están
pendientes de reescribir contra `src/compras`. La verificación de esta versión se hizo con
scripts de punta a punta contra los servicios reales (Keycloak, PostgreSQL, SQLite, memoria,
Mailpit, GreenMail y Ollama) y con `streamlit.testing.v1.AppTest` sobre todas las páginas.
