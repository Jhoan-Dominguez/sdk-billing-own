# Casos de uso (`src/billing/application/`)

Funciones sin estado que reciben la unidad de trabajo y los adaptadores que necesitan. No
importan Streamlit ni infraestructura, así que sirven igual a la app web, al worker y a los scripts.

Convención: las funciones que leen datos de usuarios reciben `owner_id` como keyword
obligatorio (`None` = todos, solo para roles con `sees_all`). Los errores de validación se
lanzan como `domain.errors.ValidationError` con mensajes en español listos para mostrar.

## `purchases.py` — compras

| Función | Descripción |
|---|---|
| `apply_values(purchase, values, items)` | Valida y copia los valores del formulario: fecha y comercio obligatorios; importes a `Decimal` (acepta coma decimal y NaN de pandas); ignora líneas sin descripción; calcula `line_total` = cantidad × precio; si no hay total, lo calcula con las líneas o con subtotal + impuestos; recorta textos al tamaño de la columna |
| `create(uow, values, items, *, owner_id, source="manual")` | Alta |
| `update(uow, purchase, values, items)` | Edición (rollback si no valida) |
| `delete(uow, storage, purchase)` | Borra la compra y sus archivos |
| `get(uow, id, *, owner_id)` | La compra si es visible con ese filtro |
| `between(uow, start, end, *, owner_id)` / `in_month(uow, "2026-10", *, owner_id)` | Compras de un rango, de la más reciente a la más antigua |
| `form_values(purchase)` | Valores para precargar el formulario |

## `imports.py` — importación (borrador → compra)

| Función | Descripción |
|---|---|
| `store_upload(uow, storage, extractor, filename, content_type, raw, *, owner_id, bank_parser=None)` | Clasifica el archivo; si es correo prueba primero `bank_parser`; si no, `extractor` con las categorías del dueño; guarda archivo y borrador |
| `store_bank_email(uow, storage, raw, result, *, owner_id, message_id, mailbox_id, subject)` | Borrador de una notificación leída de un buzón |
| `confirm_draft(uow, att, values, items)` | Crea la compra (`source=banco` si era una notificación) y vincula el adjunto |
| `discard_draft(uow, storage, att)` | Borra el borrador y su archivo |
| `drafts(uow, *, owner_id)` / `get_draft(uow, id, *, owner_id)` | Borradores pendientes |
| `draft_values(att, categories)` | Valores extraídos para el formulario (descarta categoría o método no válidos) |
| `find_duplicates(uow, att)` | Mismo SHA-256 del mismo usuario |
| `similar_purchases(uow, att)` | Compras con el mismo total y fecha ±2 días |
| `read_file(storage, att)` | Bytes del archivo original |

Si falla el guardado de la fila, el archivo recién guardado se borra (no quedan huérfanos).

## `categories.py` — categorías

| Función | Descripción |
|---|---|
| `visible_to(uow, *, owner_id)` / `names(...)` | Generales + personales, con «Otros» al final |
| `usage(uow, *, owner_id)` | Compras por categoría |
| `get(uow, id)` | |
| `create(uow, name, *, owner_id)` | `owner_id=None` = general. Nombre obligatorio, ≤ 50 caracteres, único en su ámbito y frente a las generales |
| `rename(uow, category, new_name)` | Renombra y actualiza compras (y preferencias) afectadas; devuelve cuántas compras cambió |
| `delete(uow, category)` | Sus compras pasan a «Otros» (protegida); devuelve cuántas movió |

Al renombrar o borrar una general, las compras de usuarios con una personal del mismo nombre
no se tocan.

## `users.py` — usuarios

| Función | Descripción |
|---|---|
| `sync_from_claims(uow, claims, role)` | Alta o actualización con los claims del ID token en cada login |
| `get`, `list_users(uow, role=None)` | |
| `currency(user)`, `form_defaults(user)` | Preferencias (moneda, método, categoría por defecto) |
| `update_profile(uow, account, user, first, last)` | Nombre y apellido en Keycloak y en la app |
| `update_preferences(uow, user, *, currency, payment_method, category)` | Valida y guarda |
| `set_avatar`, `remove_avatar`, `read_avatar` | Avatar ≤ 5 MB, recortado a 256×256 PNG |
| `delete_account(uow, storage, account, user)` | Borra la identidad en Keycloak y después compras, archivos, borradores, avatar, buzones, confirmaciones y el usuario |

## `reports.py`

`totals_by(purchases, key)` → `{clave: {moneda: total}}`. Las monedas nunca se suman entre sí.

## `security/` — acciones sensibles

Ver [servicios/seguridad.md](../servicios/seguridad.md).

- `confirmations.py`: `request`, `confirm_email`, `start_otp_check`, `verify_otp`, `active`,
  `cancel`, `mark_started`, `complete`. Constante `QUERY_TOKEN = "confirmar"`.
- `account_actions.py`: `continue_url` (enlace a Keycloak para contraseña o 2FA),
  `finish_identity_action` (cierre al volver con éxito), `execute` (desactivar 2FA, eliminar
  cuenta) → `Outcome(message, logged_out)`.

## `agents/` — agentes LLM

Ver [servicios/agentes.md](../servicios/agentes.md). `base.py` (`AgentSpec`, `Agent`),
`registry.py` (`AGENTS`, `INVOICE`, `BANK_NOTIFICATION`), `settings.py` (`resolve`, `save`,
`reset`), `prompts/`.

## `bank_emails/` — notificaciones bancarias

Ver [servicios/correos-bancarios.md](../servicios/correos-bancarios.md).

- `mailboxes.py`: `MailboxForm`, `DEFAULT_SENDERS`, `MAX_MAILBOXES`, `get`, `for_owner`,
  `create`, `update`, `delete`, `test_connection`.
- `sync.py`: `SyncReport`, `sync_mailbox`, `sync_all`.

## Dominio (`src/billing/domain/`)

| Módulo | Contenido |
|---|---|
| `models.py` | Entidades ([modelo de datos](../modelo-de-datos.md)) |
| `auth.py` | Roles `admin`/`cliente`, `PAGES_BY_ROLE`, `Viewer`, `viewer_from_claims`, `primary_role` |
| `security.py` | Propósitos de confirmación y sus parámetros |
| `invoice.py` | `InvoiceData`, `ExtractionResult`, `consistency_warnings` |
| `bank.py` | `BankNotification`, `TRANSACTION_TYPES`, `parse_date` |
| `llm.py` | Bloques, `Capabilities`, `LLMResult` |
| `catalog.py` | Categorías iniciales, «Otros», métodos de pago, monedas, orígenes (`manual`, `banco`), tipos de documento |
| `files.py` | Tipos de archivo aceptados y `classify` |
| `periods.py` | `month_key`, `month_bounds`, `last_months` |
| `values.py` | `clean_str`, `truncate`, `to_decimal`, `CENT` |
| `errors.py` | `ValidationError`, `UnsupportedFile`, `NotFound` |
