# Arquitectura

La aplicación sigue una **arquitectura hexagonal** (puertos y adaptadores). El dominio y
los casos de uso no conocen la base de datos, Streamlit, Keycloak, los proveedores LLM
ni los servidores de correo: hablan con ellos a través de interfaces (*puertos*) que la
infraestructura implementa (*adaptadores*). Un único módulo, `bootstrap.py`, decide qué
adaptador concreto se usa en cada caso.

## Capas y dependencias

```
                 ┌──────────────────────────────────────────────┐
                 │ presentation/streamlit   worker/   scripts/   │  entradas
                 └───────────────┬──────────────────────────────┘
                                 │ llama a
                 ┌───────────────▼──────────────────────────────┐
  bootstrap.py ─▶│ application/  (casos de uso)                 │
  (elige y       └───────────────┬──────────────────────────────┘
   conecta)                      │ usa
                 ┌───────────────▼──────────────────────────────┐
                 │ domain/  entidades · reglas · ports/         │  sin dependencias externas
                 └───────────────▲──────────────────────────────┘
                                 │ implementa los puertos
                 ┌───────────────┴──────────────────────────────┐
                 │ infrastructure/  persistence · llm · mail ·  │
                 │ extraction · identity · storage · crypto     │
                 └──────────────────────────────────────────────┘
```

Reglas:

1. `domain/` solo importa la biblioteca estándar y `pydantic` (esquemas de datos extraídos).
2. `application/` importa `domain/` y recibe los adaptadores como parámetros (inyección
   de dependencias): por ejemplo `imports.store_upload(uow, storage, extractor, ...)`.
3. `infrastructure/` implementa los puertos. Puede usar entidades del dominio y, en los
   extractores, la clase `Agent` de `application/agents` (que es un orquestador sin I/O).
4. `presentation/`, `worker/` y `scripts/` obtienen los adaptadores de `bootstrap.py` y
   llaman a los casos de uso. Las páginas no contienen lógica de negocio ni SQL.

## Composition root (`src/billing/bootstrap.py`)

Es el único módulo que conoce las clases concretas. Expone fábricas cacheadas:

| Función | Devuelve | Elegido por |
|---|---|---|
| `persistence()`, `unit_of_work()`, `uow_factory()`, `init_database()` | Backend de persistencia y su unidad de trabajo | `COMPRAS_PERSISTENCE` (+ `COMPRAS_DATABASE_URL`) vía `infrastructure/persistence/registry.py` |
| `file_storage()` | `FileStorage` | `COMPRAS_STORAGE` (`local`) |
| `llm_catalog()` | Registro de proveedores LLM | `infrastructure/llm/registry.py` |
| `agent_choice(name)` | `(proveedor, modelo, personalizado)` del agente | tabla `agent_settings` o `COMPRAS_LLM_PROVIDER`/`COMPRAS_LLM_MODEL` |
| `agent(name)` / `agent_for(name, provider, model)` | `Agent` listo para ejecutar (o `None` si es `local`) | lo anterior |
| `invoice_extractor()` | `InvoiceExtractor` (`LLMInvoiceExtractor` con respaldo de regex) | agente `invoice` |
| `bank_parser(uploaded=False)` | `BankNotificationParser` (reglas + agente `bank_notification`) | agente `bank_notification` |
| `mailer()` | `Mailer` | `COMPRAS_MAILER` (`smtp`/`console`) |
| `mailbox_gateway()` | `MailboxGateway` (IMAP) | — |
| `secret_cipher()` | `SecretCipher` (Fernet) | `COMPRAS_SECRET_KEY` |
| `account_admin(user_id)` | `AccountAdmin` (API admin de Keycloak) o `None` | `KEYCLOAK_ADMIN_API_SECRET` |
| `account_actions()` | `AccountActions` (URLs `kc_action`) | Keycloak |
| `reauthenticator()` | `Reauthenticator` (reautenticación con 2FA) | Keycloak |

La elección del agente se resuelve **en cada uso** (`agent(name)` consulta la tabla
`agent_settings`), así que un cambio del administrador se aplica sin reiniciar. Los
clientes LLM se cachean por `(proveedor, modelo)`.

## Registros por servicio

Cada servicio intercambiable tiene un registro en su carpeta de infraestructura. Añadir o
quitar una implementación es tocar solo esa carpeta:

| Servicio | Registro | Cómo se añade una implementación |
|---|---|---|
| Base de datos | `infrastructure/persistence/registry.py` (`BACKENDS`) | paquete con `backend.py` → `create(settings)`; ver [persistencia](servicios/persistencia.md) |
| LLM | `infrastructure/llm/registry.py` (`PROVIDERS`) | adaptador `LLMClient` + `ProviderSpec`; ver [agentes](servicios/agentes.md) |
| Agentes | `application/agents/registry.py` (`AGENTS`) | esquema + prompt + `AgentSpec` |
| Bancos | `infrastructure/extraction/bank_rules.py` (`TEMPLATES`) | `BankTemplate` con patrones; ver [correos bancarios](servicios/correos-bancarios.md) |
| Correo saliente | `bootstrap.mailer()` | clase con `send(EmailContent)` |
| Archivos | `bootstrap.file_storage()` | clase con `save/read/delete` |

## Árbol de carpetas

