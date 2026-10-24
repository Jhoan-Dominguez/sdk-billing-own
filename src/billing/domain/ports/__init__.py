"""Puertos: interfaces que la aplicación necesita y la infraestructura implementa.

Para añadir otro motor de base de datos, almacenamiento, proveedor de identidad, LLM,
servidor de correo o extractor basta con implementar el puerto correspondiente y
registrarlo en el registro de su servicio (infrastructure/<servicio>/registry.py);
ni el dominio ni los casos de uso cambian.

- repositories.py  persistencia (UnitOfWork + repositorios)
- storage.py       archivos
- identity.py      cuenta del usuario en el proveedor de identidad, reautenticación
- llm.py           modelos de lenguaje
- extraction.py    lectura de facturas y notificaciones bancarias
- mail.py          envío de correos y lectura de buzones IMAP
- crypto.py        cifrado de secretos guardados
"""
