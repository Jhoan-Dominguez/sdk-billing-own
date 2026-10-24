# Modelo de datos

Las entidades son dataclasses en `src/compras/domain/models.py`. El adaptador SQL las mapea
de forma imperativa (`infrastructure/persistence/sqlalchemy/orm.py`) a las tablas definidas
en `tables.py`; el adaptador en memoria las guarda tal cual. Los campos marcados
`init=False` los rellena el almacenamiento (ids, fechas por defecto) o son relaciones.

## Diagrama

```
users 1───* purchases 1───* purchase_items
  │            │
  │            └──* attachments *───1 mailbox_connections
  │                    (purchase_id NULL = borrador)      │
  ├──* attachments                                        │
  ├──* categories (owner_id NULL = general)               │
  ├──* security_confirmations                             │
  ├──* mailbox_connections ───────────────────────────────┘
  └──* agent_settings.updated_by (SET NULL)
```

## Entidades y tablas

### `User` → `users`

Usuario del proveedor de identidad visto por la app. Se crea o actualiza en cada inicio de
sesión (`users.sync_from_claims`).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `String(64)` PK | no | Claim `sub` de Keycloak |
| `username` | `String(150)` | no | `preferred_username` o correo |
| `name` | `String(200)` | sí | Nombre completo |
| `email` | `String(254)` | sí | Correo (destino de las confirmaciones) |
| `role` | `String(20)` índice | no | `admin` o `cliente` |
| `created_at` / `last_login_at` | `DateTime` | no | Alta y último login |
| `avatar_name` | `String(64)` | sí | Archivo del avatar (`avatars/<nombre>`) |
| `preferred_currency` | `String(3)` | sí | Moneda preferida |
| `default_payment_method` / `default_category` | `String(50)` | sí | Valores por defecto del formulario |

Propiedad: `display_name` (nombre o usuario).

### `Purchase` → `purchases`

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `Integer` PK | no | |
| `owner_id` | FK `users.id`, índice | no | Dueño (regla de seguridad principal) |
| `purchase_date` | `Date`, índice | no | Fecha de la compra |
| `vendor` | `String(200)` | no | Comercio |
| `vendor_tax_id` / `invoice_number` | `String(50)` / `String(100)` | sí | NIT/RFC y número de factura (o referencia bancaria) |
| `category` | `String(50)`, índice | no | Nombre de la categoría (texto, no FK) |
| `payment_method` | `String(50)` | sí | Uno de `catalog.PAYMENT_METHODS` |
| `currency` | `String(3)` | no | ISO 4217 |
| `subtotal` / `tax` / `total` | `Numeric(12,2)` | sí / sí / no | Importes en `Decimal` |
| `notes` | `Text` | sí | |
| `source` | `String(20)` | no | `manual`, `imagen`, `pdf`, `email` o `banco` |
| `created_at` | `DateTime` | no | |

Relaciones: `items` (cascada delete-orphan), `attachments` (cascada), `owner` (solo lectura).

### `PurchaseItem` → `purchase_items`

`id`, `purchase_id` (FK `ON DELETE CASCADE`), `description String(300)`, `quantity Numeric(12,3)`,
`unit_price` y `line_total` `Numeric(12,2)`.

### `Attachment` → `attachments`

Archivo original. **Si `purchase_id` es NULL, es un borrador** pendiente de revisión: no hay
tabla de borradores aparte.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `Integer` PK | no | |
| `owner_id` | FK `users.id`, índice | no | |
| `purchase_id` | FK `purchases.id` `ON DELETE CASCADE`, índice | sí | Compra confirmada |
| `original_name` / `stored_name` | `String(255)` (`stored_name` único) | no | Nombre subido / clave en el almacenamiento (UUID + extensión) |
| `content_type` / `kind` | `String(100)` / `String(20)` | no | Tipo MIME y `imagen`/`pdf`/`email` |
| `size` / `sha256` | `Integer` / `String(64)` índice | no | Tamaño y hash (detección de duplicados) |
| `extracted_text` | `Text` | sí | Texto legible extraído |
| `extracted` | `JSON` | sí | `InvoiceData` (precarga del formulario) |
| `extraction_error` | `Text` | sí | Error de extracción (el borrador se guarda igualmente) |
| `extraction_meta` | `JSON` | sí | Cómo se extrajo (abajo) |
| `message_id` | `String(255)` | sí | `Message-ID` si llegó por un buzón |
| `mailbox_id` | FK `mailbox_connections.id` `ON DELETE SET NULL` | sí | Buzón de origen |
| `uploaded_at` | `DateTime` | no | |

Índice único `uq_attachments_owner_message (owner_id, message_id)`: un correo se importa una
sola vez por usuario (los NULL no chocan).

`extraction_meta`:

```json
{
  "document_type": "factura | notificacion_bancaria",
  "method": "llm | reglas",
  "agent": "invoice | bank_notification",
  "provider": "anthropic | openai | gemini | ollama",
  "model": "claude-opus-5-5",
  "duration_ms": 1830, "input_tokens": 1200, "output_tokens": 210,
  "warnings": ["Subtotal + impuestos (...) no coincide con el total (...)."],
  "bank": { "...": "BankNotification como dict (solo notificaciones)" },
  "fallback_errors": ["proveedor/modelo: error"]
}
```

