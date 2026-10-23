class ValidationError(ValueError):
    """Datos de entrada inválidos; el mensaje se muestra tal cual al usuario."""


class UnsupportedFile(ValueError):
    """Formato de archivo que la importación de facturas no admite."""


class NotFound(LookupError):
    """El recurso no existe o no es visible para quien lo pide."""
