# Seguridad de la cuenta

Tres mecanismos, todos sobre Keycloak y el correo:

1. **Verificación en dos pasos (2FA)** opcional, que el usuario activa por su cuenta.
2. **Activación de cuentas nuevas por correo** (y recuperación de contraseña por correo).
3. **Confirmación de acciones sensibles**: correo y, si hay 2FA, código.

La app nunca ve contraseñas ni secretos TOTP: se escriben siempre en pantallas de Keycloak
(tema `billing`).

## 1. Verificación en dos pasos

- Se activa en **Configuración → Seguridad → Activar 2FA**. El botón abre la acción
  `CONFIGURE_TOTP` de Keycloak (`kc_action`), que muestra el QR y pide un código. Activarla
  no necesita confirmación por correo: añade protección, no la quita.
- Política (realm): TOTP, 6 dígitos, 30 s, ventana ±1, **un código no se puede reutilizar**
  (`otpPolicyCodeReusable: false`). Sirve con Google Authenticator, Microsoft Authenticator o FreeOTP.
- **Al iniciar sesión**, el flujo `browser` de Keycloak tiene el subflujo condicional
  *Browser - Conditional 2FA*:
  - sin 2FA configurado → entra directamente con correo y contraseña;
  - con 2FA → tras la contraseña pide el código (`login-otp`).

## 2. Activación de cuentas por correo

- Realm con `verifyEmail: true` y SMTP configurado (`smtpServer`, ver [correo](correo.md)).
- **Registro** («Crear cuenta»): el formulario pide correo, nombre y apellido. En Keycloak
  26.8, con la verificación activada, **la contraseña se crea después de confirmar el
  correo**:
  1. Keycloak muestra «Verifica tu correo» y envía «Activa tu cuenta de Registro de compras».
  2. El enlace (válido 30 min, `actionTokenGeneratedByUserLifespan: 1800`) confirma la dirección.
  3. Keycloak pide crear la contraseña y entra en la app.
- **¿Olvidaste tu contraseña?** (`resetPasswordAllowed: true`): envía un enlace para crear
  una nueva. El flujo `reset credentials` también pide el 2FA si está activo.
- Las cuentas de Google llegan con el correo ya verificado (`trustEmail` en el IdP).
- Los 5 usuarios de desarrollo del realm tienen `emailVerified: true`.

## 3. Confirmación de acciones sensibles

### Qué exige cada acción

Definido en `domain/security.py` (`PURPOSES`):

| Acción (`purpose`) | Correo | Código 2FA | Se completa en |
|---|---|---|---|
| Cambiar contraseña (`change_password`) | ✔ | — | Keycloak (`UPDATE_PASSWORD`) |
| Cambiar dispositivo 2FA (`update_otp`) | ✔ | ✔ | Keycloak (`CONFIGURE_TOTP`); al volver se borra el dispositivo anterior |
| Desactivar 2FA (`remove_otp`) | ✔ | ✔ | La app (API de administración) |
| Eliminar la cuenta (`delete_account`) | ✔ | ✔ si lo tiene activado | La app |

Las cuentas de administrador no pueden eliminarse a sí mismas (`CANNOT_SELF_DELETE_ROLES`).

Parámetros: enlace y solicitud válidos 30 min (`CONFIRMATION_TTL`), un correo nuevo por
acción cada 60 s como máximo (`RESEND_COOLDOWN`), reautenticación de hace menos de 5 min
(`REAUTH_MAX_AGE`).

### Flujo

```
 Usuario                App (Configuración)                 Keycloak / Correo
    │ «Cambiar…»              │                                    │
    ├────────────────────────▶│ confirmations.request()            │
    │                         │  token aleatorio (32 B) → SHA-256  │
    │                         │  guarda SecurityConfirmation       │
    │                         ├── correo con enlace ──────────────▶│ Mailpit / SMTP
    │ abre el enlace          │                                    │
    ├────────────────────────▶│ ?confirmar=<token>                 │
    │                         │ confirmations.confirm_email()      │
    │                         │  (mismo usuario, vigente)          │
    │ «Verificar con 2FA»     │                                    │
    ├────────────────────────▶│ start_otp_check(): state + nonce   │
    │                         ├── redirección prompt=login,        │
    │                         │   max_age=0, login_hint ──────────▶│ pide contraseña + código
    │                         │◀── /configuracion?state&code ──────┤
    │                         │ verify_otp(): canjea el code con   │
    │                         │  el secreto del cliente, valida el │
    │                         │  ID token (JWKS, iss, aud, nonce), │
    │                         │  sub, auth_time y amr ∋ "otp"      │
    │ botón final / enlace    │                                    │
    ├────────────────────────▶│ account_actions.execute() o        │
    │                         │ continue_url() → kc_action ───────▶│ pantalla de Keycloak
    │                         │◀── kc_action_status=success ───────┤
    │                         │ finish_identity_action()           │
```

