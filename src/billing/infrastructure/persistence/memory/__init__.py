"""Persistencia en memoria (BILLING_PERSISTENCE=memory): sin base de datos.

Sirve para desarrollo rápido y pruebas, y demuestra que los puertos bastan para
implementar otro motor. Los datos viven en el proceso: se pierden al reiniciar y no
se comparten entre la app y el worker.
"""
