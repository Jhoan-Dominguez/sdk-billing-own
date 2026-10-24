# Keycloak

Keycloak 26.8 en una imagen propia (`infra/docker/keycloak/`). Contiene el realm `compras`,
el tema `compras` (login y correo) y el README como panel informativo del login.

## Realm `compras` (`realm-compras.json`)

Se importa **solo si el realm no existe** (arranque con `--import-realm` sobre una base
vacía). Los marcadores `${VAR}` se sustituyen con variables del contenedor. Para aplicar
cambios del JSON: `make keycloak-reimport`, que borra y recrea la base `keycloak` y borra los
usuarios registrados a mano (las compras no se tocan; los usuarios de desarrollo tienen ids
fijos, así que conservan sus datos).

### Ajustes principales

| Ajuste | Valor | Efecto |
|---|---|---|
| `registrationAllowed` | `true` | «Crear cuenta» en el login |
| `registrationEmailAsUsername`, `loginWithEmailAllowed` | `true` | Se entra con el correo |
| `verifyEmail` | `true` | Las cuentas nuevas se activan desde el correo; la contraseña se crea después |
| `resetPasswordAllowed` | `true` | «¿Olvidaste tu contraseña?» por correo |
| `actionTokenGeneratedByUserLifespan` | `1800` | Enlaces de correo válidos 30 min |
| `duplicateEmailsAllowed` | `false` | |
| `passwordPolicy` | `length(8) and notUsername` | |
| `bruteForceProtected`, `failureFactor` | `true`, `5` | Bloqueo temporal tras 5 intentos |
| `otpPolicy*` | TOTP, HmacSHA1, 6 dígitos, 30 s, ventana 1, no reutilizable | |
| `loginTheme`, `emailTheme` | `compras` | |
| `defaultLocale`, `supportedLocales` | `es` | |
| `smtpServer` | `${SMTP_HOST}:${SMTP_PORT}`, remitente `${SMTP_FROM}` «Registro de compras», `auth`/`user`/`password`/`starttls`/`ssl` desde `SMTP_*` | Correo de Keycloak (Mailpit en desarrollo) |
| `browserFlow`, `registrationFlow`, `resetCredentialsFlow` | `browser`, `registration`, `reset credentials` | |

### Roles

`admin`, `cliente`, y los obligatorios `offline_access` y `uma_authorization` (el import falla
sin ellos). `default-roles-compras` incluye `cliente`: toda cuenta nueva (registro o Google) es cliente.

### Clientes

| Cliente | Tipo | Uso |
|---|---|---|
| `compras-app` | Confidencial (`${KEYCLOAK_CLIENT_SECRET}`), *standard flow* | Login de Streamlit, acciones `kc_action` y reautenticación. Redirecciones `http://localhost:8501` y `:${APP_PORT}` a `/oauth2callback` y `/configuracion`. Mappers: **realm roles** → claim `roles`; **amr** → claim `amr` |
| `compras-admin-api` | Cuenta de servicio (`${KEYCLOAK_ADMIN_API_SECRET}`) | La app gestiona con ella la cuenta del propio usuario. Roles de `realm-management`: `view-users`, `manage-users` (sin acceso al realm `master` ni a clientes) |

### Usuarios de desarrollo

Ids fijos (coinciden con `scripts/seed_dev_data.py`), correo verificado y contraseñas de
`COMPRAS_ADMIN_PASSWORD` / `COMPRAS_CLIENTE_PASSWORD`:

| Id | Correo | Rol |
|---|---|---|
| `8f1c2a3e-0000-4000-8000-000000000001` | `admin@compras.example.com` | admin |
| `…0101` | `cliente@compras.example.com` (Carlos Mendoza) | cliente |
| `…0102` | `maria.lopez@compras.example.com` | cliente |
| `…0103` | `juan.perez@compras.example.com` | cliente |
| `…0104` | `sofia.ramirez@compras.example.com` | cliente |

### Flujos de autenticación

El JSON incluye todos los flujos (`authenticationFlows`) y sus configuraciones
(`authenticatorConfig`), porque el flujo `browser` necesita referencias AMR:

```
browser
├── Cookie                                   ALTERNATIVE
├── Identity Provider Redirector             ALTERNATIVE
├── Organization …                           ALTERNATIVE
└── forms                                    ALTERNATIVE
    ├── Username Password Form [amr-pwd → "pwd"]   REQUIRED
    └── Browser - Conditional 2FA            CONDITIONAL
        ├── Condition - user configured      REQUIRED
        ├── Condition - credential           REQUIRED
        └── OTP Form [amr-otp → "otp"]       ALTERNATIVE
```

- Con 2FA configurado se pide el código; sin él, se entra con la contraseña.
- `amr-pwd` y `amr-otp` (`default.reference.value`) hacen que el ID token lleve
  `"amr": ["pwd", "otp"]` cuando se usaron ambos. La app lo exige para las acciones
  sensibles ([seguridad](../servicios/seguridad.md)).
- `registration`: *Registration User Profile Creation* y *Password Validation*. Con
  `verifyEmail`, Keycloak 26.8 aplaza la contraseña hasta confirmar el correo.

## Tema `compras`

### Login (`themes/compras/login`)

- `theme.properties`: `parent=base` (HTML sin estilos) y cada `kc*Class` mapeado a clases
  `cp-*` de `resources/css/compras.css` (paleta de la app, modo claro y oscuro).
- `template.ftl`: dos columnas (formulario a la izquierda, `info.ftl` a la derecha).
- `login.ftl`: correo, contraseña, «¿Olvidaste tu contraseña?», «Iniciar sesión» junto a
  «Crear cuenta», y «Continuar con Google» (deshabilitado hasta que exista el IdP `google`).
- `messages/messages_es.properties`: textos propios (también los de verificar el correo,
  recuperar la contraseña y el 2FA).
- El resto de páginas (registro, OTP, configurar TOTP, verificar correo, actualizar
  contraseña) vienen de `base` con este diseño.
- `info.ftl` = README.md convertido a HTML al construir la imagen. **Antes de publicar en
  producción hay que quitarlo o cambiarlo**: el README contiene las contraseñas de desarrollo.

### Correo (`themes/compras/email`)

- `html/template.ftl`: macro `emailLayout` con el mismo diseño que los correos de la app
  (`src/compras/infrastructure/mail/templates/layout.html`). Los mensajes pasan por
  `kcSanitize`, que quita estilos en línea, así que los estilos están en el `<style>` de la plantilla.
- `messages/messages_es.properties`: asuntos y textos de activación, recuperación de
  contraseña, acciones pendientes, prueba de SMTP y nombres de las acciones requeridas.

Tras cambiar el tema o el README: `make up SERVICE=keycloak`.

## Google como proveedor

`configure-google.sh` crea o actualiza el IdP `google` con `kcadm` (o lo quita con
`--remove`), usando `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`. URI de redirección en Google
Cloud: `http://localhost:8180/realms/compras/broker/google/endpoint`.

## Producción

Pendiente (ver [aws-terraform.md](aws-terraform.md)): arrancar con `start` (no `start-dev`)
detrás de HTTPS, hostname público, SMTP real, quitar `info.ftl` con el README y las
contraseñas de desarrollo del realm.
