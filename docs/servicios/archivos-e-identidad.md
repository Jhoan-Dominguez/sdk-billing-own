# Archivos, identidad y cifrado

## Archivos (`FileStorage`)

```python
class FileStorage(Protocol):
    def save(self, key: str, data: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...  # FileNotFoundError si no existe
    def delete(self, key: str) -> None: ...  # no falla si ya no existe
```

`LocalFileStorage(root)` (`infrastructure/storage/local.py`) guarda en
`BILLING_DATA_DIR/uploads` (volumen `uploads` en Docker) y rechaza claves que intenten salir
de la carpeta.

| Clave | Contenido |
|---|---|
| `<uuid>.<ext>` | Archivo original de una factura o notificación (`Attachment.stored_name`) |
| `avatars/<uuid>.png` | Avatar (256×256, recortado al centro, sin EXIF) |
| `models/global/<versión>.json` | Modelo general de predicción (ver [modelos-de-prediccion.md](../modelos-de-prediccion.md)) |

La base no borra archivos: los casos de uso lo hacen al borrar compras, descartar borradores,
cambiar el avatar, eliminar la cuenta o retirar versiones antiguas del modelo general. Para AWS se añadiría un adaptador S3
(`BILLING_STORAGE=s3`) sin tocar los casos de uso.

## Identidad (Keycloak)

Puertos en `domain/ports/identity.py`; adaptador en `infrastructure/identity/keycloak.py`.
Configuración del servidor en [infraestructura/keycloak.md](../infraestructura/keycloak.md).

| Puerto | Adaptador | Para qué |
|---|---|---|
| — (Streamlit `st.login`) | `scripts/write_secrets.py` → `.streamlit/secrets.toml` | Login OIDC con el cliente `billing-app` |
| `AccountActions.url(action, return_path)` | `KeycloakActions` | URL de *application initiated actions* (`UPDATE_PASSWORD`, `CONFIGURE_TOTP`); Keycloak vuelve con `kc_action_status` |
| `AccountAdmin` | `KeycloakAccountAdmin` + `ServiceAccountToken` | Perfil, nombres, proveedores vinculados, contraseña, 2FA (`otp_enabled_since`, `remove_otp(created_before)`), sesiones, cerrar todas, borrar la cuenta |
| `Reauthenticator` | `KeycloakReauthenticator` | Reautenticación con `prompt=login&max_age=0`; canjea el `code` y valida el ID token (JWKS con `joserfc`, `iss`, `aud`, `nonce`, `sub`) |

- `ServiceAccountToken` obtiene y renueva el token de la cuenta de servicio
  `billing-admin-api` (*client credentials*; roles `view-users` y `manage-users` del realm).
- `bootstrap.account_admin(user_id)` solo se crea para el usuario autenticado: la cuenta de
  servicio podría tocar a cualquiera, así que nunca se expone un id elegido por el usuario.
- Navegador y contenedores ven Keycloak en URLs distintas: `KEYCLOAK_PUBLIC_URL` (emisor de
  los tokens y redirecciones) y `KEYCLOAK_INTERNAL_URL` (token, JWKS y API desde la app).

### Roles y permisos (`domain/auth.py`)

| Rol | Páginas | Ve | Modifica | Otros permisos |
|---|---|---|---|---|
| `admin` | Usuarios, Modelos de predicción, Estado del sistema, Auditoría, Modelo de datos, Configuración | cifras de uso de todos, nunca sus compras | las cuentas de los demás (`MANAGES_USERS_ROLES`) | categorías generales, agentes IA; no puede borrar su cuenta ni actuar sobre ella desde Usuarios |
| `customer` | Resumen, Tabla, Importar, Configuración | solo lo suyo | solo lo suyo (`TRACKS_PURCHASES_ROLES`) | categorías personales, buzones bancarios, preferencias |

Las consultas de compras siempre filtran por `viewer.user_id`; `can_modify(owner_id)` solo
permite al dueño.

### Administración de otras cuentas (`UserDirectory`, `ManagedAccount`)

`KeycloakUserDirectory` (`bootstrap.user_directory()`, solo en páginas con
`viewer.manages_users`) lista el estado de todas las cuentas, las busca por correo y las crea.
`KeycloakManagedAccount` amplía `KeycloakAccountAdmin` con `representation()`, `set_enabled`,
`set_role` (vía `role-mappings/realm/available`, sin `view-realm`) y `send_actions_email`
(`execute-actions-email`, que vuelve a `/configuracion`). Un 404 lanza `IdentityNotFound`;
`delete()` lo ignora para poder limpiar los datos de una cuenta ya borrada en Keycloak.
Detalle en [administracion.md](../aplicacion/administracion.md).

## Cifrado de secretos (`SecretCipher`)

`FernetCipher(BILLING_SECRET_KEY)` (`infrastructure/crypto/fernet.py`): AES-128-CBC + HMAC-SHA256.
Cifra las contraseñas de los buzones IMAP. Una clave ausente o inválida lanza `CipherError` (la
pestaña Correo bancario lo indica); cambiarla deja ilegibles las contraseñas guardadas.
