"""Adaptadores de extracción (puertos InvoiceExtractor y BankNotificationParser).

- documents.py    archivo -> partes (texto de email, PDFs, imágenes) -> bloques para el LLM
- regex.py        facturas solo con texto + expresiones regulares (sin red)
- extractors.py   InvoiceExtractor: agente LLM `invoice` con respaldo de regex
- bank_rules.py   plantillas de reglas de bancos colombianos
- bank.py         BankNotificationParser: reglas primero, agente `bank_notification` después
"""
