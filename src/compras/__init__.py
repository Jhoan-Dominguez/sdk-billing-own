"""Registro de compras mensuales.

Arquitectura hexagonal (puertos y adaptadores), de dentro hacia fuera:

- domain/          entidades, reglas y puertos (interfaces). Sin frameworks.
- application/     casos de uso; solo dependen de domain (y de los puertos).
- infrastructure/  adaptadores: base de datos, archivos, identidad, IA.
- presentation/    interfaces de usuario (Streamlit); llaman a application.
- bootstrap.py     composition root: elige y conecta los adaptadores.
"""
