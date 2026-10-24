# Docker Compose

`docker-compose.yml` levanta todo el entorno. Lee `.env` (plantilla en `.env.example`).

## Servicios

| Servicio | Imagen | Puerto en el host | Función |
|---|---|---|---|
| `db` | `postgres:17-alpine` | `DB_PORT` (5433) | Bases `compras` (app), `keycloak` y `compras_test` |
| `keycloak` | propia (`infra/docker/keycloak/Dockerfile`, Keycloak 26.8) | `KEYCLOAK_PORT` (8180) | Identidad: login, registro, 2FA, correos |
| `app` | propia (`infra/docker/app/Dockerfile`) | `APP_PORT` (8502) | App web Streamlit |
| `worker` | la misma que `app` | — | `python -m billing.worker`: sincroniza buzones IMAP |
| `pgadmin` | `dpage/pgadmin4:9` | `PGADMIN_PORT` (5050) | Administración de PostgreSQL (servidor ya registrado) |
| `mailpit` | `axllent/mailpit:v1.27` | `MAILPIT_PORT` (8025) web, `MAILPIT_SMTP_PORT` (1025) SMTP | Captura el correo saliente de la app y de Keycloak |
| `greenmail` | `greenmail/standalone:2.1.3` | `GREENMAIL_SMTP_PORT` (3025), `GREENMAIL_IMAP_PORT` (3143) | Bandeja IMAP de pruebas para notificaciones bancarias |

Dependencias de arranque: `keycloak` espera a `db` sano y a `mailpit`; `app` espera a `db` y
`keycloak` sanos; `worker` espera a `app` sana (que ya aplicó las migraciones).

## Healthchecks

| Servicio | Comprobación |
|---|---|
| `db` | `pg_isready` |
| `keycloak` | `GET /health/ready` en el puerto de gestión 9000 (con `/dev/tcp` de bash: la imagen no trae curl) |
| `app` | `GET /_stcore/health` (en el Dockerfile) |
| `worker` | `/tmp/worker-alive` modificado hace menos de 10 min |

## Volúmenes

| Volumen | Contenido |
|---|---|
| `db_data` | Datos de PostgreSQL |
| `uploads` | Archivos de facturas, notificaciones y avatares (`/app/data/uploads`, compartido por `app` y `worker`) |
| `pgadmin_data` | Configuración de pgAdmin |

Mailpit y GreenMail guardan en memoria: se vacían al reiniciarlos.

`make down` conserva los volúmenes; `docker compose down -v` los borra (todos los datos).

## Variables comunes de la app y el worker

El bloque `x-app-env` (ancla YAML `&app-env`) define una sola vez lo que necesitan ambos:
conexión a `db`, Keycloak interno (`http://keycloak:8080`) y público, secretos, SMTP de
Mailpit, proveedores LLM (`OLLAMA_BASE_URL` apunta a `host.docker.internal`, resuelto con
`extra_hosts: host-gateway`) e intervalo de sincronización. La `app` añade
`AUTH_COOKIE_SECRET`; el `worker` añade `COMPRAS_SKIP_SECRETS=1`.

## Imagen de la app (`infra/docker/app/`)

- `python:3.13-slim`, usuario sin privilegios `app` (uid 1000), `COMPRAS_DATA_DIR=/app/data`.
- `pip install ".[llm]"`: el paquete con los SDK de Anthropic, OpenAI y Gemini.
- Copia `.streamlit/config.toml` (tema), `scripts/` y el `entrypoint.sh`.
- `entrypoint.sh` genera `.streamlit/secrets.toml` con `scripts/write_secrets.py` (salvo
  `COMPRAS_SKIP_SECRETS=1`) y ejecuta el comando: `python -m billing --server.address=0.0.0.0 --server.port=8501`.

## Imagen de Keycloak (`infra/docker/keycloak/`)

Compilación en dos etapas: una etapa `python:3.13-slim` convierte `README.md` a HTML
(`info.ftl`, panel derecho del login, dentro de `<#noparse>`), y la final
(`quay.io/keycloak/keycloak:26.8`) copia el tema `compras` (login y correo), `info.ftl` y
`realm-compras.json` a `data/import`. Arranca con `start-dev --import-realm`. Detalle en
[keycloak.md](keycloak.md).

Separación de nombres de host: el navegador usa `localhost:8180` y la app `keycloak:8080`.
`KC_HOSTNAME=http://localhost:8180` fija el emisor y las URLs públicas, y
`KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` permite token y JWKS por el host interno.

## Base de datos

`infra/docker/postgres/init-databases.sql` (solo al crear el volumen) crea `keycloak` y
`compras_test`; `POSTGRES_DB` (`compras`) la crea la imagen. pgAdmin tiene el servidor
registrado en `infra/docker/pgadmin/servers.json`.

## Operación habitual

```bash
make up                      # construye y levanta todo
make ps / make logs SERVICE=worker
make restart SERVICE=app
make up SERVICE=keycloak     # tras cambiar el tema, el realm o el README
make keycloak-reimport       # vuelve a importar el realm (borra los usuarios de Keycloak)
make seed                    # 12 meses de compras de prueba
make bank-samples            # alertas bancarias de prueba + buzón conectado
make sync-once               # una sincronización de buzones
make down
```

Copia de seguridad de la base de la app:

```bash
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" compras' > compras.sql
```
