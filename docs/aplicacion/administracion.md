# Administración

El administrador (`admin`) no lleva compras ni ve las de los clientes: solo comparte con
ellos **Configuración** (su propia cuenta). Sus páginas, en la sección «Administración» de la
barra lateral, muestran cifras de uso (cuántas compras, borradores, archivos), nunca importes
ni el detalle de una compra.

| Página (`pages/`) | URL | Contenido |
|---|---|---|
| `users.py` — Usuarios | `/usuarios` | Cuentas, estado, cifras de uso; exportar, bloquear, cambiar rol, soporte, eliminar; invitar y restaurar |
| `ml_models.py` — Modelos de predicción | `/modelos` | Modelos entrenados, versiones, métricas (acierto, error, MAE, MASE, cobertura), entrenamientos, «Entrenar ahora» |
| `system.py` — Estado del sistema | `/sistema` | Servicios, buzones y worker, agentes IA, uso, retención |
| `audit.py` — Auditoría | `/auditoria` | Acciones de los administradores, filtrables y exportables a CSV |
| `data_model.py` — Modelo de datos | `/modelo-de-datos` | Diagrama entidad-relación, detalle de tablas, migraciones (solo consulta) |

Todas empiezan con `components.admin.require_manager()` (detiene a quien no tenga
`viewer.manages_users`). Los casos de uso vuelven a comprobarlo (`accounts.require_manager`) y
lanzan `PermissionDenied`.

## Cuentas (`application/admin/accounts.py`)

`overview(uow, actor, statuses)` cruza la tabla `users` con el estado de Keycloak
(`UserDirectory.statuses()`, 30 s de caché en la página) y las cifras de
`purchases.count_by_owner()`, `attachments.usage_by_owner()` y los buzones. Las cuentas que la
app conoce pero Keycloak no (borradas desde su consola) se marcan «Sin cuenta en Keycloak»: solo
se pueden exportar o eliminar.

| Acción | Keycloak | App |
|---|---|---|
| Bloquear | `enabled=false` y cierra sus sesiones | `users.disabled_at`; `app.py` expulsa en la siguiente interacción a quien tenga una sesión abierta |
| Desbloquear | `enabled=true` | `disabled_at = NULL` |
| Cambiar rol | Deja el rol nuevo como único rol de la app asignado y cierra sus sesiones | `users.role` |
| Cerrar sesiones | `POST /users/{id}/logout` | — |
| Forzar cambio de contraseña | Correo `execute-actions-email` con `UPDATE_PASSWORD` y cierra sesiones | — |
| Quitar 2FA | Borra sus credenciales OTP (perdió el teléfono) | — |
| Reenviar verificación | Correo con `VERIFY_EMAIL` | — |
| Invitar | Crea la cuenta (sin contraseña) con su rol y envía `VERIFY_EMAIL` + `UPDATE_PASSWORD` | Aparece en `users` en su primer inicio de sesión |
| Eliminar | Borra la cuenta (si ya no existía, sigue) | `users.delete_account`: compras, borradores, archivos, avatar, buzones, modelos |

Reglas: nadie actúa sobre su propia cuenta desde aquí (usa Configuración) y siempre queda al
menos un administrador activo. Los correos de acciones vuelven a `/configuracion`, que es una
URI registrada del cliente `billing-app`. La cuenta de servicio `billing-admin-api` basta con
`view-users` + `manage-users`: los roles se asignan con `role-mappings/realm/available`.

## Exportación y restauración (`application/admin/backup.py`)

La exportación es un ZIP pensado para recrear al usuario después de eliminarlo:

```
manifest.json   formato (billing-user-export), versión, fecha, quién, conteos, archivos con sha256
data.json       {"identity": ficha de Keycloak, "tables": filas por tabla con ids y claves originales}
files/<stored_name>   facturas y correos
avatar/<nombre>       avatar
```

Tablas: `users`, `categories` (solo las personales), `mailbox_connections`, `purchases`,
`purchase_items` (con `purchase_id`) y `attachments` (con `purchase_id`; los borradores lo
tienen en `null`). No se exportan modelos de predicción ni confirmaciones de seguridad.

La restauración (`plan_restore` para la vista previa, `restore_user` para ejecutarla):