### Componentes

| Pieza | Archivo | Papel |
|---|---|---|
| Reglas | `domain/security.py` | Propósitos, TTL, cooldown, valores `amr` válidos (`otp`, `totp`, `mfa`) |
| Entidad | `domain/models.py` → `SecurityConfirmation` | Estado de cada solicitud |
| Servicio | `application/security/confirmations.py` | `request`, `confirm_email`, `start_otp_check`, `verify_otp`, `active`, `cancel`, `mark_started`, `complete` |
| Ejecución | `application/security/account_actions.py` | `continue_url`, `finish_identity_action`, `execute` |
| Puertos | `domain/ports/identity.py` (`Reauthenticator`, `AccountAdmin`, `AccountActions`), `domain/ports/mail.py` (`Mailer`) | |
| Adaptadores | `infrastructure/identity/keycloak.py` (`KeycloakReauthenticator`, `KeycloakAccountAdmin`, `KeycloakActions`), `infrastructure/mail/smtp.py` | |
| Interfaz | `presentation/streamlit/components/settings/security.py` (`handle_return`, `confirmation_flow`), `.../settings/account.py` | |

### Cómo se prueba el 2FA

El cliente `billing-app` tiene el mapper **`amr`** (`oidc-amr-mapper`) y el flujo `browser`
asigna referencias a sus autenticadores mediante `authenticatorConfig` del realm:

| Autenticador | Configuración | Valor `amr` |
|---|---|---|
| Username Password Form | `amr-pwd` | `pwd` |
| OTP Form | `amr-otp` | `otp` |

Así, un ID token emitido tras pedir contraseña y código lleva `"amr": ["pwd", "otp"]`. Sin
esas configuraciones el claim llega vacío. Por eso el realm incluye los flujos completos
(`authenticationFlows`).

### Garantías

- El token del enlace y el `state` solo se guardan como hash SHA-256.
- El enlace vale **una sola vez**, para **un solo propósito** y para **el usuario que lo
  pidió**: abierto con otra sesión, se rechaza.
- Pedir otra vez la misma acción anula la solicitud anterior.
- El `state` de la reautenticación se invalida al primer intento, salga bien o mal, y el
  `nonce` derivado del `state` evita reutilizar un ID token.
- Se rechaza la verificación si el `sub` es de otra cuenta, si `auth_time` es antiguo o
  anterior a la solicitud, o si falta `otp` en `amr` cuando se exige.
- Al cambiar el dispositivo 2FA, el anterior se borra solo cuando Keycloak vuelve con éxito
  (`remove_otp(created_before=started_at)`): quien cancela a mitad no se queda sin 2FA.
- Eliminar la cuenta borra primero la identidad en Keycloak (si falla, no se pierde nada) y
  después compras, archivos, borradores, avatar, buzones, confirmaciones y el usuario.

### Limitaciones conocidas

- El enlace del correo debe abrirse en un navegador con la sesión de la app iniciada. Si no
  lo está, el login lleva a la página principal y se pierde el parámetro: basta volver a
  abrir el enlace.
- Las acciones de Keycloak (`kc_action=UPDATE_PASSWORD`) son accesibles para cualquier
  sesión autenticada que construya la URL a mano; Keycloak exige en ese caso volver a
  escribir la contraseña (y el 2FA). La consola de cuenta de Keycloak no está habilitada
  (los usuarios no tienen los roles `account`), así que la app es la única vía para quitar el
  2FA o borrar la cuenta.

## Sesiones

En Seguridad se listan las sesiones abiertas en Keycloak y se pueden cerrar todas
(`logout_everywhere`). Cerrar sesión (`session.logout()`) borra la cookie de Streamlit, vacía
`st.session_state` y termina la sesión SSO de Keycloak (`end_session_endpoint`). El login usa
además `prompt=login`, así que siempre pide credenciales.

## Verificación realizada

Un script de punta a punta contra Keycloak y Mailpit reales comprobó: registro con
«Verifica tu correo» y correo de activación, creación de contraseña tras el enlace, login
directo sin 2FA, activación del 2FA y login con código, cambio de contraseña confirmado por
correo, rechazo de un `code` falso y de un `state` reutilizado, cambio de dispositivo 2FA
(se conserva solo el nuevo), desactivación del 2FA con correo y código, y eliminación de la
cuenta en Keycloak y en la app.