Propiedades: `is_draft`, `document_type`.

### `Category` → `categories`

`id`, `name String(50)`, `owner_id` (FK `ON DELETE CASCADE`, NULL = **general**), `created_at`.
Las compras guardan el nombre, así que renombrar o borrar actualiza las compras
(`application/categories.py`). «Otros» es general y protegida (recibe las compras de las
categorías borradas).

Unicidad del nombre por ámbito, sin distinguir mayúsculas:

- PostgreSQL: `uq_categories_owner_name (owner_id, lower(name)) NULLS NOT DISTINCT`.
- Otros motores: `uq_categories_owner_name_portable (coalesce(owner_id, ''), lower(name))`.

`tables.DIALECT_SPECIFIC_INDEXES` le dice a Alembic qué índice corresponde a cada motor.

### `SecurityConfirmation` → `security_confirmations`

Solicitud de una acción sensible ([seguridad](servicios/seguridad.md)).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `Integer` PK | no | |
| `user_id` | FK `users.id` `ON DELETE CASCADE`, índice | no | |
| `purpose` | `String(30)` | no | `change_password`, `update_otp`, `remove_otp`, `delete_account` |
| `token_hash` | `String(64)` único | no | SHA-256 del token del enlace del correo |
| `requires_otp` | `Boolean` | no | Exige código 2FA |
| `expires_at` | `DateTime` | no | Caducidad (30 min) |
| `email_confirmed_at` | `DateTime` | sí | Enlace abierto |
| `reauth_state_hash` | `String(64)` único | sí | SHA-256 del `state` de la reautenticación en curso |
| `otp_verified_at` | `DateTime` | sí | 2FA verificado |
| `started_at` | `DateTime` | sí | Acción iniciada en Keycloak (marca para borrar el 2FA anterior) |
| `completed_at` / `cancelled_at` | `DateTime` | sí | Consumida / anulada |
| `created_at` | `DateTime` | no | La fija la app (mismo reloj que `expires_at`) |

Métodos: `is_active(now)`, `email_confirmed`, `otp_verified`, `is_ready`.

### `AgentSetting` → `agent_settings`

`agent String(50)` PK, `provider String(30)`, `model String(100)` (NULL = el del proveedor),
`updated_by` (FK `users.id` `ON DELETE SET NULL`), `updated_at`. Sin fila = valor por defecto
del entorno.

### `MailboxConnection` → `mailbox_connections`

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | `Integer` PK | no | |
| `owner_id` | FK `users.id` `ON DELETE CASCADE`, índice | no | |
| `host` / `port` / `use_ssl` | `String(255)` / `Integer` / `Boolean` | no | Servidor IMAP |
| `username` | `String(255)` | no | |
| `password_encrypted` | `Text` | no | Contraseña cifrada con Fernet |
| `folder` | `String(255)` | no | Carpeta (por defecto `INBOX`) |
| `sender_filter` | `Text` | no | Remitentes aceptados, separados por coma (direcciones o `@dominio`) |
| `enabled` | `Boolean` | no | Lo sincroniza el worker |
| `uid_validity` / `last_uid` | `BigInteger` | sí / no | Hasta dónde se leyó (UID de IMAP, 32 bits sin signo) |
| `last_sync_at` / `last_error` | `DateTime` / `Text` | sí | Estado de la última sincronización |
| `imported_count` | `Integer` | no | Movimientos importados en total |
| `created_at` | `DateTime` | no | |

Propiedad: `senders` (lista normalizada).

## Esquemas no persistidos (`pydantic`)

- `InvoiceData` / `ExtractedItem` (`domain/invoice.py`): salida del agente de facturas.
  Todo opcional: comercio, NIT, número, fecha `YYYY-MM-DD`, moneda, subtotal, impuestos,
  total, método de pago, categoría y líneas.
- `BankNotification` (`domain/bank.py`): `is_transaction`, banco, tipo (`compra`, `retiro`,
  `transferencia`, `pago`, `otro`), importe, moneda, comercio, fecha, hora, tipo y últimos 4
  dígitos de la tarjeta, referencia. `to_invoice()` la convierte en `InvoiceData`.

## Migraciones (Alembic)

Viven en `infrastructure/persistence/sqlalchemy/migrations/versions/`. La app aplica las
pendientes al arrancar (`bootstrap.init_database()`), y también el worker.

| Revisión | Contenido |
|---|---|
| `0001` | Línea base: `users`, `purchases`, `purchase_items`, `attachments` |
| `0002` | Preferencias y avatar en `users`; tabla `categories` con las categorías iniciales |
| `0003` | `security_confirmations` |
| `0004` | `agent_settings`; `attachments.extraction_meta` |
| `0005` | `mailbox_connections`; `attachments.message_id`, `mailbox_id` e índice único |

Las migraciones usan `op.batch_alter_table` para que funcionen también en SQLite. Para crear
una nueva: `.venv/bin/alembic revision -m "descripcion"` y escribir `upgrade`/`downgrade` a
mano; comprobar con `.venv/bin/alembic check` que el esquema coincide con `tables.py`.
