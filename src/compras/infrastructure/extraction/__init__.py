"""Adaptadores de extracción de facturas (puerto InvoiceExtractor).

- documents.py   archivo -> partes (texto de email, PDFs, imágenes)
- regex.py       extractor local: solo texto + expresiones regulares (sin red)
- claude.py      lectura con la API de Anthropic (imágenes y PDFs escaneados)
- extractors.py  los adaptadores que usa la app, con fallback a regex
"""
