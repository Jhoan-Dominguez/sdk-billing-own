# Interfaz web (Streamlit)

Código en `src/billing/presentation/streamlit/`. Se arranca con `python -m billing` (o
`make dev`), que ejecuta `streamlit run app.py`. Textos en español; identificadores en inglés.

## Entrada (`app.py`)

1. Sin sesión → `login_screen()` vacía `st.session_state` y llama a `st.login("keycloak")`
   (redirección directa al tema de login de Keycloak) y se detiene.
2. Con sesión → `Viewer` desde los claims. Sin rol de la app → error y botón de cerrar sesión.
3. `ensure_database()` aplica las migraciones una vez por proceso (`st.cache_resource`).
4. Sincroniza el usuario una vez por sesión y guarda el `Viewer` en `st.session_state["viewer"]`.
5. Si el usuario está bloqueado (`users.disabled_at`), error, botón de cerrar sesión y se detiene.
6. `st.navigation` con las páginas del rol (`PAGE_SPECS`; la primera es la de inicio). Las del
   administrador van en la sección «Administración». «Importar facturas (N)» muestra los
   borradores pendientes.
7. Barra lateral: avatar, nombre, rol, cerrar sesión y el lector de facturas activo (proveedor y modelo).

Cerrar sesión usa `session.logout()`, no `st.logout` directamente: además de borrar la cookie
y terminar la sesión de Keycloak, vacía `st.session_state` (el `Viewer`, filtros...). Y
`reload_on_back_cache()` recarga la página si el navegador la restaura desde su caché de
atrás/adelante (bfcache): así, al volver atrás tras cerrar sesión no queda una interfaz vieja
utilizable, sino que se valida otra vez la cookie y se redirige al login.

## Páginas (`pages/`)

| Página | Rol | Contenido |
|---|---|---|
| `summary.py` (`/resumen`) — Resumen general | customer | Gasto del mes, compras, categoría y comercio principales; en el mes en curso, la proyección (cierre estimado, mes siguiente, aviso); barras por mes, categoría, método y comercio (por moneda) |
| `summary_table.py` (`/tabla_resumen`) — Tabla resumen | customer | Compras del mes con filtro por categoría, detalle con adjuntos, editar, eliminar, exportar CSV y «Agregar compra» |
| `imports.py` (`/importar`) — Importar facturas | customer | Subir archivos o tomar foto; borradores (facturas y alertas bancarias, también las de buzones) con vista previa, datos de extracción, avisos y formulario de confirmación |
| `users.py`, `ml_models.py`, `system.py`, `audit.py`, `data_model.py` | admin | Ver [administracion.md](administracion.md) |
| `settings.py` (`/configuracion`) — Configuración | todos | Pestañas: Perfil, Seguridad, Cuenta, (customer) Correo bancario y Preferencias, Categorías y (admin) Agentes IA |

### Pestañas de Configuración (`components/settings/`)

| Módulo | Pestaña | Contenido |
|---|---|---|
| (página) | Perfil | Avatar; nombre y apellido (guardados en Keycloak) |
| `security.py` | Seguridad | Cambiar contraseña (correo); 2FA: activar, cambiar dispositivo y desactivar (correo + código); sesiones abiertas y cerrar todas. `handle_return()` procesa `?confirmar=`, `?state&code` y `?kc_action_status` |
| `account.py` | Cuenta | Información (incluye el estado del 2FA) y eliminar la cuenta (correo + código si hay 2FA) |
| `mailboxes.py` | Correo bancario | Conectar, probar, editar, sincronizar y desconectar buzones IMAP; ayuda para Gmail, Outlook y GreenMail |
| (página) | Preferencias | Moneda, método de pago y categoría por defecto |
| (página) | Categorías | Generales (admin) o personales (customer): crear, renombrar, eliminar |
| `agents.py` | Agentes IA | Estado de proveedores; proveedor y modelo por agente; guardar, restablecer, probar |

`context.py` → `SettingsContext`: viewer, claims, `AccountAdmin`, `AccountActions`,
`FileStorage`, perfil de Keycloak y error si no está disponible. `RETURN_PATH = "/configuracion"`.

`confirmation_flow(ctx, uow, purpose, …)` es el componente común de las acciones sensibles:
sin solicitud muestra el botón que envía el correo; con solicitud muestra los pasos
(✓ correo, ✓ código 2FA), «Verificar con mi código 2FA» (enlace a Keycloak), el botón o enlace
final, «Reenviar correo» y «Cancelar solicitud».

## Componentes (`components/`)

| Módulo | Contenido |
|---|---|
| `session.py` | `ensure_database`, `user_claims`, `current_viewer` (detiene la página sin Viewer), `login_screen` |
| `layout.py` | `apply_styles`, `flash`/`show_flash` (avisos tras `st.rerun`), `page_header` (título y mes) |
| `forecast.py` | `render(owner_id, history, preferred)`: proyección por moneda con gráfico de real vs. previsto |
| `admin.py` | `require_manager`, `user_directory`, `identity_statuses` (caché de 30 s), `human_bytes`, `when` |
| `forms.py` | `form_options(viewer)`, `purchase_form(key, values, items, …)` con `st.data_editor` para las líneas |
| `files.py` | `show_attachment`, `draft_label`, `extraction_info`, `draft_warnings` |
| `formatting.py` | `month_label`, `money`, `to_float` |
| `profile.py` | `current_user`, `avatar`, `initials` |
| `assets/styles.css` | Botones `confirm-delete*` en rojo |

## Convenciones de estado

- Los widgets tienen `key`. Para reiniciar un formulario tras guardar se incrementa un contador
  que forma parte de la clave (`upload_no`, `avatar_no`, `mailbox_no`).
- Un widget no se puede cambiar después de crearlo en la misma ejecución: otras páginas piden
  un mes con `st.session_state["goto_month"]`, que `page_header` aplica antes de dibujar el selector.
- `flash(mensaje)` + `st.rerun()` para avisos después de una acción.
- Las páginas abren `with bootstrap.unit_of_work() as uow:` y pintan dentro del bloque
  (las relaciones se cargan bajo demanda).
- La URL de reautenticación de una solicitud se genera una vez por sesión
  (`reauth-url-<id>` en `session_state`).
- Los enlaces a Keycloak (`st.link_button`) se abren en otra pestaña y vuelven a `/configuracion`.

## Tema

`.streamlit/config.toml`: verde Vue `#42b883` como color de marca (barra lateral, botones
primarios), componentes en neutros, paleta categórica azul/naranja/violeta/rosa validada para
daltonismo, rampa secuencial azul para magnitudes; el rojo se reserva para errores y acciones
destructivas.
