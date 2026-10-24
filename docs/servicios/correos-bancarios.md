# Notificaciones bancarias por correo

Los bancos envían una alerta por correo en cada compra con tarjeta, retiro, transferencia o
pago. Este servicio las convierte en **borradores de compra** en Importar facturas, por dos vías:

1. **Subiendo el `.eml`** en Importar facturas (se detecta solo).
2. **Conectando un buzón IMAP** (Gmail, Outlook, GreenMail en desarrollo): un worker lee las
   alertas nuevas de los remitentes del banco cada pocos minutos.

## Componentes

| Pieza | Archivo |
|---|---|
| Esquema del movimiento | `domain/bank.py` → `BankNotification`, `to_invoice()` |
| Puerto | `domain/ports/extraction.py` → `BankNotificationParser.parse(raw) -> ExtractionResult \| None` |
| Plantillas de reglas | `infrastructure/extraction/bank_rules.py` → `TEMPLATES`, `match()` |
| Lectores | `infrastructure/extraction/bank.py` → `RuleBankParser`, `LLMBankParser` |
| Agente LLM | `application/agents/registry.py` → `bank_notification` + `prompts/bank_notification.md` |
| Buzones | `application/bank_emails/mailboxes.py` (alta, edición, prueba, baja) |
| Sincronización | `application/bank_emails/sync.py` → `sync_mailbox`, `sync_all`, `SyncReport` |
| IMAP | `infrastructure/mail/imap.py` → `ImapGateway`, `ImapMailbox`, `sender_matches` |
| Cifrado | `infrastructure/crypto/fernet.py` → `FernetCipher` |
| Worker | `worker/__main__.py` (`python -m billing.worker`) |
| Interfaz | `components/settings/mailboxes.py` (Configuración → Correo bancario), `pages/importar.py` |
| Datos de prueba | `scripts/send_bank_samples.py` (`make bank-samples`) |

## Lectura de una alerta

`LLMBankParser.parse(raw_email)`:

1. **Reglas** (`RuleBankParser`): extrae el texto del correo (cabecera, cuerpo HTML → texto) y
   el remitente, elige las plantillas del banco por dominio del remitente (o, si es un
   reenvío, por el nombre del banco en el texto) y prueba sus patrones. Si alguno reconoce la
   alerta → `method=rules`. Gratis, instantáneo y sin red.
2. **Agente LLM**: si ninguna regla aplica y hay un agente disponible, `bank_notification`
   decide si es un movimiento (`is_transaction`) y extrae sus datos. Si no lo es (publicidad,
   códigos de verificación…) → `None` (no se importa).
   - Con `require_bank_sender=True` (correos subidos a mano) solo se llama al agente si el
     remitente es de un banco conocido o el texto menciona uno, para no gastar una llamada en
     cada factura por correo.
3. Resultado: `ExtractionResult` con `data = notification.to_invoice()` y
   `meta = {"document_type": "bank_notification", "method": …, "bank": {…}, "warnings": […]}`.

`to_invoice()`: comercio → `vendor`, importe → `total`, fecha → `purchase_date`, referencia →
`invoice_number`, moneda (COP por defecto en bancos colombianos) y método de pago
(crédito/débito → tarjeta; transferencia → Transferencia; retiro → Efectivo). Al confirmar, la
compra queda con `source = "bank"`.

## Plantillas de bancos colombianos

`bank_rules.TEMPLATES` (una `BankTemplate` por banco: nombre, dominios remitentes, palabra
clave y patrones). Los patrones usan grupos con nombre (`amount`, `merchant`, `date`, `time`,
`last4`, `card`); el texto se normaliza sin tildes y con espacios colapsados.

| Banco | Remitentes | Movimientos reconocidos | Ejemplo |
|---|---|---|---|
| Bancolombia | `notificacionesbancolombia.com`, `bancolombia.com.co` | compra (dos formatos), retiro, transferencia, pago | «Bancolombia: Compraste $45.900,00 en EXITO COLINA con tu T.Cred *4321, el 12/03/2026 a las 14:35.» |
| Davivienda | `davivienda.com` | compra, retiro (tabla «Fecha / Hora / Valor Transacción / Clase de Movimiento / Lugar de Transacción») | «…tarjeta Crédito terminada en 5544: Fecha: 2026/03/18 Hora: 13:05:44 Valor Transacción: $62,300 Clase de Movimiento: Compra Lugar de Transacción: FARMATODO CHAPINERO» |
| BBVA Colombia | `bbva.com.co`, `bbva.com` | compra | «BBVA te informa: se realizó una compra por $39.990,00 en NETFLIX.COM con tu tarjeta de crédito terminada en 9087 el 20/03/2026 a las 07:00.» |
| Banco de Bogotá | `bancodebogota.com.co`, `bancodebogota.com` | compra | «Banco de Bogotá le informa compra por $54.200 en TERPEL CALLE 80 con tarjeta Crédito *3141 el 2026-03-21 17:48.» |

Nequi y cualquier otro banco sin plantilla se leen con el agente LLM.

Importes: `regex.parse_amount` entiende el formato colombiano (`$45.900,00`, `$200.000`) y el
inverso (`$62,300`, `$45,900.00`).

