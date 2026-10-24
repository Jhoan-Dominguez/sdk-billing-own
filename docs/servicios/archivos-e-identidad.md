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

La base no borra archivos: los casos de uso lo hacen al borrar compras, descartar borradores,
cambiar el avatar o eliminar la cuenta. Para AWS se añadiría un adaptador S3
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
| `admin` | todas, incluida Comparativa de clientes | datos de todos (`SEES_ALL_ROLES`) | solo lo suyo | categorías generales, agentes IA; no puede borrar su cuenta |
| `cliente` | Resumen, Tabla, Importar, Configuración | solo lo suyo | solo lo suyo | categorías personales |

`Viewer.owner_filter(selected)` devuelve el filtro de dueño que deben usar las consultas;
`can_modify(owner_id)` solo permite al dueño.

## Cifrado de secretos (`SecretCipher`)

`FernetCipher(BILLING_SECRET_KEY)` (`infrastructure/crypto/fernet.py`): AES-128-CBC + HMAC-SHA256.
Cifra las contraseñas de los buzones IMAP. Una clave ausente o inválida lanza `CipherError` (la
pestaña Correo bancario lo indica); cambiarla deja ilegibles las contraseñas guardadas.