1. Valida el ZIP sin extraerlo a disco: tamaño total, formato y versión, JSON y sha256 de cada archivo.
2. Si el usuario exportado sigue en la app, se rechaza (duplicaría sus datos).
3. Si existe una cuenta en Keycloak con ese correo, los datos se cargan en ella. Si no, se crea
   (`UserDirectory.create`) y recibe el correo para fijar su contraseña: Keycloak no exporta
   contraseñas ni secretos 2FA. **El id cambia**: la API de usuarios ignora el `id` y conservarlo
   exigiría `partialImport` con `manage-realm`; por eso se remapean todas las claves.
4. Fase 1 (commit): usuario, categorías que no choquen y buzones. Las contraseñas IMAP viajan
   cifradas; si no se pueden descifrar (otra `BILLING_SECRET_KEY`), el buzón queda desactivado
   con un aviso. Se conservan `uid_validity`/`last_uid` para no reimportar correos.
5. Fase 2 (commit): compras con líneas y adjuntos, y borradores. Los archivos se guardan con un
   nombre nuevo. Un borrador de un correo que la cuenta ya tiene se omite.
6. Si algo falla, se borran los archivos guardados, se deshace la fase 1 y, si se creó la
   cuenta en Keycloak, se elimina.

El ZIP contiene datos personales y contraseñas IMAP cifradas: hay que guardarlo en un lugar seguro.

## Auditoría (`application/admin/audit.py`)

Tabla `admin_audit_log` sin claves foráneas, para que la entrada sobreviva al borrado de quien
actuó y del afectado; por eso guarda también sus etiquetas (correo o nombre de ese momento).
Acciones en `domain/admin.py` (`ACTION_LABELS`). `audit.record` guarda en su propia transacción.

## Estado del sistema (`application/admin/system.py`)

- **Servicios**: `check_services(bootstrap.service_checks())` — base de datos, Keycloak (token
  de la cuenta de servicio) y SMTP (`SmtpMailer.check()`: conecta sin enviar).
- **Buzones y worker**: el worker corre en otro contenedor; su latido visible es la última
  sincronización. Si ningún buzón activo se sincronizó en tres intervalos
  (`BILLING_MAIL_SYNC_INTERVAL`), se avisa. Lista los buzones con error y los atrasados.
- **Agentes IA**: `attachments.extraction_log` por tipo de documento, método (agente o reglas),
  proveedor y modelo: documentos, errores y tiempo medio.
- **Uso**: usuarios por rol, activos y nuevos en 30 días, bloqueados, compras, borradores,
  archivos, y compras registradas por mes y origen (cantidad, nunca importes).
- **Retención**: purgar borradores sin revisar más antiguos que N días (con sus archivos) y
  listar cuentas sin iniciar sesión en N meses.

## Modelos de predicción

`application/forecasting/models.py` expone `overview()` para la página: modelos (`ml_models`,
por cliente y moneda), entrenamientos (`ml_training_runs`), acierto medio de los activos e
historial de versiones; y `train_now()` para el botón «Entrenar ahora» (reentrena todo,
incluido el general, y queda en la auditoría). Métricas en `domain/forecasting.py`:

| Clave | Significado |
|---|---|
| `mape` | Error porcentual medio; **acierto** = 100 − MAPE |
| `mae` | Error absoluto medio (moneda del cliente, o proporción en el modelo general) |
| `mase` | Error frente a repetir el mes anterior; < 1 = el modelo aporta |
| `coverage` | % de meses cuyo gasto real cayó en el rango P10–P90 (ideal ≈ 80 %) |

Cómo se entrenan, dónde se guardan y qué ve el cliente: [modelos-de-prediccion.md](../modelos-de-prediccion.md).

## Modelo de datos

`PersistenceBackend.describe_schema()` devuelve un `domain.schema.SchemaInfo`. El adaptador SQL
(`sqlalchemy/schema.py`) inspecciona la base real (no `tables.py`): tablas, columnas, claves,
índices, filas y migraciones aplicadas/pendientes de Alembic. El motor en memoria devuelve
`None`. La página dibuja el diagrama con `st.graphviz_chart` (DOT generado en la página).