```
src/billing/
├── __init__.py, __main__.py      `python -m billing` arranca Streamlit
├── settings.py                   variables de entorno (ver configuracion.md)
├── bootstrap.py                  composition root
├── domain/
│   ├── models.py                 entidades (dataclasses): User, Purchase, PurchaseItem, Attachment,
│   │                             Category, SecurityConfirmation, AgentSetting, MailboxConnection
│   ├── auth.py                   roles, Viewer, permisos
│   ├── security.py               acciones sensibles y pasos que exige cada una
│   ├── invoice.py                InvoiceData, ExtractionResult, avisos de coherencia
│   ├── bank.py                   BankNotification (movimiento bancario)
│   ├── llm.py                    bloques neutrales (texto/imagen/PDF), Capabilities, LLMResult
│   ├── catalog.py, files.py, periods.py, values.py, errors.py
│   └── ports/                    repositories, storage, identity, llm, extraction, mail, crypto
├── application/
│   ├── purchases.py, imports.py, categories.py, users.py, reports.py
│   ├── security/                 confirmations.py, account_actions.py
│   ├── agents/                   base.py, registry.py, settings.py, prompts/*.md
│   └── bank_emails/              mailboxes.py, sync.py
├── infrastructure/
│   ├── persistence/              registry.py, sqlalchemy/ (tables, orm, repositorios, migraciones), memory/
│   ├── llm/                      anthropic, openai (+compatibles y Ollama), gemini, fake, fallback, registry
│   ├── extraction/               documents, regex, extractors (facturas), bank_rules, bank (notificaciones)
│   ├── mail/                     smtp, console, imap, rendering, templates/layout.html
│   ├── identity/keycloak.py      acciones, cuenta de servicio, administración de cuenta, reautenticación
│   ├── crypto/fernet.py          cifrado de secretos
│   └── storage/local.py          archivos en disco
├── presentation/streamlit/
│   ├── app.py                    entrada: login, navegación por rol, barra lateral
│   ├── pages/                    resumen, tabla_resumen, importar, comparativa, configuracion
│   ├── components/               session, layout, formatting, forms, files, profile, settings/
│   └── assets/styles.css
└── worker/__main__.py            `python -m billing.worker`: sincroniza buzones IMAP
infra/
├── docker/app/                   imagen de la app y del worker, entrypoint
├── docker/keycloak/              imagen de Keycloak, realm, temas login/email, script de Google
├── docker/postgres/, pgadmin/    inicialización de bases y servidor de pgAdmin
└── terraform/                    esqueleto AWS
scripts/                          write_secrets.py, seed_dev_data.py, send_bank_samples.py
docs/                             esta documentación
```

## Flujos principales

### Petición de una página

1. `app.py` lee los claims del ID token (`st.user`). Sin sesión, redirige a Keycloak (`st.login`).
2. Construye el `Viewer` (rol desde el claim `roles`), sincroniza el usuario en la base
   (`users.sync_from_claims`) y aplica las migraciones una vez por proceso.
3. `st.navigation` solo recibe las páginas permitidas para el rol (`auth.PAGES_BY_ROLE`).
4. La página pide adaptadores a `bootstrap`, abre `with bootstrap.unit_of_work() as uow:`
   y llama a los casos de uso con `owner_id = viewer.owner_filter(...)`.

### Importación (borrador → compra)

```
archivo/correo ─▶ imports.store_upload ─┬─ (correo) bank_parser ─▶ notificación bancaria
                                        └─ invoice_extractor ─────▶ factura
                    │ guarda el archivo (FileStorage) y un Attachment con purchase_id = NULL
                    ▼
            Importar facturas: revisión ─▶ imports.confirm_draft ─▶ Purchase
```

### Buzones bancarios

```
worker (cada N s) ─▶ sync.sync_all ─▶ por buzón: IMAP (solo lectura) ─▶ correos de remitentes
  configurados ─▶ bank_parser ─▶ imports.store_bank_email ─▶ borrador en Importar
```

### Acción sensible

```
solicitar ─▶ correo con enlace ─▶ confirmar enlace ─▶ (si 2FA) reautenticación en Keycloak
  con contraseña + código ─▶ ejecutar (o continuar en Keycloak) ─▶ solicitud consumida
```

Detalle en [servicios/seguridad.md](servicios/seguridad.md).

## Decisiones de diseño

- **Entidades como dataclasses + mapeo imperativo**: las clases del dominio no heredan de
  SQLAlchemy; `orm.py` las mapea. Otro motor puede guardarlas sin modificarlas.
- **Unidad de trabajo explícita**: `with uow: ...; uow.commit()`. Salir sin commit descarta.
  `SqlAlchemyUnitOfWork.__exit__` usa solo `session.close()` (no `rollback()`) para que los
  objetos leídos sigan siendo legibles fuera del bloque.
- **Filtro de dueño obligatorio**: toda consulta de datos de usuario recibe `owner_id`
  (keyword obligatorio); `None` = todos y solo lo produce `Viewer.owner_filter` para roles
  con `sees_all`.
- **La app nunca ve contraseñas ni secretos TOTP**: todo se hace en pantallas de Keycloak.
- **Las extracciones nunca bloquean una subida**: si el LLM falla, se usan reglas y se guarda
  el error en el borrador.
- **Proveedor LLM en tiempo de ejecución**: credenciales en el entorno, elección en la base.
