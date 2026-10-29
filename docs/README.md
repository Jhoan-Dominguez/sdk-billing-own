# Documentación técnica

Documentación de construcción y funcionamiento de **Registro de compras**. El
[README principal](../README.md) es la guía rápida; aquí está el detalle de cada pieza.

## Mapa

| Documento | Qué cubre |
|---|---|
| [arquitectura.md](arquitectura.md) | Capas hexagonales, dependencias, composition root, registros de adaptadores, árbol de carpetas |
| [configuracion.md](configuracion.md) | Todas las variables de entorno, valores por defecto y quién las lee |
| [modelo-de-datos.md](modelo-de-datos.md) | Entidades, tablas, columnas, índices, relaciones y migraciones |
| [modelos-de-prediccion.md](modelos-de-prediccion.md) | Modelos de predicción del gasto: datos, LightGBM y ETS, combinación, métricas, almacenamiento, entrenamiento, consumo, operación |
| **Servicios** | |
| [servicios/seguridad.md](servicios/seguridad.md) | 2FA, verificación de cuentas por correo, confirmaciones de acciones sensibles |
| [servicios/agentes.md](servicios/agentes.md) | Agentes LLM y proveedores intercambiables (Anthropic, OpenAI, Gemini, Ollama) |
| [servicios/persistencia.md](servicios/persistencia.md) | Base de datos intercambiable: PostgreSQL, SQLite, MySQL, memoria; cómo añadir un motor |
| [servicios/facturas.md](servicios/facturas.md) | Reconocimiento de facturas (imágenes, PDFs, correos) con LLM y reglas |
| [servicios/correos-bancarios.md](servicios/correos-bancarios.md) | Notificaciones bancarias: plantillas de bancos colombianos, agente LLM, buzones IMAP, worker |
| [servicios/correo.md](servicios/correo.md) | Envío de correos (SMTP) y lectura de buzones (IMAP) |
| [servicios/archivos-e-identidad.md](servicios/archivos-e-identidad.md) | Almacenamiento de archivos, Keycloak como proveedor de identidad, cifrado de secretos |
| **Aplicación** | |
| [aplicacion/casos-de-uso.md](aplicacion/casos-de-uso.md) | Referencia de cada módulo de `application/` y sus funciones |
| [aplicacion/interfaz.md](aplicacion/interfaz.md) | Páginas Streamlit, componentes, permisos por rol y convenciones de estado |
| [aplicacion/administracion.md](aplicacion/administracion.md) | Panel del administrador: cuentas, exportación/restauración, auditoría, estado, modelos, modelo de datos |
| **Infraestructura** | |
| [infraestructura/docker.md](infraestructura/docker.md) | Servicios de Docker Compose, imágenes, puertos, volúmenes, healthchecks |
| [infraestructura/keycloak.md](infraestructura/keycloak.md) | Realm, clientes, roles, usuarios, flujos de autenticación, temas, SMTP |
| [infraestructura/correo-de-pruebas.md](infraestructura/correo-de-pruebas.md) | Mailpit (correo saliente) y GreenMail (bandeja IMAP de pruebas) |
| [infraestructura/aws-terraform.md](infraestructura/aws-terraform.md) | Esqueleto de despliegue en AWS |
| [desarrollo.md](desarrollo.md) | Puesta en marcha, comandos `make`, scripts, verificación, convenciones |

## Glosario

- **Puerto**: interfaz (`typing.Protocol`) que la aplicación necesita, en `domain/ports/`.
- **Adaptador**: implementación concreta de un puerto, en `infrastructure/`.
- **Agente**: tarea LLM concreta (instrucciones + esquema de salida) que se ejecuta con cualquier proveedor.
- **Borrador**: adjunto importado sin compra asociada (`attachments.purchase_id IS NULL`), pendiente de revisión.
- **Confirmación de seguridad**: solicitud de una acción sensible que exige correo y, si aplica, código 2FA.
- **Viewer**: el usuario autenticado y lo que puede ver/modificar (`domain/auth.py`).
- **Auditoría**: registro de las acciones de los administradores (`admin_audit_log`).
- **Exportación de usuario**: ZIP con las filas y archivos de un usuario para recrearlo con «Restaurar».
- **Serie**: gasto mensual de un cliente en una moneda (meses completos), derivado de las compras.
- **Modelo general / por cliente**: LightGBM entrenado con las series de todos (normalizadas) /
  suavizado exponencial entrenado con la serie de un cliente.
- **P10 / P50 / P90**: cuantiles de una predicción; P10–P90 es el rango probable (80 %).