> Los textos siguen el formato habitual de cada banco, pero los bancos los cambian con el
> tiempo. Si una alerta real deja de reconocerse, el agente LLM la cubre, y se puede añadir o
> ajustar un `Pattern` (con su `example`) en `bank_rules.py`.

### Añadir un banco

```python
BankTemplate(
    bank="Scotiabank Colpatria",
    senders=("scotiabankcolpatria.com",),
    keyword="colpatria",
    patterns=(
        _p(
            PURCHASE,  # domain/bank.py: PURCHASE, WITHDRAWAL, TRANSFER, PAYMENT
            rf"compra por {_AMOUNT} en {_MERCHANT} con tu tarjeta \*(?P<last4>\d{{4}}) el {_DATE_DMY} a las {_TIME}",
            "Colpatria: compra por $10.000 en D1 con tu tarjeta *1234 el 01/04/2026 a las 08:05.",
        ),
    ),
)
```

Comprobación rápida de todas las plantillas con sus ejemplos:

```bash
.venv/bin/python -c "from billing.infrastructure.extraction import bank_rules as b; \
print(all(b.match(p.example, 'x@' + t.senders[0]) for t in b.TEMPLATES for p in t.patterns))"
```

## Buzones IMAP

### Conexión (Configuración → Correo bancario)

Formulario: servidor, puerto, SSL, usuario, contraseña de aplicación, carpeta (`INBOX`),
remitentes del banco (direcciones o `@dominio` separados por coma; por defecto los de los
bancos de la tabla y `@nequi.com.co`) y «Sincronizar automáticamente». Botones **Probar
conexión**, **Guardar**, **Sincronizar ahora**, **Editar** y **Desconectar buzón**. Se ve el
estado: última sincronización, movimientos importados y último error.

- Máximo 5 buzones por usuario. Cada usuario solo ve y gestiona los suyos.
- La contraseña se cifra con Fernet (`BILLING_SECRET_KEY`) y nunca se muestra; al editar,
  dejarla vacía conserva la actual.
- Cambiar servidor, usuario o carpeta reinicia la lectura desde el principio.
- Desconectar conserva los borradores ya importados.

| Proveedor | Servidor | Puerto | SSL | Contraseña |
|---|---|---|---|---|
| Gmail | `imap.gmail.com` | 993 | sí | Contraseña de aplicación (requiere verificación en 2 pasos de Google) |
| Outlook / Hotmail | `outlook.office365.com` | 993 | sí | Contraseña de aplicación |
| GreenMail (desarrollo) | `greenmail` (Docker) o `localhost` | 3143 | no | `Bandeja-Compras-2026` |

### Sincronización

`sync.sync_mailbox(uow, mailbox, gateway, cipher, parser, storage, batch)`:

1. Descifra la contraseña y abre la carpeta **en solo lectura** (`EXAMINE`; las descargas usan
   `BODY.PEEK`): no marca como leído, no mueve ni borra nada.
2. Busca los UID mayores que `last_uid`; de cada uno lee primero solo el `From` y descarga el
   correo completo únicamente si el remitente coincide con el filtro (hasta `batch` correos).
3. Si cambió el `UIDVALIDITY` de la carpeta (el servidor la renumeró), vuelve a leer desde 0.
4. Por cada correo: si su `Message-ID` ya se importó para ese usuario → se omite; si no es un
   movimiento → se omite; si lo es → `imports.store_bank_email()` crea el borrador (archivo
   `.eml` con el asunto como nombre, `message_id` y `mailbox_id`).
5. Guarda `uid_validity`, `last_uid`, `last_sync_at`, `imported_count` y `last_error`.
   **Nunca lanza**: los errores de conexión o de descifrado quedan en el buzón y en el informe.

`SyncReport.summary()`: «N correos revisados, M movimientos importados, K omitidos».

### Worker

```bash
python -m billing.worker              # bucle cada BILLING_MAIL_SYNC_INTERVAL segundos
python -m billing.worker --once       # una pasada (make sync-once en Docker)
python -m billing.worker --interval 30
```

- Servicio `worker` de Docker Compose (misma imagen que la app, `BILLING_SKIP_SECRETS=1`).
- `sync_all()` procesa cada buzón activo en su propia transacción; un fallo no detiene el bucle.
- Aplica las migraciones al arrancar, se detiene limpiamente con SIGTERM/SIGINT y toca
  `/tmp/worker-alive` tras cada pasada (healthcheck: menos de 10 minutos).

## Duplicados

- **Mismo correo**: índice único `(owner_id, message_id)` y comprobación previa con `by_message_id`.
- **Mismo pago por dos vías** (factura y alerta): aviso «Ya tienes una compra con el mismo total
  en fechas cercanas» en el borrador (`similar_purchases`, ±2 días).

## Pruebas en desarrollo

Ver [correo de pruebas](../infraestructura/correo-de-pruebas.md). En resumen:

```bash
make bank-samples        # envía 8 alertas a cliente@billing.example.com y conecta su buzón
make sync-once           # o «Sincronizar ahora» en la app, o esperar al worker
```

Se envían alertas de Bancolombia (compra, retiro, pago), Davivienda, BBVA, Banco de Bogotá
y Nequi, más un correo publicitario. Resultado verificado: 6 movimientos importados por reglas;
Nequi se importa si hay un agente LLM configurado; la publicidad se omite; una segunda
sincronización no duplica nada.
