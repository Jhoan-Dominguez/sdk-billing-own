# Correo de pruebas: Mailpit y GreenMail

En desarrollo **ningún correo sale a Internet**: no hace falta (ni se debe) usar un
servidor de correo real. Hay dos servidores locales, uno por sentido:

| | Mailpit | GreenMail |
|---|---|---|
| Para qué | Ver los correos que **envían** la app y Keycloak | Hacer de **bandeja de entrada** de la que la app **lee** por IMAP |
| Protocolos | SMTP (recibe) + interfaz web y API | SMTP (recibe) + IMAP (sirve los buzones) |
| Acceso | http://localhost:8025 | IMAP `localhost:3143` (en Docker `greenmail:3143`), SMTP `3025` |
| Quién le envía | App (`SMTP_HOST=mailpit`) y Keycloak (`smtpServer`) | `scripts/send_bank_samples.py` (simula los bancos) |
| Quién lee | Tú, en el navegador | El worker y «Sincronizar ahora» (como si fuera Gmail) |
| Persistencia | En memoria (máx. 2000 mensajes) | En memoria |

## Mailpit (correo saliente)

Captura todo lo que se envía por SMTP, a cualquier dirección (acepta cualquier usuario y
contraseña). Ahí aparecen:

- «Activa tu cuenta de Registro de compras» (registro) y «Recupera tu contraseña» (Keycloak).
- «Confirma: cambio de contraseña», «…desactivar verificación en dos pasos», «…eliminación de
  la cuenta» (app).

Probar un registro completo: http://localhost:8502 → Crear cuenta → abrir http://localhost:8025
→ abrir el correo → «Activar mi cuenta» → crear la contraseña.

API útil para scripts: `GET http://localhost:8025/api/v1/messages`,
`GET /api/v1/search?query=to:"correo"`, `GET /api/v1/message/<ID>`.

En producción se cambia `SMTP_HOST`/`SMTP_PORT`/`SMTP_AUTH`/`SMTP_USER`/`SMTP_PASSWORD`/
`SMTP_STARTTLS` por los de un servidor real (Amazon SES, por ejemplo) y se reimporta el realm
o se edita el SMTP en la consola de Keycloak.

## GreenMail (bandeja de entrada IMAP)

Servidor de correo de pruebas que acepta correo por SMTP para cualquier dirección y lo
sirve por IMAP. Los buzones con contraseña se definen en `GREENMAIL_USERS`
(`usuario:contraseña@dominio`, el inicio de sesión es el correo completo):

| Buzón | Contraseña |
|---|---|
| `cliente@billing.example.com` | `Bandeja-Compras-2026` |
| `maria.lopez@billing.example.com` | `Bandeja-Compras-2026` |

### Probar las notificaciones bancarias

```bash
make bank-samples                                   # a cliente@ y conecta su buzón en la app
make bank-samples TO=maria.lopez@billing.example.com
make sync-once                                      # o espera al worker (BILLING_MAIL_SYNC_INTERVAL)
```

`send_bank_samples.py` envía 8 correos con fechas de los últimos días: Bancolombia (compra,
retiro, pago), Davivienda (compra), BBVA (compra), Banco de Bogotá (compra), Nequi (pago, lo
lee el agente LLM) y una publicidad de Bancolombia (no debe importarse). Con `--connect` crea
la conexión IMAP del usuario dueño de ese correo hacia GreenMail (servidor `greenmail` dentro
de Docker, `localhost` fuera; puerto 3143, sin SSL).

Para conectar el buzón a mano: Configuración → Correo bancario → servidor `greenmail` (si la
app corre en Docker) o `localhost` (`make dev`), puerto `3143`, SSL desactivado, usuario
`cliente@billing.example.com`, contraseña `Bandeja-Compras-2026`.

También se puede enviar cualquier `.eml` a GreenMail:

```bash
python - <<'PY'
import smtplib; from email.message import EmailMessage
m = EmailMessage(); m["From"] = "alertas@bbva.com.co"; m["To"] = "cliente@billing.example.com"
m["Subject"] = "BBVA te informa"; m.set_content("BBVA te informa: se realizó una compra por $12.000,00 en D1 con tu tarjeta de débito terminada en 1111 el 01/10/2026 a las 10:00.")
smtplib.SMTP("localhost", 3025).send_message(m)
PY
```

Reiniciar GreenMail (`docker compose restart greenmail`) vacía los buzones.
